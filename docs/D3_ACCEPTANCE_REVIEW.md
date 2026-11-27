# D3 acceptance review

Issue #4; original storage implementation merged in PR #17. Review found an
in-flight provenance gap: a process exit during pagination could lose fetched
pages still in memory. The follow-up `codex/d3-durable-pages` closes this gap
and strengthens the interruption/concurrency evidence. Acceptance applies to
the branch after review and merge, not automatically to the old main commit.

| Issue criterion | Evidence and disposition |
| --- | --- |
| Mock paginated replay; market fields survive | Existing test_storage paginated replay and JSON-pointer tests; new storage-integrated two-page replay. Pass. |
| Failures around rename/catalog cannot create false success or overwrite prior output | Existing disk-full mocks plus real child exits before/after rename and before/after catalog commit. Pre-commit orphans fail reads; a completed catalog commit remains hash-verified and capabilities blocked. Previous dataset manifest stays byte-identical and readable in every case. Pass for process exits on tested local filesystems. |
| Concurrent writers, corruption, incomplete restart, refresh isolation | Existing corruption/config/refresh tests; two simultaneous subprocess publishers produce exactly one success and one rejection. Process exit during the second request preserves page one as incomplete evidence; restart starts from request one. Journal corruption/config mismatch fails closed, and journal write failure prevents request two. Pass. |
| Input-only IDs; later audits never rewrite manifests | Existing D0 identity tests reject output/audit/path/clock fields. Existing D3 later-audit test checks manifest bytes unchanged. Pass. |

No live provider data, credentials or subscription probes are part of this
review. The current follow-up suite has 74 tests (67 existing + 7 focused tests);
each parameterized interruption test exercises multiple process-exit positions.
No claim of actual hardware power-loss, remote filesystem or Windows behavior
is made. All capabilities stay blocked until later quality checks exist.

## Boundaries that do not block D2

The original handoff left source references and table row counts caller-supplied.
Storage verifies bytes, identities and schema shapes. D4/D5/D8/D10 must verify
semantic source relationships, normalization outputs, row counts and full
reproduction. D8 owns quality acceptance. These later-phase requirements do
not require statistical work or an expanded D3 data scope, and do not prevent
bounded D2 capability probes from saving raw evidence.

D2 can start after this follow-up is reviewed and merged. Its live probe path
must use Store.acquire_partition with explicit online opt-in, bounded requests,
and the existing subscription; it must not invoke bare fetch and postpone
storage until all pages arrive. Keep issue #4 open until that merge, then mark
the tracker done and D2 ready.
