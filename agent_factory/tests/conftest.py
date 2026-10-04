import shutil
from pathlib import Path

import pytest

from human_agent_governance import GovernanceRuntime, Policy


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    shutil.copytree(Path(__file__).resolve().parents[2] / "governance", root / "governance")
    return root


@pytest.fixture
def runtime(repository, tmp_path):
    return GovernanceRuntime(Policy(repository), tmp_path / "state/ledger.sqlite3", b"test-only-key-" * 3)


@pytest.fixture
def prepared(runtime):
    calls = []

    async def handler(arguments, context):
        calls.append(arguments)
        return arguments["text"].upper()

    runtime.register_mock(
        "uppercase_mock", handler, lambda a, r: r == a["text"].upper(), runtime.owner_authority
    )
    task = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    return runtime, task, calls
