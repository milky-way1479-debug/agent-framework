# Enforcement boundary and limits

## Supported boundary

This release is an offline research implementation, not a claim that all 34 norms are fully implemented.
The supported route is `build_research_agent -> propose_action -> owner decision -> GovernanceRuntime.execute`.
The model receives both pinned draft documents as instructions. The runtime additionally enforces mechanically
checkable conditions. An LLM's interpretation, a framework approval message, a PDF, a Tool result, or a Skill
cannot enact norms, create owner authority, register an executor, or authorize execution.

The trusted host constructs the runtime, owns its capability, chooses a permitted task scope, registers reviewed
local mock handlers and separate verification functions, and holds the audit key outside model context.
The current CLI's owner is the person controlling the local terminal. It is not a remote identity service.
Network providers, service-managed conversations, built-in provider Tools, shell/code execution, MCP,
remote delegates, dynamically loaded Skills, and arbitrary Python supplied by the model are not supported.
The adapter rejects other model clients, streaming, and replacement functions; it raises Microsoft's
`MiddlewareFailure` so policy failures abort the loop rather than becoming recoverable Tool-error messages.

## What the controls mean

- A SQLite transaction consumes approval and reserves root budget before callback start. Concurrent attempts
  cannot both start. The committed start is the execution boundary, not an exactly-once guarantee in a remote system.
- The fingerprint uses keyed argument hashes. Rejected, cancelled, completed, unknown, and existing proposals cannot
  be silently resubmitted under a new task or ID with identical name/arguments. Semantic equivalence of different
  wording is not established. Host-led reconsideration and external idempotency reconciliation are not implemented.
- Stop commits prevent new starts and invalidate descendants' pending approvals. If start committed first, a
  callback is already running. `ExecutionContext.stopped()` supports cooperative cancellation; Python cannot kill
  arbitrary running threads or undo external effects. On storage failure, local stop is latched immediately and
  record failure is reported to the caller. No claim is made about remote stop propagation during outages.
- Handler error, cancellation, timeout, or interrupted execution does not prove absence of effects. Automatic
  retry is unavailable. `recover_interrupted` is a host-only reconciliation method that marks RUNNING as unknown;
  the host must first ensure no old executor is still active. It never restores approval or resumes work.
- Verification is a separately registered host function. Only a literal `True` yields COMPLETED. Output must
  be finite JSON to be recorded as verified. An exception or false check cannot be turned into success.
- Raw arguments, results, exception strings, credentials, and norm source contents are not written to the ledger.
  Keyed digests, opaque task/operation IDs, timestamps, status, scope, and minimal audit events are retained.

## The runtime is not an OS sandbox

Middleware and the Python authority object are not isolation against arbitrary code running in the host process.
Someone who can access the host key, alter Python, call ungoverned SDKs, or register a malicious callback can bypass
this boundary. A callback labelled `mock` is trusted reviewed host code, not automatically proven safe by its label.
Production needs separate identities/processes, least-privilege credentials, filesystem and network enforcement,
and exclusive access to approval/execution services. All alternate execution routes must be identified and blocked.

The audit chain detects modified rows and mismatched state under a host-held key. It is not independent append-only
storage. An attacker restoring a whole old database plus matching old audit chain can escape local detection.
The database must never be rolled back as a way of restoring code. An external monotonic anchor / audit store,
retention and deletion policies, backups and recovery verification are required before production.
Physical deletion, denial of service, compromise of the host and key, and third-party real-world effects remain outside
the local mock tests. Quarantine inventory is not a malware scanner: it cannot approve licenses, dependencies,
install hooks, code behavior, changing remote sources, or prompts. No quarantined Skill is imported or executed.

## Drafts and activation

The repository snapshots retain CONST-009..011 as proposals and constitutional questions A..E as unresolved.
No formal enactment, interpretation resolution, owner identity policy, production activation, or additional
permissions are inferred from the development request. Production mode is rejected by code, not merely a warning.
The traceability matrix identifies implemented research controls and every remaining production condition.
