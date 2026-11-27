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
calendar dependencies install from wheels. One bounded live invocation completed; reports and raw data remain in ignored
local directories.
No bulk ingestion, statistical model, signal, portfolio or backtest work.


The completed live invocation was started with implementation commit `4153cd4`;
its immutable state contains that implementation fingerprint. Subsequent changes
harden ledger disk failures, Ctrl-C continuation, root-wide invocation locking
and cross-invocation rate restoration without expanding the live request plan.
Those changes are verified by additional synthetic tests. No second live
invocation is started automatically; older probe continuations require their
original implementation and dependency versions.


## Live evidence review

Probe `68b05398333f4080a6982aaf35f10a8c` completed its 80 planned queries with
80 reserved HTTP attempts and no automatic continuation. Both instrument
identities are verified. All 50 successful snapshots and their JSON pointers
were re-read/hash-verified; the original source/dependency fingerprint matches
commit 4153cd4. A scan of 607 private runtime files found no runtime credential
text, including in decompressed pages. Runtime data/report paths are untracked.

The session-method candidate remains blocked: observed daily summaries disagree
with the scheduled minute proxies, and the early-close sample was inaccessible.
These are unresolved semantics/access findings, not proof of a particular plan
tier or an exact entitlement cutoff. The query queue completed, but D2 is not
accepted as a ready source for D4. No method is selected and no dataset published.

Private artifacts (relative to repo root):

- configs/reports/probes/68b05398333f4080a6982aaf35f10a8c/DATA_FEASIBILITY.md
- configs/reports/probes/68b05398333f4080a6982aaf35f10a8c/capabilities.json
- configs/reports/probes/68b05398333f4080a6982aaf35f10a8c/endpoint_contracts.json
- configs/data/probes/68b05398333f4080a6982aaf35f10a8c/state.json and calendar.json

## Acceptance disposition

1. Identity and sampled endpoint evidence: collected and sanitized. Unresolved
   boundaries and unknown denials are explicitly retained.
2. Sparse actions: empty results never create a claimed oldest entitlement date;
   page completeness is kept separate from vendor database completeness.
3. Session-method evidence: blocked pending resolution of discrepancies and the
   inaccessible early-close sample. No equivalence or auction print is invented.
4. Scope/security: no bulk acquisition, paid upgrade, provider/host switch,
   automatic legacy fallback, model, signal, portfolio or backtest. Pending
   capabilities stay blocked. Draft PR #19 and issue #5 remain in progress.

The live doctor returned exit 5 as designed for a completed queue with blocked
method acceptance. This is separate from the green offline test/CI result.
