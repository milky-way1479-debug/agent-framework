"""Offline Microsoft Agent adapter with model-supplied, system-checked 5W1H."""

from __future__ import annotations

import json

from agent_framework import Agent, AgentMiddleware, MiddlewareFailure, tool

from ..framework import OfflineProposalClient
from ..policy import GovernanceError, canonical
from .gateway import Notice


class _Guard(AgentMiddleware):
    def __init__(self, gateway, task):
        self.gateway, self.task = gateway, task

    async def process(self, context, call_next):
        try:
            self.gateway.check_task(self.task)
        except GovernanceError as exc:
            raise MiddlewareFailure("Flight gateway held") from exc
        if context.stream:
            raise MiddlewareFailure("Offline Flight adapter does not support streaming")
        await call_next()


def build_flight_agent(gateway, task, requests):
    """Reuse the existing guarded SDK adapter, with required AI 5W1H claims inside proposal JSON.

    requests use (tool_name, {"arguments": {...}, "notice": {...}}).
    Original adapter supplies exact function identity/client guards and bounded offline client.
    """
    from ..framework import _ChatGuard, _FunctionGuard

    gateway.check_task(task)
    if len(requests) > gateway.policy.settings["max_operations"]:
        raise GovernanceError("Batch too large")
    client = OfflineProposalClient(requests)
    proposals = []

    @tool(approval_mode="never_require")
    def propose_action(name: str, arguments_json: str) -> str:
        """Submit mock operation arguments and a 5W1H notice. This tool cannot execute or approve."""
        if len(arguments_json.encode()) > 12000:
            gateway.record_refusal()
            raise GovernanceError("Proposal too large")
        try:
            data = json.loads(arguments_json)
            if set(data) != {"arguments", "notice"}:
                gateway.record_refusal()
                raise GovernanceError("Arguments and 5W1H required")
            notice = Notice(**data["notice"])
            proposal = gateway.propose(task, name, data["arguments"], notice)
        except (TypeError, ValueError, KeyError) as exc:
            gateway.record_refusal()
            raise GovernanceError("Invalid 5W1H") from exc
        proposals.append(proposal)
        return canonical({"operation_id": proposal.operation_id, "executed": False})

    agent = Agent(
        client=client,
        name="FlightRecorderResearchAgent",
        instructions=gateway.policy.instructions(),
        tools=[propose_action],
        middleware=[
            _Guard(gateway, task),
            _ChatGuard(gateway, task, client),
            _FunctionGuard(gateway, task, propose_action),
        ],
    )
    return agent, proposals
