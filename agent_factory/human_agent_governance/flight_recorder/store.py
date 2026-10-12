"""Recorder-owned append-only API, authenticated chain and separately stored checkpoint."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path

from ..policy import GovernanceError, canonical

EVENTS = {
    "task_created",
    "request",
    "permission_allowed",
    "denied",
    "proposal",
    "decision_requested",
    "approved",
    "rejected",
    "execution_requested",
    "execution_started",
    "result",
    "stop_requested",
    "stopped",
    "handoff",
    "reconciliation",
    "recovery",
    "cancelled",
}
FIELDS = {
    "execution_id",
    "agent_id",
    "owner_id",
    "tool_id",
    "task_id",
    "approval_id",
    "request_id",
    "source_id",
    "destination_id",
    "payload_digest",
    "command_digest",
    "notice_digest",
    "norm_revision",
    "policy_revision",
    "trace_id",
    "span_id",
    "status",
    "reason",
    "timestamp",
    "event",
}
STATUSES = {
    "PENDING",
    "APPROVED",
    "REJECTED",
    "RUNNING",
    "COMPLETED",
    "UNVERIFIED",
    "RESULT_UNKNOWN",
    "CANCELLED",
    "DENIED",
    "STOPPED",
    "OBSERVED",
    "FAILED",
    "NOT_STARTED",
}
REASONS = {"policy_or_authority", "audit_unavailable", "command_mismatch", "unknown_after_restart"}
HEX = re.compile(r"^[0-9a-f]{16,64}$")
NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_event(event: dict) -> None:
    if type(event) is not dict or set(event) - FIELDS or event.get("event") not in EVENTS:
        raise GovernanceError("Audit schema rejected")
    if type(event.get("timestamp")) not in (int, float):
        raise GovernanceError("Audit timestamp required")
    canonical(event)  # Reject NaN, non-JSON and nested objects in typed fields below.
    for key, value in event.items():
        if key in {"timestamp", "event"}:
            continue
        if key == "status":
            valid = value in STATUSES if type(value) is str else False
        elif key == "reason":
            valid = value in REASONS if type(value) is str else False
        elif key == "tool_id":
            valid = type(value) is str and NAME.fullmatch(value)
        else:
            valid = type(value) is str and HEX.fullmatch(value)
        if not valid:
            raise GovernanceError("Audit field rejected")


def _private_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written == 0:
                raise OSError("Incomplete write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class AuditStore:
    """Only the recorder process gets this object or its signing key.

    A checkpoint is not a remote WORM anchor: coordinated rollback of both stores remains possible.
    Interrupted log/checkpoint commits are intentionally held, never silently repaired.
    """

    def __init__(self, directory: Path, checkpoint: Path):
        self.directory, self.checkpoint = Path(directory), Path(checkpoint)
        self.log = self.directory / "events.jsonl"
        self.key = (self.directory / "signing.key").read_bytes()
        if len(self.key) != 32:
            raise GovernanceError("Recorder key invalid")
        self.lock = threading.RLock()
        self._lock_fd = os.open(self.directory / "writer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.verify()
        except BaseException:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise

    def close(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    @classmethod
    def provision(cls, directory: Path, checkpoint: Path) -> AuditStore:
        directory, checkpoint = Path(directory), Path(checkpoint)
        # Explicit host-only provisioning. Existing or partly missing stores are never reinitialized.
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        checkpoint.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private_file(directory / "signing.key", os.urandom(32))
        _private_file(directory / "events.jsonl", b"")
        _private_file(checkpoint, canonical({"seq": 0, "signature": "0" * 64}).encode())
        _sync_directory(directory)
        _sync_directory(checkpoint.parent)
        return cls(directory, checkpoint)

    def _sign(self, row: dict) -> str:
        return hmac.new(self.key, canonical(row).encode(), hashlib.sha256).hexdigest()

    def verify(self) -> list[dict]:
        with self.lock:
            previous, rows = "0" * 64, []
            try:
                contents = self.log.read_text()
                if contents and not contents.endswith("\n"):
                    raise GovernanceError("Incomplete audit frame")
                for seq, line in enumerate(contents.splitlines(), 1):
                    row = json.loads(line)
                    signature = row.pop("signature")
                    if (
                        set(row) != {"seq", "previous", "payload"}
                        or row["seq"] != seq
                        or row["previous"] != previous
                        or not hmac.compare_digest(signature, self._sign(row))
                    ):
                        raise GovernanceError("Audit chain mismatch")
                    validate_event(row["payload"])
                    row["signature"] = signature
                    rows.append(row)
                    previous = signature
                if json.loads(self.checkpoint.read_text()) != {"seq": len(rows), "signature": previous}:
                    raise GovernanceError("Audit checkpoint mismatch; operator reconciliation required")
                return rows
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise GovernanceError("Audit cannot be verified") from exc

    def append(self, event: dict) -> dict:
        validate_event(event)
        with self.lock:
            rows = self.verify()
            row = {
                "seq": len(rows) + 1,
                "previous": rows[-1]["signature"] if rows else "0" * 64,
                "payload": event,
            }
            row["signature"] = self._sign(row)
            data = (canonical(row) + "\n").encode()
            fd = os.open(self.log, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if written == 0:
                        raise OSError("Incomplete append")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            temporary = self.checkpoint.with_suffix(".pending")
            _private_file(temporary, canonical({"seq": row["seq"], "signature": row["signature"]}).encode())
            os.replace(temporary, self.checkpoint)
            _sync_directory(self.checkpoint.parent)
            return {"seq": row["seq"], "signature": row["signature"]}
