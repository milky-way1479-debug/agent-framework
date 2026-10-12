"""Linux UNIX-socket recorder. Only authenticated gateway peers may append/read."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import socket
import socketserver
import struct
import sys
from pathlib import Path

from ..policy import canonical
from .store import HEX, AuditStore

MAX_FRAME = 16384


class RecorderServer(socketserver.UnixStreamServer):
    def __init__(self, path: Path, store: AuditStore, token: str, gateway_uid: int):
        self.store, self.token, self.gateway_uid = store, token, gateway_uid
        super().__init__(str(path), _Handler)
        os.chmod(path, 0o660)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        try:
            _, uid, _ = struct.unpack(
                "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            request = json.loads(self.rfile.readline(MAX_FRAME + 1))
            response = process_request(
                self.server.store, self.server.token, request, authorized_peer=uid == self.server.gateway_uid
            )
        except Exception:  # noqa: BLE001 - never disclose credentials, events or exception details
            response = {"ok": False}
        self.wfile.write((canonical(response) + "\n").encode())


def process_request(store, token, request, *, authorized_peer=True):
    try:
        if (
            not authorized_peer
            or type(request) is not dict
            or not hmac.compare_digest(str(request.get("token", "")), token)
        ):
            raise ValueError("Unauthorized peer")
        transport_id = request.get("transport_id", "")
        if type(transport_id) is not str or not HEX.fullmatch(transport_id):
            raise ValueError("Missing transport correlation")
        if request.get("action") == "append" and set(request) == {"token", "action", "event", "transport_id"}:
            result = store.append(request["event"])
        elif request.get("action") == "read" and set(request) == {"token", "action", "transport_id"}:
            result = store.verify()
        else:
            raise ValueError("Unsupported command")
        return {"ok": True, "result": result, "transport_id": transport_id}
    except Exception:  # noqa: BLE001 - never expose arbitrary exception strings
        return {"ok": False}


def serve_stdio(store, token):
    while True:
        data = sys.stdin.buffer.readline(MAX_FRAME + 1)
        if not data:
            return
        if len(data) > MAX_FRAME or not data.endswith(b"\n"):
            return  # Oversized/truncated stream is closed, never parsed as another request.
        try:
            response = process_request(store, token, json.loads(data))
        except ValueError:
            response = {"ok": False}
        sys.stdout.write(canonical(response) + "\n")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--gateway-uid", type=int)
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    if bool(args.socket) == args.stdio:
        parser.error("Exactly one of --socket or --stdio is required")
    if args.socket and args.gateway_uid is None:
        parser.error("Socket mode needs an explicit gateway UID")
    os.umask(0o077)
    store = (
        AuditStore.provision(args.directory, args.checkpoint)
        if args.provision
        else AuditStore(args.directory, args.checkpoint)
    )
    token = args.token_file.read_text().strip()
    if len(token) < 64:
        parser.error("Host provisioned gateway token must be at least 64 characters")
    if args.stdio:
        try:
            serve_stdio(store, token)
        finally:
            store.close()
        return
    # Stale sockets are not blindly unlinked. The operator verifies the old service is stopped.
    with RecorderServer(args.socket, store, token, args.gateway_uid) as server:
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            args.socket.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
