import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from human_agent_governance import GovernanceError, GovernanceRuntime, Policy
from human_agent_governance.ledger import Ledger


def proposed(prepared, text="hello"):
    runtime, task, _calls = prepared
    return runtime.propose(task, "uppercase_mock", {"text": text})


def approved(prepared, text="hello"):
    proposal = proposed(prepared, text)
    prepared[0].decide(proposal.operation_id, True, prepared[0].owner_authority)
    return proposal


def test_full_workflow_requires_owner_and_verifies_effect(prepared):
    runtime, _, calls = prepared
    p = proposed(prepared)
    with pytest.raises(GovernanceError):
        asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    assert calls == []
    runtime.decide(p.operation_id, True, runtime.owner_authority)
    report = asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    assert (report.status, report.verified, report.output) == ("COMPLETED", True, "HELLO")


@pytest.mark.parametrize("fake", [None, "approved", {"approved": True}, object()])
def test_model_text_and_forged_capabilities_cannot_approve(prepared, fake):
    p = proposed(prepared)
    with pytest.raises(GovernanceError):
        prepared[0].decide(p.operation_id, True, fake)
    assert prepared[0].status(p.operation_id) == "PROPOSED"


def test_cannot_change_approved_arguments(prepared):
    p = approved(prepared)
    with pytest.raises(GovernanceError):
        asyncio.run(prepared[0].execute(p.operation_id, {"text": "changed"}))
    assert not prepared[2]


def test_expired_approval_blocks_start(prepared):
    runtime = prepared[0]
    now = runtime.clock()
    runtime.clock = lambda: now
    p = approved(prepared)
    runtime.clock = lambda: now + 61
    with pytest.raises(GovernanceError):
        asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    assert not prepared[2]


def test_used_approval_and_new_task_cannot_replay(prepared):
    runtime = prepared[0]
    p = approved(prepared)
    asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    with pytest.raises(GovernanceError):
        asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    task2 = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    with pytest.raises(GovernanceError):
        runtime.propose(task2, "uppercase_mock", {"text": "hello"})
    assert len(prepared[2]) == 1


def test_rejection_cannot_be_evaded_by_new_id_or_child(prepared):
    runtime, task, _ = prepared
    p = proposed(prepared)
    runtime.decide(p.operation_id, False, runtime.owner_authority)
    child = runtime.create_task(["uppercase_mock"], runtime.owner_authority, parent=task)
    with pytest.raises(GovernanceError):
        runtime.propose(child, "uppercase_mock", {"text": "hello"})


def test_stop_cancels_pending_children_and_blocks_new_delegation(prepared):
    runtime, task, calls = prepared
    child = runtime.create_task(["uppercase_mock"], runtime.owner_authority, parent=task)
    p = runtime.propose(child, "uppercase_mock", {"text": "child"})
    runtime.decide(p.operation_id, True, runtime.owner_authority)
    runtime.stop(task, runtime.owner_authority)
    assert runtime.status(p.operation_id) == "CANCELLED"
    with pytest.raises(GovernanceError):
        asyncio.run(runtime.execute(p.operation_id, {"text": "child"}))
    with pytest.raises(GovernanceError):
        runtime.create_task(["uppercase_mock"], runtime.owner_authority, parent=task)
    assert calls == []


def test_delegation_cannot_expand_scope(prepared):
    runtime, task, _ = prepared
    with pytest.raises(GovernanceError):
        runtime.create_task(["send_email"], runtime.owner_authority, parent=task)


def test_shared_budget_does_not_multiply_for_children(prepared):
    runtime, task, _ = prepared
    children = [
        runtime.create_task(["uppercase_mock"], runtime.owner_authority, parent=task) for _ in range(2)
    ]
    for i in range(8):
        p = runtime.propose(children[i % 2], "uppercase_mock", {"text": str(i)})
        runtime.decide(p.operation_id, True, runtime.owner_authority)
        asyncio.run(runtime.execute(p.operation_id, {"text": str(i)}))
    with pytest.raises(GovernanceError):
        runtime.propose(task, "uppercase_mock", {"text": "ninth"})


def test_concurrent_start_consumes_approval_only_once(prepared):
    p = approved(prepared)

    def start():
        try:
            return asyncio.run(prepared[0].execute(p.operation_id, {"text": "hello"})).status
        except GovernanceError:
            return "DENIED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: start(), range(2)))
    assert sorted(results) == ["COMPLETED", "DENIED"]
    assert len(prepared[2]) == 1


@pytest.mark.parametrize(
    "path", ["sources/CONSTITUTION.md", "sources/OPERATING_RULES.md", "research-policy.json"]
)
def test_norm_or_config_change_invalidates_execution(prepared, repository, path):
    p = approved(prepared)
    with (repository / "governance" / path).open("a") as stream:
        stream.write("\nchanged")
    with pytest.raises(GovernanceError):
        asyncio.run(prepared[0].execute(p.operation_id, {"text": "hello"}))
    assert not prepared[2]


def test_draft_cannot_enable_production(repository):
    path = repository / "governance/research-policy.json"
    policy = json.loads(path.read_text())
    policy["mode"] = "production"
    path.write_text(json.dumps(policy))
    with pytest.raises(GovernanceError):
        Policy(repository)


def test_failure_is_unknown_and_no_automatic_retry(runtime):
    calls = []

    async def fails(arguments, context):
        calls.append(1)
        raise ConnectionError("sensitive error details")

    runtime.register_mock("uppercase_mock", fails, lambda a, r: True, runtime.owner_authority)
    task = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    p = runtime.propose(task, "uppercase_mock", {"text": "ambiguous"})
    runtime.decide(p.operation_id, True, runtime.owner_authority)
    report = asyncio.run(runtime.execute(p.operation_id, {"text": "ambiguous"}))
    assert report.status == "RESULT_UNKNOWN" and report.output is None
    with pytest.raises(GovernanceError):
        asyncio.run(runtime.execute(p.operation_id, {"text": "ambiguous"}))
    assert len(calls) == 1


def test_successful_handler_is_not_completed_without_verification(runtime):
    async def wrong(arguments, context):
        return "incorrect"

    runtime.register_mock("uppercase_mock", wrong, lambda a, r: False, runtime.owner_authority)
    task = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    p = runtime.propose(task, "uppercase_mock", {"text": "hello"})
    runtime.decide(p.operation_id, True, runtime.owner_authority)
    report = asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    assert report.status == "UNVERIFIED" and not report.verified and report.output is None


def test_stop_signal_reaches_running_callback(runtime):
    async def scenario():
        started = asyncio.Event()

        async def cooperative(arguments, context):
            started.set()
            while not context.stopped():
                await asyncio.sleep(0)
            raise RuntimeError("Stopped before mock effect")

        runtime.register_mock("uppercase_mock", cooperative, lambda a, r: True, runtime.owner_authority)
        task = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
        p = runtime.propose(task, "uppercase_mock", {"text": "running"})
        runtime.decide(p.operation_id, True, runtime.owner_authority)
        work = asyncio.create_task(runtime.execute(p.operation_id, {"text": "running"}))
        await started.wait()
        runtime.stop(task, runtime.owner_authority)
        report = await work
        assert report.status == "RESULT_UNKNOWN"

    asyncio.run(scenario())


def test_ledger_tamper_blocks_execution(prepared):
    p = approved(prepared)
    with sqlite3.connect(prepared[0].ledger.path) as db:
        db.execute("UPDATE operations SET approval_until=9999999999")
    with pytest.raises(GovernanceError):
        asyncio.run(prepared[0].execute(p.operation_id, {"text": "hello"}))
    assert not prepared[2]


def test_audit_tamper_and_wrong_key_are_detected(prepared):
    runtime = prepared[0]
    proposed(prepared)
    with pytest.raises(GovernanceError):
        Ledger(runtime.ledger.path, b"wrong-test-key-" * 3)
    with sqlite3.connect(runtime.ledger.path) as db:
        db.execute("UPDATE audit SET payload='{}' WHERE seq=1")
    with pytest.raises(GovernanceError):
        runtime.check_task(prepared[1])


def test_logs_do_not_store_raw_arguments_results_or_errors(prepared):
    secret = "private-demo-input-0123456789"
    p = approved(prepared, secret)
    asyncio.run(prepared[0].execute(p.operation_id, {"text": secret}))
    assert secret.encode() not in prepared[0].ledger.path.read_bytes()
    assert secret.upper().encode() not in prepared[0].ledger.path.read_bytes()


@pytest.mark.parametrize(
    "arguments", [{"text": "ok", "destination": "https://example.com"}, {"text": 1}, {"text": "x" * 2049}, {}]
)
def test_undeclared_or_overlarge_arguments_rejected(prepared, arguments):
    with pytest.raises(GovernanceError):
        prepared[0].propose(prepared[1], "uppercase_mock", arguments)


def test_restart_preserves_consumed_approval_and_stop(prepared):
    runtime, task, _ = prepared
    p = approved(prepared)
    asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    runtime.stop(task, runtime.owner_authority)
    restarted = GovernanceRuntime(runtime.policy, runtime.ledger.path, runtime.ledger.key)
    assert restarted.status(p.operation_id) == "COMPLETED"
    with pytest.raises(GovernanceError):
        restarted.check_task(task)


def test_storage_failure_blocks_start_and_local_stop_survives(prepared, monkeypatch):
    runtime, task, calls = prepared
    p = approved(prepared)

    def broken():
        raise GovernanceError("Unavailable storage")

    monkeypatch.setattr(runtime.ledger, "connect", broken)
    with pytest.raises(GovernanceError):
        asyncio.run(runtime.execute(p.operation_id, {"text": "hello"}))
    with pytest.raises(GovernanceError):
        runtime.stop(task, runtime.owner_authority)
    assert task in runtime._blocked and not calls


def test_cancel_unused_approval_blocks_start(prepared):
    p = approved(prepared)
    prepared[0].cancel_operation(p.operation_id, prepared[0].owner_authority)
    with pytest.raises(GovernanceError):
        asyncio.run(prepared[0].execute(p.operation_id, {"text": "hello"}))
    assert prepared[0].status(p.operation_id) == "CANCELLED" and not prepared[2]


def test_recovery_holds_interrupted_operations_as_unknown(prepared):
    runtime = prepared[0]
    p = approved(prepared)
    with runtime.ledger.transaction() as db:
        db.execute("UPDATE operations SET status='RUNNING',approval_until=NULL WHERE id=?", (p.operation_id,))
        runtime.ledger.event(db, "test_crash_after_start")
    restarted = GovernanceRuntime(runtime.policy, runtime.ledger.path, runtime.ledger.key)
    assert restarted.recover_interrupted(restarted.owner_authority) == 1
    assert restarted.status(p.operation_id) == "RESULT_UNKNOWN"
    with pytest.raises(GovernanceError):
        asyncio.run(restarted.execute(p.operation_id, {"text": "hello"}))


def test_timeout_does_not_claim_no_effect(runtime, repository):
    settings_path = repository / "governance/research-policy.json"
    settings = json.loads(settings_path.read_text())
    settings["tools"][0]["timeout_seconds"] = 0.01
    settings_path.write_text(json.dumps(settings))
    runtime.policy = Policy(repository)

    async def slow(arguments, context):
        await asyncio.sleep(1)

    runtime.register_mock("uppercase_mock", slow, lambda a, r: True, runtime.owner_authority)
    task = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    p = runtime.propose(task, "uppercase_mock", {"text": "slow"})
    runtime.decide(p.operation_id, True, runtime.owner_authority)
    report = asyncio.run(runtime.execute(p.operation_id, {"text": "slow"}))
    assert report.status == "RESULT_UNKNOWN" and not report.verified


def test_task_expiration_is_inherited(prepared):
    runtime, task, _ = prepared
    child = runtime.create_task(["uppercase_mock"], runtime.owner_authority, parent=task, lifetime=9999)
    now = runtime.clock()
    runtime.clock = lambda: now + 301
    with pytest.raises(GovernanceError):
        runtime.check_task(child)


@pytest.mark.parametrize("capability", ["network", "shell", "external_delegation"])
def test_research_cannot_enable_external_capabilities(repository, capability):
    path = repository / "governance/research-policy.json"
    settings = json.loads(path.read_text())
    settings[capability] = True
    path.write_text(json.dumps(settings))
    with pytest.raises(GovernanceError):
        Policy(repository)


def test_shared_cost_reservation_blocks_children_before_count_limit(runtime, repository):
    path = repository / "governance/research-policy.json"
    settings = json.loads(path.read_text())
    settings["tools"][0]["cost_units"] = 3
    path.write_text(json.dumps(settings))
    runtime.policy = Policy(repository)
    calls = []

    async def callback(arguments, context):
        calls.append(1)
        return arguments["text"]

    runtime.register_mock("uppercase_mock", callback, lambda a, r: True, runtime.owner_authority)
    root = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    children = [
        runtime.create_task(["uppercase_mock"], runtime.owner_authority, parent=root) for _ in range(3)
    ]
    for i, child in enumerate(children):
        p = runtime.propose(child, "uppercase_mock", {"text": str(i)})
        runtime.decide(p.operation_id, True, runtime.owner_authority)
        if i < 2:
            asyncio.run(runtime.execute(p.operation_id, {"text": str(i)}))
        else:
            with pytest.raises(GovernanceError):
                asyncio.run(runtime.execute(p.operation_id, {"text": str(i)}))
    assert len(calls) == 2


def test_allowed_global_tool_cannot_expand_parent_scope(runtime, repository):
    path = repository / "governance/research-policy.json"
    settings = json.loads(path.read_text())
    second = dict(settings["tools"][0], name="second_mock")
    settings["tools"].append(second)
    path.write_text(json.dumps(settings))
    runtime.policy = Policy(repository)
    parent = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    with pytest.raises(GovernanceError):
        runtime.create_task(["second_mock"], runtime.owner_authority, parent=parent)


def test_callback_mutation_cannot_change_verification_snapshot(runtime):
    async def changes_input(arguments, context):
        arguments["text"] = "changed"
        return "CHANGED"

    runtime.register_mock(
        "uppercase_mock", changes_input, lambda a, r: r == a["text"].upper(), runtime.owner_authority
    )
    task = runtime.create_task(["uppercase_mock"], runtime.owner_authority)
    p = runtime.propose(task, "uppercase_mock", {"text": "original"})
    runtime.decide(p.operation_id, True, runtime.owner_authority)
    report = asyncio.run(runtime.execute(p.operation_id, {"text": "original"}))
    assert report.status == "UNVERIFIED"
