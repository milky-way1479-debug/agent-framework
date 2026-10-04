# Validation record — 2026-10-04

## Scope and result

Local validation on Python 3.12.14 with the fork's editable `agent-framework-core==1.19.0` succeeded.
49 pytest cases passed. Ruff check and formatting passed. The actual Microsoft Agent tool-calling loop was
used with an offline scripted client; no paid model API or real external operation was used.
The mock demo completed Proposal -> explicit simulated owner approval -> Execute -> Verify/Report -> Stop.
The simulation was explicitly requested by the test command; interactive demo requires terminal input `YES`.

## Checked risks

- Fabricated model approval and forged owner capabilities cannot start execution.
- Changed arguments, changed norm/configuration files, expired approval and expired parent tasks are rejected.
- Two concurrent starts consume one approval once; identical requests cannot replay via a new ID/task/child.
- Child scopes cannot expand to another globally available Tool; root proposal/task/cost bounds are shared.
- Pending cancellation and ancestor stop prevent starts; cooperative running handlers receive stop signals.
- Errors, timeouts, crash recovery and failed effect checks are not reported as verified success.
- Callback mutation cannot alter the original approval/verification snapshot.
- Ledger state/audit alteration, wrong keys and unavailable storage prevent new execution.
- Raw inputs, outputs and private exception details are not stored in the ledger.
- Unknown Tools, replacement functions, another client and streaming cannot use the governed adapter.
- Research mode rejects network, shell, external delegation and production activation.
- Malicious Skill instructions and setup.py are inventoried without execution; symlink/size boundaries hold.

## Commands

From repository root, using an isolated environment with the extension and fork SDK installed:

```sh
python -m pytest agent_factory/tests -q
python -m ruff check agent_factory
python -m ruff format --check agent_factory
python -m human_agent_governance.demo --repository . --simulate-owner-approval
git diff --check
```

## Limits

These are local mock and integration results, not tests of Google, email, MCP, remote Agents, .NET,
real provider/hosted Tools, operating-system isolation, or production approval UI/authentication.
The new GitHub workflow is configured to repeat these checks; local results do not imply a remote CI run succeeded.
Upstream core tests were not rerun because no upstream core or provider code was changed.
Pending production work is explicit in TRACEABILITY.md, BOUNDARIES.md and ACTIVATION_CHECKLIST.md.

Validation refusals surface to the trusted host; the current ledger records accepted proposals, owner decisions,
starts, stops and reports. Persisting every malformed/rejected intake attempt in an independently protected
audit store remains production work. Restoring a whole older ledger is not detected without an external anchor.
