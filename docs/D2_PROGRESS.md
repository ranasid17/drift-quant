# D2 implementation in progress

Issue #5; draft PR #19; branch `codex/d2-subscription-probes`; baseline
`739facb541b5d5d57f58b9bfc621701cbc4df202`.
Owner @ranasid17; implementer Codex in this chat; no delegated agents.

Implemented explicit-online CLI, frozen pinned session schedule, endpoint
planning, 80-attempt budget including retries/pages, resumable state and durable
D3 evidence, capability/feasibility/endpoint-method reports, conservative
identity and boundary analysis. Tests use synthetic provider responses and fake
monotonic time with the socket/DNS guard enabled. Implementation details and
remaining proof boundaries are in DOCTOR.md.

Native macOS arm64 / Conda Python 3.15.2: 99 offline tests passed. Hash-locked
calendar dependencies install from wheels. Live verification is underway in one
bounded invocation; reports and raw data remain in ignored local directories.
No bulk ingestion, statistical model, signal, portfolio or backtest work.


The running live invocation was started with implementation commit `4153cd4`;
its immutable state contains that implementation fingerprint. Subsequent changes
harden ledger disk failures, Ctrl-C continuation, root-wide invocation locking
and cross-invocation rate restoration without expanding the live request plan.
Those changes are verified by additional synthetic tests. No second live
invocation is started automatically; older probe continuations require their
original implementation and dependency versions.
