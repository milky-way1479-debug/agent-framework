"""Gateway reuses governance checks; a separate recorder must acknowledge every important event."""

from __future__ import annotations

import asyncio
import contextvars
import json
import secrets
import threading
from dataclasses import asdict, dataclass
from functools import wraps
from typing import Any

from agent_framework.observability import get_tracer
from opentelemetry import trace

from ..policy import GovernanceError, canonical
from ..runtime import GovernanceRuntime, Proposal
from .client import RecorderClient


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._control_lock:
            return method(self, *args, **kwargs)

    return call


@dataclass(frozen=True)
class Notice:
    """5W1H claims. Free text is for human review, never a permission or tool instruction."""

    who: str
    what: str
    when: float
    where: str
    why: str
    how: str


class ExecutionGateway(GovernanceRuntime):
    """Trusted host only. Models receive a task-bound proposal tool, not this object.

    Existing direct runtime users remain unchanged and are NOT automatically recorded.
    All outbound destinations are denied in this offline MVP (an empty allowlist).
    """

    def __init__(self, policy, ledger_path, audit_key, recorder: RecorderClient, **kwargs):
        super().__init__(policy, ledger_path, audit_key, **kwargs)
        self.recorder = recorder
        self._audit_failed = False
        self._control_lock = threading.RLock()
        self._owner_id = self.ledger.digest("local-terminal-owner/research")
        self._pending: dict[str, dict] = {}
        self._agent_ids: dict[str, str] = {}
        self._executing = contextvars.ContextVar("flight_execution", default=None)
        self._active: set[str] = set()
        self.tracer = get_tracer("human_agent_governance.flight_recorder", "0.1.0")
        # Verify recorder before offering a proposal tool. No auto-resume of old pending approvals.
        recorder.read()

    def _emit(self, event: str, **fields):
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            fields.update(trace_id=f"{context.trace_id:032x}", span_id=f"{context.span_id:016x}")
        try:
            return self.recorder.append({"event": event, "timestamp": self.clock(), **fields})
        except Exception as exc:
            self._audit_failed = True
            raise GovernanceError("Independent audit unavailable; gateway held") from exc

    def record_refusal(self):
        self._emit("denied", request_id=secrets.token_hex(16), status="DENIED", reason="policy_or_authority")

    def _healthy(self):
        if self._audit_failed:
            raise GovernanceError("Audit failure latched; operator reconciliation required")

    def check_task(self, task_id):
        self._healthy()
        super().check_task(task_id)

    @_serialized
    def create_task(self, tools, authority, **kwargs):
        self._healthy()
        task = super().create_task(tools, authority, **kwargs)
        agent = secrets.token_hex(16)  # Assigned by trusted host, not agent-supplied identity.
        self._agent_ids[task] = agent
        self._emit("task_created", task_id=task, agent_id=agent)
        return task

    def register_mock(self, name, handler, verifier, authority):
        self._owner(authority)

        async def recorded_handler(arguments, context):
            fields = self._executing.get()
            if not fields:
                raise GovernanceError("No gateway execution context")
            self._healthy()
            # Called only AFTER core atomic approval consumption, budget and scope validation.
            self._emit("permission_allowed", **fields)
            self._emit("execution_started", status="RUNNING", **fields)
            if context.stopped():
                raise GovernanceError("Stopped before callback")
            return await handler(arguments, context)

        super().register_mock(name, recorded_handler, verifier, authority)

    def _command(self, task, name, payload):
        return self.ledger.digest(
            canonical(
                {
                    "task": task,
                    "agent": self._agent_ids.get(task),
                    "tool": name,
                    "payload": payload,
                    "destination": "local://mock",
                    "norm": self.policy.norm_revision,
                    "policy": self.policy.policy_revision,
                }
            )
        )

    @_serialized
    def propose(
        self, task_id: str, name: str, arguments: dict[str, Any], notice: Notice | None = None
    ) -> Proposal:
        self._healthy()
        request_id = secrets.token_hex(16)
        fields = {"request_id": request_id}
        self._emit("request", **fields)
        try:
            if task_id not in self._agent_ids:
                raise GovernanceError("Task not created by this gateway")
            # Do not allow multiple outstanding requests in one task (LAW-011).
            if any(p["task_id"] == task_id for p in self._pending.values()):
                raise GovernanceError("One pending request per task")
            payload = self.policy.validate_arguments(name, arguments)
            digest = self._command(task_id, name, payload)
            with self.ledger.transaction() as db:
                task = self._task(db, task_id)
            expected = Notice(
                self._agent_ids[task_id],
                name,
                task["expires"],
                "local://mock",
                self.policy.settings["purpose"],
                digest,
            )
            # Optional AI claims must exactly match facts. A lie is a refusal, not rewritten silently.
            if notice is not None and (type(notice) is not Notice or notice != expected):
                raise GovernanceError("5W1H differs from system command")
            proposal = super().propose(task_id, name, json.loads(payload))
            fields.update(
                execution_id=proposal.operation_id,
                task_id=task_id,
                agent_id=expected.who,
                tool_id=name,
                command_digest=digest,
                notice_digest=self.ledger.digest(canonical(asdict(expected))),
                norm_revision=self.policy.norm_revision,
                policy_revision=self.policy.policy_revision,
            )
            self._emit("proposal", status="PENDING", **fields)
            self._pending[proposal.operation_id] = {
                **fields,
                "proposal": proposal,
                "notice": expected,
                "approval_id": None,
            }
            return proposal
        except GovernanceError:
            self._emit("denied", status="DENIED", reason="policy_or_authority", request_id=request_id)
            raise

    def preview(self, operation_id: str, authority: object) -> dict:
        self._owner(authority)
        pending = self._pending.get(operation_id)
        if not pending:
            raise GovernanceError("No reviewable command in this host session")
        proposal = pending["proposal"]
        return {
            "operation_id": operation_id,
            "notice": asdict(pending["notice"]),
            "arguments": json.loads(proposal.arguments_json),
            "cost_units": proposal.cost_units,
            "effect": proposal.effect,
            "verification": "Registered host verifier must return literal True",
            "risk": "Mock only; timeout/crash may leave result unknown; no automatic retry",
            "recovery": "Stop and reconcile. Previous effects are not undone.",
            "approval_id": pending["approval_id"],
        }

    @staticmethod
    def _fields(pending):
        return {
            key: value
            for key, value in pending.items()
            if key not in {"proposal", "notice"} and value is not None
        }

    @_serialized
    def decide(self, operation_id, approved, authority, *, lifetime=60):
        self._healthy()
        request_id = secrets.token_hex(16)
        self._emit("decision_requested", request_id=request_id)
        try:
            self._owner(authority)
            pending = self._pending[operation_id]
            if pending["approval_id"] is not None:
                raise GovernanceError("Decision already made")
            super().decide(operation_id, approved, authority, lifetime=lifetime)
            pending["approval_id"] = secrets.token_hex(16)
            self._emit(
                "approved" if approved else "rejected",
                status="APPROVED" if approved else "REJECTED",
                owner_id=self._owner_id,
                **self._fields(pending),
            )
            if not approved:
                # Rejection ends the task, preventing agent resubmission under another operation ID.
                super().stop(pending["task_id"], authority)
                self._emit("stopped", task_id=pending["task_id"], status="STOPPED")
                del self._pending[operation_id]
        except (GovernanceError, KeyError):
            self._emit("denied", request_id=request_id, status="DENIED", reason="policy_or_authority")
            raise GovernanceError("Approval refused") from None

    async def execute(self, operation_id, arguments):
        self._healthy()
        request_id = secrets.token_hex(16)
        self._emit("execution_requested", request_id=request_id)
        pending = self._pending.get(operation_id)
        if not pending:
            self._emit("denied", status="DENIED", reason="policy_or_authority", request_id=request_id)
            raise GovernanceError("Operation not in gateway session; cannot resume old approval")
        fields = self._fields(pending)
        if operation_id in self._active:
            self._emit("denied", status="DENIED", reason="policy_or_authority", **fields)
            raise GovernanceError("Execution already in progress")
        try:
            payload = canonical(arguments)  # Snapshot before any await.
        except GovernanceError:
            self.record_refusal()
            raise
        if self._command(pending["task_id"], pending["tool_id"], payload) != pending["command_digest"]:
            self._emit("denied", status="DENIED", reason="command_mismatch", **fields)
            raise GovernanceError("Command differs from reviewed 5W1H")
        token = self._executing.set(fields)
        try:
            self._active.add(operation_id)
            with self.tracer.start_as_current_span(
                "flight.execute",
                attributes={"flight.execution_id": operation_id},
                record_exception=False,
                set_status_on_exception=False,
            ):
                report = await super().execute(operation_id, json.loads(payload))
                self._healthy()  # Core conservatively catches handler failures; do not hide audit failure.
                result_fields = dict(fields)
                if report.verified:
                    result_fields["payload_digest"] = self.ledger.digest(canonical(report.output))
                self._emit("result", status=report.status, **result_fields)
                del self._pending[operation_id]
                if report.status in {"RESULT_UNKNOWN", "UNVERIFIED"}:
                    self.stop(pending["task_id"], self.owner_authority)
                return report
        except asyncio.CancelledError:
            self._emit("result", status="RESULT_UNKNOWN", **fields)
            self.stop(pending["task_id"], self.owner_authority)
            raise
        except GovernanceError:
            # A record failure may occur after effects: never declare success or retry automatically.
            if not self._audit_failed:
                self._emit("denied", status="DENIED", reason="policy_or_authority", **fields)
            raise
        finally:
            self._active.discard(operation_id)
            self._executing.reset(token)

    def stop(self, task_id, authority):
        self._owner(authority)
        # Stops must work even when recorder is unreachable. Core latches descendants before persistence.
        self._blocked.add(task_id)
        try:
            super().stop(task_id, authority)
        finally:
            self._emit("stop_requested", task_id=task_id)
        self._emit("stopped", task_id=task_id, status="STOPPED")

    @_serialized
    def cancel_operation(self, operation_id, authority):
        self._owner(authority)
        super().cancel_operation(operation_id, authority)
        pending = self._pending.pop(operation_id, None)
        self._emit("cancelled", status="CANCELLED", **(self._fields(pending) if pending else {}))

    @_serialized
    def handoff(self, source_id, destination_task, data, authority):
        """Host grants data access only. Target still needs its own proposal and approval."""
        self._owner(authority)
        self._healthy()
        self.check_task(destination_task)
        rows = self.recorder.read()
        source = next(
            (
                r["payload"]
                for r in reversed(rows)
                if r["payload"].get("execution_id") == source_id and r["payload"]["event"] == "result"
            ),
            None,
        )
        digest = self.ledger.digest(canonical(data))
        if not source or source.get("status") != "COMPLETED" or source.get("payload_digest") != digest:
            self._emit("denied", status="DENIED", reason="policy_or_authority")
            raise GovernanceError("Only exact verified output can be handed off")
        self._emit(
            "handoff",
            source_id=source_id,
            destination_id=destination_task,
            payload_digest=digest,
            status="OBSERVED",
        )
        return json.loads(canonical(data))  # Copy only, never transfer authority/approval/context.

    @_serialized
    def recover_interrupted(self, authority):
        self._owner(authority)
        self._healthy()
        if self._active:
            raise GovernanceError("Old executor still active")
        # Cross-process liveness still requires the operator to stop the old host first.
        rows = self.recorder.read()
        starts = {r["payload"]["execution_id"] for r in rows if r["payload"]["event"] == "execution_started"}
        finished = {
            r["payload"].get("execution_id") for r in rows if r["payload"]["event"] in {"result", "recovery"}
        }
        count = super().recover_interrupted(authority)
        for operation_id in starts - finished:
            # The core may have completed before the independent result acknowledgement failed.
            # Preserve its earlier audit history but hold this operation for external evidence reconciliation.
            with self.ledger.transaction() as db:
                db.execute(
                    "UPDATE operations SET status='RESULT_UNKNOWN',approval_until=NULL WHERE id=?",
                    (operation_id,),
                )
                self.ledger.event(db, "independent_result_missing", operation=operation_id)
            self._emit(
                "recovery", execution_id=operation_id, status="RESULT_UNKNOWN", reason="unknown_after_restart"
            )
        return count

    @_serialized
    def reconcile(self, operation_id, observed_status, authority):
        self._owner(authority)
        self._healthy()
        if observed_status not in {"COMPLETED", "FAILED", "NOT_STARTED", "RESULT_UNKNOWN"}:
            raise GovernanceError("Invalid reconciliation status")
        if self.status(operation_id) != "RESULT_UNKNOWN":
            raise GovernanceError("Only unknown results may be reconciled")
        # Human-observed evidence; distinguish it from automatic verified execution results.
        self._emit("reconciliation", execution_id=operation_id, status=observed_status)
        # Do not restore budget, state, approval or retry capability.
