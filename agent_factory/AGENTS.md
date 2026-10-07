# Governance extension work rules

- Read ../governance/README.md and docs/BOUNDARIES.md before changing enforcement.
- Preserve the pinned Layer 1 and Layer 2 source wording. A document copy is not enactment.
- Keep Microsoft core, providers, and public APIs unchanged; use public extension points.
- Never expose owner authority, audit keys, approval decisions, or execution handlers as model tools.
- Tests and demo use local mocks only. External Skills are inventory data, never executable input.
- Run tests and Ruff using the commands in README.md. Keep secrets and runtime ledgers out of Git.
