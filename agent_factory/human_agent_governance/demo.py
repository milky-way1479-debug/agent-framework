"""Offline executable walkthrough; owner approval simulation is explicitly opt-in."""

import argparse
import asyncio
import json
import secrets
import tempfile
from pathlib import Path

from .framework import build_research_agent
from .policy import Policy
from .runtime import GovernanceRuntime


async def uppercase_mock(arguments, context):
    if context.stopped():
        raise RuntimeError("Stopped")
    return arguments["text"].upper()


def verify_uppercase(arguments, output):
    return output == arguments["text"].upper()


async def demo(repository: Path, simulate_owner_approval: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="human-agent-research-") as directory:
        runtime = GovernanceRuntime(
            Policy(repository), Path(directory) / "ledger.sqlite3", secrets.token_bytes(32)
        )
        owner = runtime.owner_authority
        runtime.register_mock("uppercase_mock", uppercase_mock, verify_uppercase, owner)
        task = runtime.create_task(["uppercase_mock"], owner)
        research = build_research_agent(runtime, task, [("uppercase_mock", {"text": "human x agent"})])
        await research.agent.run("Prepare a mock proposal; no external action.")
        proposal = research.proposals[0]
        print("PROPOSAL:", proposal.tool, proposal.arguments_json)
        print("Effect:", proposal.effect)
        print("Norm revision:", proposal.norm_revision)
        print("Policy revision:", proposal.policy_revision)
        print("Purpose:", proposal.purpose)
        print("Cost units:", proposal.cost_units, "; task expiry:", proposal.task_expires_at)
        approved = simulate_owner_approval or input("Approve this local mock only? Type YES: ") == "YES"
        runtime.decide(proposal.operation_id, approved, owner)
        if approved:
            report = await runtime.execute(proposal.operation_id, json.loads(proposal.arguments_json))
            print("REPORT:", report.status, "verified=", report.verified, "output=", report.output)
        else:
            print("REPORT: REJECTED; no execution")
        runtime.stop(task, owner)
        print("STOP: task and pending children blocked; database removed after this mock demo")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--simulate-owner-approval",
        action="store_true",
        help="Explicitly simulate approval for the offline mock demo only",
    )
    args = parser.parse_args()
    asyncio.run(demo(args.repository, args.simulate_owner_approval))


if __name__ == "__main__":
    main()
