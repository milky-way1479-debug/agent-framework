"""Proposal -> owner decision -> single-use mock execution -> verified report."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ledger import Ledger
from .policy import GovernanceError, Policy, canonical


@dataclass(frozen=True)
class Proposal:
    operation_id: str
    tool: str
    arguments_json: str
    norm_revision: str
    policy_revision: str
    cost_units: int
    task_expires_at: float
    purpose: str
    effect: str = "Local mock only; no network, file mutation or real-world action"


@dataclass(frozen=True)
class Report:
    operation_id: str
    status: str
    verified: bool
    output: Any = None
    limitation: str = "Mock execution; no claim of real-world effect"


class _OwnerAuthority:
    """In-process capability created only by the trusted host, never sent to the model."""


class ExecutionContext:
    def __init__(self, runtime: GovernanceRuntime, task_id: str):
        self._runtime, self.task_id = runtime, task_id

    def stopped(self) -> bool:
        try:
            self._runtime.check_task(self.task_id)
            return False
        except GovernanceError:
            return True


MockHandler = Callable[[dict[str, Any], ExecutionContext], Awaitable[Any]]
Verifier = Callable[[dict[str, Any], Any], bool]


class GovernanceRuntime:
    def __init__(self, policy: Policy, ledger_path: Path, audit_key: bytes, *, clock=time.time):
        self.policy, self.ledger = policy, Ledger(ledger_path, audit_key)
        self.clock = clock
        self.owner_authority = _OwnerAuthority()
        self._blocked: set[str] = set()
        self._handlers: dict[str, tuple[MockHandler, Verifier]] = {}

    def _owner(self, authority: object) -> None:
        if authority is not self.owner_authority:
            raise GovernanceError("An authenticated host owner decision is required")

    def register_mock(self, name: str, handler: MockHandler, verifier: Verifier, authority: object) -> None:
        self._owner(authority)
        if name not in self.policy.tools or name in self._handlers:
            raise GovernanceError("Mock tool is absent from policy or already registered")
        self._handlers[name] = (handler, verifier)

    def _task(self, db, task_id: str):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise GovernanceError("Unknown task")
        current = row
        while current:
            if current["stopped"] or current["id"] in self._blocked or current["expires"] <= self.clock():
                raise GovernanceError("Task or ancestor stopped or expired")
            if not current["parent"]:
                break
            current = db.execute("SELECT * FROM tasks WHERE id=?", (current["parent"],)).fetchone()
            if current is None:
                raise GovernanceError("Cannot verify parent task")
        return row

    def check_task(self, task_id: str) -> None:
        self.policy.assert_integrity()
        with self.ledger.transaction() as db:
            self._task(db, task_id)

    def create_task(
        self, tools: list[str], authority: object, *, parent: str | None = None, lifetime: int = 300
    ) -> str:
        self._owner(authority)
        self.policy.assert_integrity()
        if (
            not tools
            or not set(tools) <= set(self.policy.tools)
            or type(lifetime) is not int
            or lifetime <= 0
        ):
            raise GovernanceError("Task scope or lifetime invalid")
        task_id = secrets.token_hex(16)
        expires = self.clock() + min(lifetime, self.policy.settings["max_task_seconds"])
        with self.ledger.transaction() as db:
            root, depth = task_id, 0
            if parent:
                p = self._task(db, parent)
                if not set(tools) <= set(json.loads(p["tools"])):
                    raise GovernanceError("Delegation cannot expand parent scope")
                root, depth, expires = p["root"], p["depth"] + 1, min(expires, p["expires"])
            if depth > self.policy.settings["max_depth"]:
                raise GovernanceError("Delegation depth exceeded")
            count = db.execute("SELECT COUNT(*) FROM tasks WHERE root=?", (root,)).fetchone()[0]
            if count >= self.policy.settings["max_tasks"]:
                raise GovernanceError("Shared delegation limit exceeded")
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    parent,
                    root,
                    canonical(sorted(set(tools))),
                    expires,
                    0,
                    depth,
                    0,
                    self.policy.settings["max_operations"],
                ),
            )
            self.ledger.event(db, "task_created", task=task_id, parent=parent, timestamp=self.clock())
        return task_id

    def propose(self, task_id: str, name: str, arguments: dict[str, Any]) -> Proposal:
        payload = self.policy.validate_arguments(name, arguments)
        fingerprint = self.ledger.digest(name + ":" + payload)
        op_id = secrets.token_hex(16)
        digest = self.ledger.digest(
            canonical([task_id, name, payload, self.policy.norm_revision, self.policy.policy_revision])
        )
        with self.ledger.transaction() as db:
            task = self._task(db, task_id)
            if name not in json.loads(task["tools"]) or name not in self._handlers:
                raise GovernanceError("Tool outside task scope or not registered")
            previous = db.execute(
                "SELECT id FROM operations WHERE fingerprint=? LIMIT 1", (fingerprint,)
            ).fetchone()
            if previous:
                raise GovernanceError(
                    "Matching operation already exists; host review required, no automatic resubmission"
                )
            count = db.execute(
                "SELECT COUNT(*) FROM operations WHERE task IN (SELECT id FROM tasks WHERE root=?)",
                (task["root"],),
            ).fetchone()[0]
            if count >= self.policy.settings["max_operations"]:
                raise GovernanceError("Shared proposal limit exceeded")
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    op_id,
                    task_id,
                    name,
                    digest,
                    fingerprint,
                    self.policy.norm_revision + ":" + self.policy.policy_revision,
                    "PROPOSED",
                    None,
                    None,
                ),
            )
            self.ledger.event(
                db, "proposed", operation=op_id, task=task_id, tool=name, timestamp=self.clock()
            )
        return Proposal(
            op_id,
            name,
            payload,
            self.policy.norm_revision,
            self.policy.policy_revision,
            self.policy.tools[name]["cost_units"],
            task["expires"],
            self.policy.settings["purpose"],
        )

    def decide(self, operation_id: str, approved: bool, authority: object, *, lifetime: int = 60) -> None:
        self._owner(authority)
        if type(approved) is not bool or type(lifetime) is not int or lifetime <= 0:
            raise GovernanceError("Explicit boolean decision and positive lifetime required")
        self.policy.assert_integrity()
        with self.ledger.transaction() as db:
            op = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            if op is None or op["status"] != "PROPOSED":
                raise GovernanceError("No pending proposal; approval cannot be replayed")
            task = self._task(db, op["task"])
            until = min(
                task["expires"], self.clock() + min(lifetime, self.policy.settings["max_approval_seconds"])
            )
            db.execute(
                "UPDATE operations SET status=?,approval_until=? WHERE id=?",
                ("APPROVED" if approved else "REJECTED", until if approved else None, operation_id),
            )
            self.ledger.event(
                db,
                "owner_approved" if approved else "owner_rejected",
                operation=operation_id,
                timestamp=self.clock(),
            )

    def stop(self, task_id: str, authority: object) -> None:
        self._owner(authority)
        # Local stopping is immediate, even if persistent audit/storage has failed.
        self._blocked.add(task_id)
        with self.ledger.transaction() as db:
            rows = db.execute(
                """WITH RECURSIVE descendants(id) AS (
                SELECT id FROM tasks WHERE id=? UNION ALL
                SELECT t.id FROM tasks t JOIN descendants d ON t.parent=d.id)
                SELECT id FROM descendants""",
                (task_id,),
            ).fetchall()
            if not rows:
                raise GovernanceError("Unknown task")
            for row in rows:
                self._blocked.add(row["id"])
                db.execute("UPDATE tasks SET stopped=1 WHERE id=?", (row["id"],))
                db.execute(
                    "UPDATE operations SET status='CANCELLED',approval_until=NULL "
                    "WHERE task=? AND status IN ('PROPOSED','APPROVED')",
                    (row["id"],),
                )
            self.ledger.event(db, "stopped", task=task_id, timestamp=self.clock())

    def cancel_operation(self, operation_id: str, authority: object) -> None:
        self._owner(authority)
        with self.ledger.transaction() as db:
            op = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            if op is None or op["status"] not in ("PROPOSED", "APPROVED"):
                raise GovernanceError(
                    "Cannot cancel a started operation; stop its task and reconcile results"
                )
            db.execute(
                "UPDATE operations SET status='CANCELLED',approval_until=NULL WHERE id=?", (operation_id,)
            )
            self.ledger.event(db, "owner_cancelled", operation=operation_id, timestamp=self.clock())

    def recover_interrupted(self, authority: object) -> int:
        self._owner(authority)
        # Only after the host confirms no executor is still running. Never retry.
        with self.ledger.transaction() as db:
            count = db.execute("SELECT COUNT(*) FROM operations WHERE status='RUNNING'").fetchone()[0]
            db.execute("UPDATE operations SET status='RESULT_UNKNOWN' WHERE status='RUNNING'")
            self.ledger.event(db, "interrupted_reconciled_as_unknown", count=count, timestamp=self.clock())
            return count

    async def execute(self, operation_id: str, arguments: dict[str, Any]) -> Report:
        self.policy.assert_integrity()
        with self.ledger.transaction() as db:
            op = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            if op is None or op["status"] != "APPROVED":
                raise GovernanceError("No unused approval for this operation")
            task = self._task(db, op["task"])
            payload = self.policy.validate_arguments(op["name"], arguments)
            expected = self.ledger.digest(
                canonical(
                    [op["task"], op["name"], payload, self.policy.norm_revision, self.policy.policy_revision]
                )
            )
            if (
                op["digest"] != expected
                or op["revision"] != self.policy.norm_revision + ":" + self.policy.policy_revision
            ):
                raise GovernanceError("Approved arguments or norm/policy version do not match")
            if op["approval_until"] is None or op["approval_until"] <= self.clock():
                raise GovernanceError("Approval expired")
            if op["name"] not in self._handlers or op["name"] not in json.loads(task["tools"]):
                raise GovernanceError("No registered, scoped execution path")
            spec = self.policy.tools[op["name"]]
            root = self._task(db, task["root"])
            if root["used"] + spec["cost_units"] > root["limit_units"]:
                raise GovernanceError("Shared execution budget exhausted")
            db.execute("UPDATE tasks SET used=used+? WHERE id=?", (spec["cost_units"], task["root"]))
            db.execute(
                "UPDATE operations SET status='RUNNING',approval_until=NULL WHERE id=?", (operation_id,)
            )
            self.ledger.event(db, "execution_started", operation=operation_id, timestamp=self.clock())
        handler, verifier = self._handlers[op["name"]]
        # The serialized payload is the exact approved snapshot, unaffected by caller mutation.
        frozen_arguments = json.loads(payload)
        ctx = ExecutionContext(self, op["task"])
        output, status, verified, output_digest = None, "RESULT_UNKNOWN", False, None
        cancelled = False
        try:
            output = await asyncio.wait_for(handler(frozen_arguments, ctx), timeout=spec["timeout_seconds"])
            verified = verifier(json.loads(payload), output) is True
            output_digest = self.ledger.digest(canonical(output)) if verified else None
            status = "COMPLETED" if verified else "UNVERIFIED"
        except asyncio.CancelledError:
            cancelled = True
        except Exception:  # noqa: BLE001 - arbitrary reviewed callback failures must never imply no effect
            # Do not leak exception strings containing secrets or infer no effect.
            status = "RESULT_UNKNOWN"
            verified = False
        with self.ledger.transaction() as db:
            updated = db.execute(
                "UPDATE operations SET status=?,output_digest=? WHERE id=? AND status='RUNNING'",
                (status, output_digest, operation_id),
            )
            if updated.rowcount != 1:
                raise GovernanceError("Execution state changed; reconcile before declaring completion")
            self.ledger.event(
                db,
                "execution_report",
                operation=operation_id,
                status=status,
                verified=verified,
                timestamp=self.clock(),
            )
        if cancelled:
            raise asyncio.CancelledError
        return Report(operation_id, status, verified, output if verified else None)

    def status(self, operation_id: str) -> str:
        with self.ledger.transaction() as db:
            row = db.execute("SELECT status FROM operations WHERE id=?", (operation_id,)).fetchone()
            if row is None:
                raise GovernanceError("Unknown operation")
            return row[0]
