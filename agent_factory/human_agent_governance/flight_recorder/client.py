"""Gateway-only recorder transport. Never expose it or its token to a model."""

from __future__ import annotations

import json
import secrets
import socket
from pathlib import Path

from ..policy import GovernanceError, canonical

MAX_FRAME = 16384


class RecorderClient:
    def __init__(self, socket_path: Path, token: str):
        self.socket_path, self._token = Path(socket_path), token

    def _call(self, action: str, **fields):
        transport_id = secrets.token_hex(16)
        data = (
            canonical({"token": self._token, "action": action, "transport_id": transport_id, **fields}) + "\n"
        ).encode()
        if len(data) > MAX_FRAME:
            raise GovernanceError("Recorder request too large")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(10)
                connection.connect(str(self.socket_path))
                connection.sendall(data)
                with connection.makefile("rb") as stream:
                    # MVP read bound; archive/rotation with anchored segments is not yet implemented.
                    response = json.loads(stream.readline(8 * 1024 * 1024 + 1))
            if response.get("ok") is not True or response.get("transport_id") != transport_id:
                raise GovernanceError("Recorder refused request; hold operation")
            return response["result"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise GovernanceError("Recorder unavailable; hold operation") from exc

    def append(self, event: dict):
        return self._call("append", event=event)

    def read(self) -> list[dict]:
        return self._call("read")


class PipeRecorderClient:
    """Dedicated child recorder over exclusive inherited pipes; no network or filesystem API for models."""

    def __init__(self, process, token):
        import threading

        self.process, self._token = process, token
        self.lock = threading.Lock()
        self._broken = False

    @classmethod
    def start(cls, directory, checkpoint, token_file, *, provision=False):
        import os
        import subprocess
        import sys

        args = [
            sys.executable,
            "-m",
            "human_agent_governance.flight_recorder.service",
            "--stdio",
            "--directory",
            str(directory),
            "--checkpoint",
            str(checkpoint),
            "--token-file",
            str(token_file),
        ]
        if provision:
            args.append("--provision")
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        )
        client = cls(process, token_file.read_text().strip())
        try:
            client.read()  # Startup/integrity acknowledgement, not just successful process creation.
        except BaseException:
            client.close()
            raise
        return client

    def _call(self, action, **fields):
        import os
        import select
        import time

        transport_id = secrets.token_hex(16)
        data = (
            canonical({"token": self._token, "action": action, "transport_id": transport_id, **fields}) + "\n"
        ).encode()
        if len(data) > MAX_FRAME:
            raise GovernanceError("Recorder request too large")
        with self.lock:
            if self._broken:
                raise GovernanceError("Recorder connection lost; do not reuse stale acknowledgements")
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
                chunks = bytearray()
                deadline = time.monotonic() + 10
                while not chunks.endswith(b"\n"):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                        raise OSError("Recorder timeout")
                    part = os.read(self.process.stdout.fileno(), 65536)
                    if not part or len(chunks) + len(part) > 8 * 1024 * 1024:
                        raise OSError("Recorder disconnected or response too large")
                    chunks.extend(part)
                response = json.loads(chunks)
                if response.get("ok") is not True or response.get("transport_id") != transport_id:
                    raise OSError("Recorder refused request or correlation mismatch")
                return response["result"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._broken = True
                raise GovernanceError("Recorder unavailable; hold operation") from exc

    def append(self, event):
        return self._call("append", event=event)

    def read(self):
        return self._call("read")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        self.process.stdout.close()
