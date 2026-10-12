"""Offline human console and independent recorder process; no simulated automatic approval."""

import argparse
import asyncio
import secrets
import tempfile
from pathlib import Path

from ..policy import GovernanceError, Policy
from .client import PipeRecorderClient
from .dashboard import MonitoringDashboard
from .gateway import ExecutionGateway


async def demo(repository):
    with tempfile.TemporaryDirectory(prefix="flight-demo-") as temporary:
        root = Path(temporary)
        token = secrets.token_hex(32)
        (root / "gateway.token").write_text(token)
        (root / "gateway.token").chmod(0o600)
        recorder = await asyncio.to_thread(
            PipeRecorderClient.start,
            root / "audit",
            root / "anchor/checkpoint",
            root / "gateway.token",
            provision=True,
        )
        try:
            gateway = ExecutionGateway(
                Policy(repository), root / "ledger.sqlite3", secrets.token_bytes(32), recorder
            )

            async def uppercase(arguments, context):
                if context.stopped():
                    raise GovernanceError("Stopped")
                return arguments["text"].upper()

            gateway.register_mock(
                "uppercase_mock", uppercase, lambda a, r: r == a["text"].upper(), gateway.owner_authority
            )
            task = gateway.create_task(["uppercase_mock"], gateway.owner_authority)
            gateway.propose(task, "uppercase_mock", {"text": "dummy school notice"})
            print("This demo is same-UID development. Separate production identities are NOT activated.")
            print("Temporary dummy records are discarded when this demo ends.")
            print("Task for stop:", task)
            await MonitoringDashboard(gateway, gateway.owner_authority).run()
        finally:
            await asyncio.to_thread(recorder.close)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(demo(args.repository))


if __name__ == "__main__":
    main()
