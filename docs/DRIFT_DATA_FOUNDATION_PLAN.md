# Drift data foundation: XOM and XLE

Prepared 26 November 2026. Status: implementation-ready plan; no implementation or live entitlement verification performed. This document governs the next data-only phase and supersedes conflicting data instructions in the older prototype plan. It does not authorize or specify statistical models, signals, portfolios, execution simulation, or backtesting.

## Implementation-readiness review

Reviewed 26 November 2026 before issue creation. The scope, raw-price/action separation, complete session spine, existing-subscription constraint, and independent numerical fixtures are retained. Apply these corrections wherever the original text below is less specific:

1. **Probe provenance and dependencies:** implement D3's raw store before D2's live probes. D2 depends on D1 and D3; all successful probe market responses use the same sanitized page archive and lineage as ingestion. A sanitized failure summary can be emitted before the archive is usable. D3 remains testable with mocked responses and does not depend on live access. D0 establishes machine-readable schemas and shared enums before downstream packets extend them.
2. **Non-circular identities:** calculate `dataset_id` from a canonical build-input descriptor (source content hashes, transform/source fingerprint, schema, config, frozen calendar and endpoint contracts), excluding dataset IDs, output hashes, audit IDs, paths and wall-clock fields. Then write tables containing that ID, hash outputs, and build the manifest. The manifest has its own integrity hash excluding its hash field. Audits have independent IDs and sidecar manifests referencing the dataset; attach later audit IDs in the catalog without rewriting an immutable dataset manifest. Dataset publication requires an initial audit, whose ID is excluded from dataset identity. Replay compares logical market/quality content with acquisition IDs and source-location pointers normalized to source content hashes.
3. **Action invalidation extent:** unknown action coverage invalidates the entire uncertain interval. A known ordinary split/cash event with unresolved units invalidates its dependent return. An unsupported identity-changing action (merger, spin-off, reorganization or unverified share continuity) blocks that instrument from the effective date onward until a versioned resolution establishes continuity; do not resume valid returns merely because the next two prices exist. No future calendar dates are invented for unknown actions. This phase detects only events exposed by entitled reference/action sources or mechanical anomalies; absence of a jump is not proof that all complex actions are covered. Report that coverage limitation explicitly.
4. **Audit/report ownership:** `audit` writes `quality.json`, `issues.csv`, and `coverage.csv`; `report --audit` renders `index.html` from those saved findings. Both are offline. Optional orchestration may call both, but must preserve separate error status and never report HTML completion after only the audit succeeds. Dataset readiness is an aggregate of per-instrument/per-capability flags; `--require-ready` defaults to `aligned_pair_ready` and supports an explicit capability selection.
5. **Deterministic return segments:** an invalid return ends the old index segment. If its current close is itself valid, that close may seed a new segment at 100; otherwise wait for the next valid close. The next valid adjacent return compounds from that seed. An unresolved identity-changing action prohibits seeding until resolved. Test both a missing-close gap and an action-coverage-only gap.
6. **Honest access boundaries and acceptance:** an empty result from a sparse action endpoint cannot establish the oldest entitled date. Record unknown/interval-valued boundaries and explicit access evidence rather than forcing a session-exact answer. Complete paginated requests demonstrate vendor-query coverage, not independently verified completeness of the vendor's event database. D12 may produce a complete engineering handoff with a blocked empirical capability, but the real-data foundation is accepted only when all required capability gates pass. Report `engineering_complete` and `real_data_accepted` separately; missing live credentials or pending Docker verification cannot be described as a fully accepted release.

These are technical clarifications within the requested data scope. No implementation has begun. Current GitHub repository state was rechecked during review: main still contains README, LICENSE and .gitignore, and the issue list was empty.

## 1. Reviewed evidence and repository boundary

The target is [ranasid17/drift-quant](https://github.com/ranasid17/drift-quant/tree/bbaf2e48af0c39bfd7bd1848d8319628bc02b58f), main commit `bbaf2e48af0c39bfd7bd1848d8319628bc02b58f`. Its complete tree contains only `.gitignore`, `LICENSE`, and a seven-byte README (`# drift`); the branch listing returned main only. There is no implemented Drift data pipeline or repository sprint plan to extend.

The existing plans reviewed are local to `/Users/sidrana/Documents/ChatGPT/quant`: `README.md`, `docs/PROTOTYPE_PLAN.md`, `docs/RESEARCH_SPEC.md`, `docs/DECISIONS.md`, and `docs/IMPLEMENTATION_HANDOFF.md`. That checkout has untracked planning artifacts and no configured remote. Preserve them; do not repoint it or overwrite its Git state. Establish a separate verified Drift checkout during implementation and copy approved planning documents deliberately, recording their source hashes.

QUSA was reviewed read-only at `/Users/sidrana/Projects/qusa`, HEAD `8247d4223aa6fdbcb17ddc53e6234bdaa5d50949`. Its configuration has a local modification, which was neither read for credentials nor changed. Relevant source findings:

| Source under QUSA | Actual behavior | Drift decision |
| --- | --- | --- |
| `qusa/data/fetcher.py` | Historical `/v2/aggs/.../1/day`, latest `/v1/open-close`; both request `adjusted=true`; returns selected OHLCV fields | New adapter with explicit unadjusted requests and endpoint-specific contracts; do not import this fetcher |
| Same fetcher | One HTTP request per range; no `next_url` traversal or bounded retry; non-OK body with zero results can become an empty frame | Distinguish denial, malformed response, empty success, and incomplete pagination |
| Same fetcher | Converts epoch milliseconds to a UTC date; latest session is calendar-completed, not delivery-verified | Preserve timestamps, map in exchange timezone, and distinguish session close from provider availability |
| `qusa/data/loader.py` | Validates positive finite OHLC, ranges, nonnegative volume; merges CSV fragments with lexical precedence and last duplicate wins | Reuse validation ideas; replace mutation and lexical precedence with immutable snapshots and explicit revision selection |
| `qusa/data/sessions.py`, `tests/test_data_reliability.py` | Calendar handles DST, holidays, early closes; injectable clock; tests atomic-write failure and contention | Reuse small verified patterns with independent Drift tests and a frozen schedule |
| `qusa/storage/artifacts.py`, `locks.py` | Same-directory temporary write plus replace; bounded advisory file lock | Extend to multi-artifact staging, hash verification, manifest commit, crash recovery |
| `qusa/utils/errors.py` | Allowlisted safe error categories | Preserve safe diagnostics with structured reason codes |
| `scripts/fetch_data.py` | Direct exception interpolation; fetcher places credentials in query parameters | Never copy this logging/request pattern; transport errors can contain authenticated URLs |
| `qusa/services/pipeline_service.py`, `qusa/cli.py` | Explicit fetch path and lazy provider creation, then feature workflow | Keep explicit networking and offline reads; exclude feature/model workflow entirely |

QUSA CSVs and saved models are not authoritative Drift inputs. No action ingestion, immutable raw-page archive, or total-return construction was found in its reviewed data workflow. QUSA's tests were inspected, not executed as part of this planning review.

## 2. Scope and deliverable

Deliver a native Python CLI plus Docker packaging that obtains the subscription-accessible history of **XOM and XLE only**, retains source evidence, builds calendar-aligned raw regular-session price references and cash-inclusive returns, and emits an offline HTML/JSON/CSV quality report. Instrument identity must distinguish XOM common stock from the XLE ETF. USD only; no FX conversion, historical constituents, inactive-name universe, live streaming, or additional market-data subscription.

“Executable price” here means an unadjusted observed regular-session price reference suitable for a later consumer. It is not an actual fill, bid/ask quote, guaranteed opening-auction price, or evidence that a hypothetical order could execute at that price. Persist the exact price method so no consumer can make that inference implicitly.

Use all verified accessible common history rather than imposing a ten-year prerequisite or a minimum model window. Keep each instrument's longer accessible history in raw/normalized storage. The published pair view uses the common supported date envelope and retains every session inside it, including invalid rows. A single valid adjacent return proves the mechanics, not sample adequacy for any future research. No train/validation/test partition is selected in this phase.

Default end is the latest fully completed exchange session whose required data is available at the run's captured UTC `as_of`. Record that resolved date, never a moving `today` in a frozen manifest. Probe history back toward the provider's documented earliest records, stopping at measured subscription boundaries or verified listing inception. Do not buy, upgrade, change providers, or silently reduce scope to close-only data if required opens are unavailable.

## 3. Provider access and historical coverage

Current public documentation is evidence of API shape, not of this account's entitlement:

* [Custom bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars): `/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`; explicitly set `adjusted=false`, ascending order, and a declared limit. Limits apply to underlying aggregates. Handle pagination and validate actual coverage.
* [Daily ticker summary](https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary): `/v1/open-close/{ticker}/{date}` is a candidate open/close source, with separate extended-hours fields. Verify the precise field semantics before adopting it.
* [Dividends](https://massive.com/docs/rest/stocks/corporate-actions/dividends) now documents `/stocks/v1/dividends`; [splits](https://massive.com/docs/rest/stocks/corporate-actions/splits) documents `/stocks/v1/splits`. Older `/v3/reference/...` routes are deprecated. Probe current routes first; any legacy fallback must be named, separately tested, and frozen in the endpoint contract. Do not mix schemas silently.
* Public history allowances differ by endpoint and plan. No account tier or available start date was verified in this review. The old plan's October 2026 XLE success is historical evidence for that request only.

### Bounded feasibility protocol

`drift-data doctor --online --config ...` performs read-only probes. No network on import, `--help`, validation, normalization, audit, or reproduction. Credential source: `POLYGON_API_KEY`, otherwise a user-selected `--credentials-file` containing that key. Do not auto-discover QUSA secrets or load its application configuration. Persist only credential-present and authentication-result flags.

1. Validate XOM/XLE reference identity using the provider ticker-details route (`/v3/reference/tickers/{ticker}`, verified during implementation), active/listing information, currency and exchange. Save supported identifiers and effective alias intervals; do not invent identifier continuity from a matching symbol.
2. Test `api.polygon.io` compatibility, then an explicitly configured `api.massive.com` route if needed. Record actual endpoint/host/version. Never forward credentials through an unvalidated redirect.
3. For each ticker and each required endpoint, probe a short recent completed interval, then approximately 2-, 5-, 10-, and 20-year-old intervals as permitted by results. Include split and dividend queries for those date bounds, not just recent actions. Use one recent minute-data session to assess the possible regular-session fallback. Older intervals need small requests, not bulk downloads.
4. Bracket the oldest working boundary, then refine to a session-level boundary with bounded probes. Cap a doctor invocation at 80 HTTP attempts including retries; if exhausted, write `boundary_unresolved` and a continuation cursor. A successful old week is not proof of all intervening history. Full ingestion/audit establishes contiguous coverage later.
5. Distinguish explicit entitlement refusal from an empty success, holiday interval, pre-listing interval, rate limit, delayed latest data, malformed response and unsupported endpoint. A 403 without a specific entitlement reason remains `access_denied_unknown`, not a claimed subscription limit. An empty old interval cannot alone identify the access boundary.
6. Verify action queries cover the return interval `(previous_session, session]`, including the first required return. A valid previous-session close is needed; otherwise the first return remains null. Dates outside entitlement cannot be supplied by another credential, a public-history workaround, or QUSA's cache.
7. Save `DATA_FEASIBILITY.md` and `capabilities.json`: per-endpoint/ticker requests, successes/failures, oldest/newest observations, rolling-boundary uncertainty, identity/timing/unit evidence, docs URLs/date, sanitized request IDs, and unresolved blockers. Do not infer exact plan tier from the observed cutoff.

Default one worker and conservative five requests/minute until this account's supported rate is evidenced. Transport uses connect/read timeouts (5/30 seconds), at most five attempts for timeouts, 429 and 5xx, exponential backoff with jitter (base 1 second, cap 60 seconds), respecting `Retry-After`. If a required wait exceeds the command deadline, persist resumable state and stop; do not disregard the limit. 401/403 and non-retryable 4xx fail immediately. Successful HTTP with an error body is still failure. Record attempt counts; redact exception content.

Pagination requires HTTPS, an exact configured host allowlist, approved endpoint path, no userinfo, and cycle detection. Strip any credential from continuation URLs and authenticate through the transport. Reject cross-host changes unless already explicitly configured and tested. Cap pages/response bytes per partition; exceeding caps yields incomplete, not success. Partition minute queries into bounded session ranges so the base-bar limit cannot truncate a large request invisibly. Compare resulting timestamps to requested bounds, because provider snapping can widen intervals.

## 4. Session and price contracts

Use a pinned exchange-calendar library and `America/New_York` exchange time. Persist session dates as date32 and event instants as UTC timestamps. Confirm the shared US-equity schedule is appropriate for XOM's and XLE's listing venues, including exceptional closures. Freeze the exact calendar schedule and library/tzdata versions in each dataset. Never use weekday arithmetic or fixed UTC offsets. Session open/close timestamps come from that schedule; early closes are not 16:00.

Choose one verified price method per versioned dataset:

1. Prefer unadjusted daily source fields only after documentation/support evidence establishes their regular-session open/close meaning. Preserve vendor daily OHLCV separately if high/low or volume have wider coverage. Do not label the whole daily bar regular-session OHLCV merely because its open and close qualify.
2. If semantics cannot be established, use subscription-entitled unadjusted minute bars clipped to `[session_open, session_close)` by bar start. The first qualifying bar open and final qualifying bar close are observed proxies. Require the opening-minute bar and final scheduled minute bar for boundary-price validity; a later first bar or earlier last bar is flagged and not silently substituted. Persist first/last observation intervals and missing-minute diagnostics. Minute-bar close is not an independently established closing-auction print.
3. A close-timestamp auction print can require separate provider handling; never include the entire post-close minute merely to capture it. Document the chosen boundary convention. Inconsistent semantics across sources block publication until resolved.

The [extended-hours documentation](https://massive.com/knowledge-base/article/does-massive-offer-pre-market-and-after-hours-data) requires timestamp-based session separation; absence of a minute bar can reflect no qualifying trades. Thus missing minute bars are not automatically transport loss, and equal daily/minute values alone do not prove session semantics. Compare diagnostic samples spanning ordinary days, DST and early-close days, with tolerances and mismatches recorded. Any verified minute method limits the ready date envelope to minute-history entitlement, even if daily history is deeper.

Retain `observed_interval_start/end`, `session_open/close`, `price_method`, `session_semantics_verified`, and source pointers. An endpoint without exact print timestamps must retain null print time rather than inventing 09:30/16:00. Record vendor-finality status separately from `retrieved_at`; calendar close does not mean delivered or unrevisable. Historical revised data is not a point-in-time vintage. Store `historical_availability=unknown` unless evidenced; this phase does not certify next-open causal availability.

## 5. Corporate actions and returns

Store raw unadjusted prices and event-time cash values separately. Provider split adjustment is not dividend-inclusive total return. The [cash-amount documentation](https://massive.com/knowledge-base/article/does-massive-adjust-historic-dividends-for-splits) distinguishes original `cash_amount` from amounts restated on today's share basis; preserve both if supplied, but use verified original event units. Cumulative historical adjustment factors are not the event share ratio.

Support ordinary USD cash distributions for both instruments and forward/reverse splits. XLE must receive the same cash-distribution treatment as XOM. Ingest every returned action without a recurring-only filter: special/supplemental/unknown distributions, stock dividends, mergers, spin-offs, returns of capital, or reorganizations must be classified. V1 quarantines unsupported or ambiguous events; it never silently discards them. A later narrowly scoped support task may resolve them using documented economics without expanding to other tickers. No tax treatment or payment ledger is implemented.

Action queries use ex-date for distributions and effective/execution date for splits, not declaration or pay date. Preserve declaration, record, and payment dates as separate nullable fields. Missing pay date does not invalidate a mathematically supported ex-date return; it sets `payment_metadata_ready=false`. A future payment consumer must require that capability. Unknown ex-date, amount/currency, or share basis invalidates affected returns. Non-session effective/ex-dates are investigated, not silently shifted to Monday.

For adjacent exchange sessions `p` and `t`, define `k_t = split_to / split_from` as new shares per prior share, or 1 when action coverage is established and no split applies. Let `d_t` be the sum of supported ex-date cash entitlements expressed **per prior-session share**. With verified unadjusted closes:

```
price_return_t = (k_t * close_t) / close_p - 1
total_return_t = (k_t * close_t + d_t) / close_p - 1
```

No action may default to zero merely because the actions endpoint failed. For simultaneous split/dividend events, establish the entitlement share basis and ordering from evidence. If the cash amount is per post-split share, `d_t = k_t * cash_amount`; if per prior share, `d_t = cash_amount`. If ambiguous, null the return with `ambiguous_action_units`. Multiple distinct cash events may be summed after units are verified; conflicting duplicates may not. Multiple same-date share-change events require evidenced ordering or are unsupported.

Use float64 for returns; retain original JSON numeric text and canonical decimal amounts/ratios (decimal128 precision 28, scale 12; reject overflow or unsupported precision rather than round silently). The optional total-return index starts at 100 at the first valid close of each consecutive valid segment and compounds `1 + total_return`. A gap ends the segment; never bridge it or imply continuity across resets. This index assumes gross ex-date cash reinvestment at that close for measurement, without taxes/costs, and is never an executable price.

Hand-calculated oracles: 100 to 50 with a 2:1 split gives zero return; 50 to 100 with a 1:2 reverse split gives zero; 100 to 99 plus USD 1 cash gives zero; 100 to 49.5 with a 2:1 split plus USD 0.5 per new share gives zero. An absent Wednesday between Tuesday and Thursday makes Wednesday and Thursday returns invalid; Friday can become valid using Thursday's valid close. Do not forward/backfill or use `pct_change` defaults that fill gaps.

## 6. Versioned schemas

Every persisted table has `schema_version=1`, declared primary key, field types, nullability, units and foreign keys in a checked-in schema definition. Strings are UTF-8; dates date32; instants UTC microseconds; hashes lowercase SHA-256; flags booleans; reasons sorted enum arrays. Required numeric inputs must be finite. Null means unavailable, not zero. All normalized rows carry lineage through `source_refs` containing snapshot/page/JSON-pointer identifiers. Derived rows also point to their normalized parent keys. The following fields are required unless marked `?`.

| Artifact / primary key | Fields and constraints |
| --- | --- |
| `instruments` / `instrument_id` | stable internal ID, symbol, security type, currency, primary MIC, provider identifiers map, listing start/end?, identity verification status, source_refs; aliases in separate `(instrument_id, symbol, valid_from)` intervals with `valid_to?`; no overlapping conflicting identity intervals |
| `sessions` / `(calendar_id, session_date)` | open_utc, close_utc, previous/next session?, early_close, calendar/version/hash; chronological open < close |
| `capabilities` / `(probe_id, instrument_id, endpoint_contract_id, requested_start, requested_end)` | as_of, attempted interval, HTTP/status category, observed start/end?, row count, pagination complete, access state, boundary precision, evidence refs; empty success distinct from denial |
| `raw_request_manifest` / `(snapshot_id, partition_id, page_index)` | sanitized host/path/params, request fingerprint, started/retrieved UTC, response status, allowed request ID?, byte count, body hash, storage hash, next-page fingerprint?, retry count, response schema version, completion state, sanitization version |
| `vendor_bars` / `(snapshot_id, instrument_id, endpoint_contract_id, interval_start)` | interval_end?, source timestamp, raw OHLCV decimals, adjusted flag=false, volume_scope, raw symbol, provider status, source_refs; daily and minute data never collide |
| `session_prices` / `(dataset_id, instrument_id, session_date)` | raw regular open/close?, regular high/low/volume? only when verified, observation intervals?, exact print times?, method, currency, open_valid, close_valid, session_semantics_verified, reasons, source_refs; one row for every expected session |
| `actions` / `(dataset_id, instrument_id, action_key)` | provider event ID?, event type, ex/effective_date?, declaration/record/pay dates?, currency?, cash_amount?, cash_basis?, split_from/to?, distribution classification?, normalized prior-share cash?, verification state, raw-record hash, source_refs |
| `action_coverage` / `(dataset_id, instrument_id, action_type, interval_start, interval_end)` | endpoint contract, retrieval time, page chain hash, request complete, entitlement verified, classification complete; no-events success explicit; intervals must cover each evaluated return |
| `returns` / `(dataset_id, instrument_id, session_date)` | previous_expected_session, previous/current price keys, split factor?, cash per prior share?, price return?, total return?, valid, reasons, action keys[], segment_id?, total_return_index? |
| `aligned_pair` / `(dataset_id, session_date)` | XOM/XLE price and return keys, previous/next expected session?, per-leg open/close/return validity, pair_open_valid, pair_close_valid, pair_return_valid, reasons; never store a compressed inner-join timeline |
| `quality_issues` / `(audit_id, issue_id)` | rule/version, severity, instrument?, session/interval?, entity key, expected/actual sanitized evidence, affected capabilities, resolution state, evidence refs; deterministic issue ID |
| `dataset_manifest` / `dataset_id` | schema/config/normalizer/calendar versions and hashes, source snapshot IDs, requested/observed/common intervals, resolved as_of, table row counts/hashes, source-tree fingerprint, dependencies/platform, endpoint/method contracts, capability flags, audit ID, limitations, publication status |

When the provider lacks event IDs, retain candidate identity fields and the entire normalized event hash. Same economic candidate with different amounts/dates is a conflict, not two dividends. Require explicit resolution evidence; do not sum conflicting revisions. Identical repeats retain all raw provenance but one normalized event. Vendor revisions produce a new snapshot and dataset plus an old/new comparison; no update-in-place.

Pair validity is a conjunction of the relevant per-leg flags on the same calendar date. Pair returns require each leg's valid close at the immediately preceding expected session and complete supported action coverage. Open validity is independent of return validity. Next-session mapping identifies the actual next calendar session even when its data is missing; it never jumps to the next available row. No order/fill logic is present.

## 7. Validation, missing data and failure behavior

Validation layers run in order: transport/envelope → pagination/coverage → schema/identity → calendar/session semantics → OHLC/action economics → aligned outputs → artifact integrity. Preserve rejected evidence safely. A failing layer cannot produce a successful downstream readiness flag.

| Condition | Required behavior |
| --- | --- |
| 401, entitlement denial, unsupported endpoint | Stop that request immediately, persist sanitized capability failure; no empty-success conversion |
| Retry exhaustion, page loop, partial pages, truncation, missing partition | Acquisition incomplete; retain finished partitions; no dataset publication |
| Unexpected response shape, adjustment mismatch, conflicting duplicate, foreign ticker | Quarantine partition; schema/identity error; do not guess mappings or choose last row |
| Missing session bar or boundary minute | Materialize nulls and reasons; invalidate dependent price/return flags; retain calendar row |
| Nonfinite/nonpositive OHLC, impossible high/low, negative volume | Quarantine observed value and set affected validity false; never clip |
| Zero volume, unexpected interior missing minutes, suspicious action-adjusted jump | Report anomaly; investigate source coverage. Default jump warning at absolute total return > 25%, configurable and frozen before audit; never delete or winsorize |
| Unsupported/ambiguous action or incomplete action coverage | Invalidate affected returns (entire uncertain interval if coverage unknown); raw prices may remain available |
| Missing payment date only | Preserve return if other economics valid; payment capability false |
| Corrupt snapshot/hash mismatch, disk full, interrupted publication | Integrity failure; no ready marker or SQLite success record; prior published dataset unchanged |
| Provider revision | New immutable snapshot/dataset, explicit diff; old reproducible dataset retained |

HTTP and domain errors use typed exceptions with allowlisted diagnostic fields. CLI exit codes: 0 operation succeeded; 2 configuration/schema contract failure; 3 provider access failure; 4 incomplete/retryable acquisition; 5 quality gate failed; 6 storage/integrity failure. A report must still be written when enough validated metadata exists to describe failure. Bad credentials never produce a nominally successful empty report.

Separate artifact lifecycle (`staging`, `incomplete`, `quarantined`, `published`) from data capability (`ready`, `partial`, `blocked`). A complete audited dataset with legitimate gaps may publish as `partial`; this is not a fully ready dataset. `audit --require-ready` exits 5 unless the selected capability is ready across the entire declared envelope. No automatic date trimming to hide defects. A deliberately shorter clean interval must be named as a derived subset with exclusions visible in the parent report.

The initial close is an explicit return seed, not an expected valid return: return readiness is evaluated over the declared return interval starting at its next session. The report shows both the price envelope and return envelope. This is the sole structural first-row exclusion, not permission to omit internal gaps. Dataset completion also requires referential integrity, unique primary keys, consistent schema versions and exact declared row counts across all tables.

## 8. Raw snapshots, storage and reproducibility

Use local files plus SQLite metadata, with a single writer. Parquet is canonical for typed normalized tables; CSV is a convenience export only. No external service or shared live database.

```
data/
  raw/<snapshot_id>/<partition_id>/page-000001.json.gz
  raw/<snapshot_id>/manifest.json
  staging/<attempt_id>/...
  datasets/<dataset_id>/{manifest.json,instruments.parquet,sessions.parquet,...}
  catalog.sqlite
reports/<dataset_id>/<audit_id>/{index.html,quality.json,issues.csv,coverage.csv}
```

Raw storage retains response content before analytical transformation. Remove credential-bearing fields/URLs and sensitive headers at the transport boundary; use an explicit sanitation transform that preserves all market fields. Store hashes of both received bytes (hash only if unsafe) and persisted sanitized bytes, so “raw” is not falsely claimed to be an unchanged wire capture. Only allowlist metadata headers. Persist a JSON pointer or page index for every source record. Unknown error bodies are not stored verbatim; store their hash, status and safe category.

Use unique acquisition IDs plus content hashes: repeating a request can yield identical content in a different acquisition; a refresh never mutates the old acquisition. Normalization build identity is a canonical hash of selected source hashes, config, schemas, frozen calendar, and transform version. Publish a dataset manifest only after all files are flushed, re-read and hashed, then atomically rename the staging directory on the same filesystem. Commit the catalog entry last. Readers require the manifest and hashes, not SQLite alone. Startup reconciliation detects orphan directories/catalog rows without treating them as successful.

Resume only completed, hash-verified partitions from the same frozen acquisition configuration. Restart an incomplete page chain if cursor stability is unknown; do not append results from two vendor revisions. Capture the acquisition time span and disclose that paginated history is not a transactional provider snapshot. Dataset-level advisory locks have bounded timeout; stale temporary files can be cleaned only after determining no writer owns them. Explicit refresh creates a new lineage branch; cached commands never fetch missing files silently.

Record Git SHA plus dirty source fingerprint (exclude data/secrets), Python/dependency lock hash, OS/architecture, tzdata/calendar, endpoint contracts, expanded nonsecret config, row ordering, decimal conversion and numeric tolerances. Sort canonical tables by their primary keys. Compare logical normalized-table hashes across environments; Parquet compression/metadata bytes may differ. Same locked environment should also reproduce artifact bytes where deterministic writers are available. Exclude wall-clock/audit-attempt IDs from deterministic content hashes, retaining them separately.

Reproduction command reads a frozen manifest and raw archive, verifies hashes, rebuilds normalized tables and audit, then compares logical outputs. It never contacts the provider. Corruption fails closed. Retain old datasets until explicit deletion; do not define an automatic destructive retention policy. A local backup/export includes manifests, raw pages, calendar, lockfile and reports, subject to subscription usage rights; do not assume redistribution rights or upload market data publicly.

## 9. Security and Docker

Credential handling is runtime-only, preferably an authorization header if verified supported. If the provider needs a query credential, never persist the prepared URL. Redact before logging, exception handling, retry instrumentation, raw-page persistence, and report rendering. Do not pass keys on the command line. Config files contain names/placeholders, not secrets. Credential files are explicit read-only inputs; persist neither their absolute private paths nor their contents. Do not source shell files. Enforce TLS verification, bounded payloads, symbol allowlist XOM/XLE, safe path construction, and escaped HTML text. Reports use local assets, no remote scripts, trackers, or authenticated links.

Add `.gitignore` and `.dockerignore` coverage for credentials, `.env*` except example, all data/report outputs, SQLite/WAL/SHM, logs, caches, virtualenvs, local credential files and QUSA. Test exclusion with sentinel secrets and fake market files. No secret scanning of the user's home directory is required. Use restrictive local permissions on credentials and artifacts; never dump process environment or HTTP debug logs.

Use Python 3.12 initially, pinned and tested dependencies, an official slim base pinned by digest, and a non-root runtime user. Separate install/build networking from runtime. Provide native `drift-data` and the same installed entry point in Docker. Mount config and replay input read-only, explicit writable output/catalog paths, and credentials read-only only for online commands. Default offline Compose service uses `network_mode: none`; an explicit online service/profile enables provider access. No published ports, Docker socket, privileged mode or secrets in build arguments/layers. Use a read-only root filesystem with writable temporary space and mount permissions compatible with macOS Docker.

Test arm64 first and amd64 when available; label each architecture independently verified/unverified. Validate output survives container removal, read-only input remains unchanged, non-root writes work, offline replay needs no credentials, and image/config/history contain no sentinel secrets. If Docker is unavailable, native work can complete but container acceptance remains pending. Do not claim a build or parity test that was not run.

## 10. Data-quality report

`drift-data audit --dataset <id>` produces identical findings in `quality.json`, `issues.csv`, `coverage.csv`, and a browser-readable `index.html`. Report code reads saved artifacts, not live APIs. Include:

* Dataset/audit identity, scope XOM/XLE, as-of, acquisition interval, raw hashes, code/config/environment, endpoint and price-method contracts, and reproduction command.
* Per-ticker/per-endpoint entitlement evidence and requested versus returned dates; denied/empty/unresolved cases; common envelope and excluded tails. Separate accessibility, observed coverage, action coverage and valid aligned coverage.
* Expected/observed/valid session counts, missing spans, gap calendar, duplicates/conflicts, zero volume, OHLC violations, boundary-minute failures and out-of-session observations.
* Split/dividend counts and coverage intervals, amounts/units, simultaneous-action cases, unsupported events, missing pay dates, revision comparisons and unresolved anomalies.
* Per-leg and pair valid open/close/return counts; longest contiguous valid segments; every return invalidity reason; first-return null and segment resets. Denominators always use expected sessions, never surviving rows only.
* Trace view for one ordinary return, one cash event when present, and one invalid/synthetic case: raw page → normalized input → action units → derived result. Clearly label synthetic examples.
* Capability verdicts: `raw_prices_ready`, `regular_session_prices_ready`, `total_returns_ready`, `aligned_pair_ready`, `payment_metadata_ready`; historical point-in-time availability separately `unknown/verified`. Include blockers, warnings and remediation tasks with evidence.
* Explicit limitations: selected two-instrument pilot, subscription-limited history, revised vendor data, price proxy semantics and unknown historical delivery. No profitability, signal, portfolio or backtest charts/metrics.

## 11. Tests and release acceptance

Offline synthetic/mocked tests are mandatory. Live checks are explicit opt-in with credentials; normal CI must work without secrets. Never commit live market responses as fixtures without confirmed rights and sanitation. No tests may instantiate QUSA or load its data/models.

| Test group | Required cases and oracle |
| --- | --- |
| Transport | all pages followed; repeated cursor/host escape rejected; HTTP-200 error body; 401/403 no retry; 429 Retry-After; capped 5xx/timeouts; truncated partitions; empty legitimate action success; captured output free of sentinel keys |
| Calendar/timing | ordinary session, weekend, holiday, DST transitions, early close, before/after close; frozen schedule fixture independently enumerates expected UTC times; incomplete latest delivery; extended-hours exclusion; missing boundary minutes |
| Schema/normalization | duplicate exact row vs conflict; wrong symbol/currency; adjustment mismatch; malformed dates; nonfinite OHLC; high/low contradictions; stable identity; idempotent offline normalize |
| Actions/returns | the four hand-calculated examples above; no-action with verified coverage vs failed coverage; XLE cash distribution; multiple events; unsupported type; same-day unit ambiguity; future split does not rewrite old raw prices or old returns; pay date does not shift ex-date return |
| Alignment | preserve all sessions; missing one leg invalidates pair only where dependent; no gap compression; next expected session remains fixed; index segment resets; independent open/close/return validity |
| Persistence | disk full, process termination before/after rename/catalog commit, concurrent writers, modified raw page hash, incomplete restart, refresh preserves old snapshot, offline replay from portable paths |
| Reporting/security | JSON and HTML counts match; HTML escapes provider text; report renders locally offline; redaction on exceptions/URLs/page metadata; ignore/build-context sentinel tests |
| Integration/packaging | one synthetic acquisition through report with no network; optional live XOM/XLE small slice including an accessible dividend; native/container replay comparison; output persistence and each claimed architecture tested |

Numerical assertions use independent hand values with return tolerance `atol=1e-12, rtol=1e-10`; exact decimal equality for stored cash/ratios and exact calendar/key/validity equality. Compare provider diagnostics with a separately declared price tolerance based on source precision, never widening it just to pass. A future-data perturbation test must leave earlier derived returns unchanged when earlier raw inputs and actions are unchanged.

Foundation acceptance requires: both identities verified; exact measured coverage documented; complete raw lineage; selected regular-session method evidenced; every expected pair session represented; supported action units and return oracles pass; no fabricated fills or prices; immutable publication and replay verified; report agrees with tables; security checks pass; native and claimed Docker paths verified. Any absent entitlement or unsupported semantics yields a precise blocked/partial report, not a falsely complete data foundation. Short history alone does not fail acceptance if its actual supported envelope is correct and disclosed.

## 12. Bounded implementation packets for Sol or Terra

Either implementer uses the same contracts. One packet per session, focused tests and review; no delegation or model selection required. Record status, changed files, exact commands/results, limitations, and next packet in `docs/STATUS.md`. Split a packet if it crosses subsystems or introduces multiple unresolved semantic choices. The deliverables below are planned, not implemented.

| Packet | Dependencies | Bounded deliverable | Exit evidence |
| --- | --- | --- | --- |
| D0 Repository and skeleton | none | Establish separate Drift checkout; preserve license/ignore; bring plan with provenance; `pyproject.toml`, `src/drift_data`, minimal CLI, lockfile, config/schema scaffold, status log | Offline install/help/config validation; repository identity and no unrelated changes |
| D1 Safe transport | D0 | HTTP wrapper, key resolution, typed failures, retries/rate limiter, secure pagination; mocked responses only | Transport and redaction tests; no import-time network |
| D2 Access and semantics probes | D1 | Bounded doctor, identity and per-endpoint capability matrix, versioned endpoint mappings, proposed session-price method | Sanitized live evidence if credentials available; explicit blockers otherwise; no bulk ingestion |
| D3 Raw snapshot store | D1 | Immutable page/manifests, hashes, staging, lock, resume and catalog lifecycle | Corruption/crash/concurrency tests; successful mock paginated replay |
| D4 Bounded ingestion | D2, D3 | Partitioned XOM/XLE price/action/reference acquisition within verified entitlement; explicit cache/refresh | All partitions reconciled and immutable; partial failure retained, not published ready |
| D5 Sessions and raw price normalization | D2, D4 | Frozen schedule, identities, vendor bars, session prices and method metadata | DST/early-close/session-boundary fixtures; all expected rows; no adjusted prices |
| D6 Action normalization | D4, D5 | Actions, coverage intervals, dedup/conflict rules, unit conversion and capability flags | Split/cash/ambiguous/unsupported tests; no silent event filtering |
| D7 Returns and aligned pair | D5, D6 | Pure return functions, reasons, segments and pair table | Independent numerical oracles, missing-session and future-data invariance tests |
| D8 Quality audit | D7 | Rule engine and JSON/CSV findings; explicit readiness gates | Counts reconcile; every blocker has scope and lineage; no auto-trimming |
| D9 HTML report | D8 | Offline HTML using saved findings, coverage view and trace examples | Local render/visual review; no remote assets; escaped content and JSON parity |
| D10 Reproduction and revision diff | D3, D8 | Frozen-manifest rebuild, content comparison, refresh diff and portable export | Second offline build matches logical hashes; prior snapshot remains reproducible |
| D11 Docker delivery | D0, D10 | Dockerfile/Compose profiles, pinned base, mounts, non-root/offline defaults | Native/container parity and persistent outputs; actual architecture evidence |
| D12 Foundation acceptance | D2–D11 | Accessible XOM/XLE ingestion/audit, end-to-end replay, handoff documentation | Acceptance matrix with pass/fail/pending evidence; stop at data-only boundary |

Suggested modules: `cli.py`, `config.py`, `schemas.py`, `provider/{transport,polygon,capabilities}.py`, `storage/{snapshots,catalog,publish}.py`, `data/{identity,sessions,prices,actions,returns,alignment}.py`, `quality/{rules,audit}.py`, `reporting/html.py`. Provider I/O is separate from pure transforms. Avoid installing stats/ML/backtesting packages. Core interfaces: `fetch_partition(request)->PageChain`, `normalize(snapshot_manifest, contracts, calendar)->Tables`, `derive_returns(prices, actions, coverage, sessions)->Returns`, `align_pair(...)->Pair`, `audit(dataset)->Findings`, `publish(staging, findings)->DatasetManifest`.

Planned CLI: `validate-config`, `doctor --online`, `fetch --online`, `normalize --snapshot`, `audit --dataset [--require-ready]`, `report --audit`, `reproduce --dataset`, `diff --old --new`. `fetch` requires resolved date bounds/config and selected endpoint contracts; `--refresh` creates a new snapshot. The commands are not available until implemented.

Reusable assignment: “Implement packet Dn from DRIFT_DATA_FOUNDATION_PLAN.md in the verified Drift checkout. Read applicable repository instructions and STATUS first. Complete only that packet and its required tests; preserve QUSA and existing artifacts. Keep network explicit, record evidence and blockers, and stop before any model, signal, portfolio, or backtest work.”

## 13. Required changes to the existing sprint plan

| Existing section | Change for the current phase |
| --- | --- |
| Outcome/scope and Sprint map | Replace the immediate 12-stock research deliverable with XOM/XLE data foundation. Retain later sprints as deferred historical context, not next tasks |
| 0.1 Project foundation | D0–D1; use Drift package/CLI names; initialize in the verified target checkout; avoid model dependencies |
| 0.2 Bounded provider probes | D2; endpoint-specific entitlement boundaries, current/legacy action schemas, secure transport and session semantics; recent/five/ten-year probes alone are insufficient |
| 0.3 Provisional experiment manifest | Replace with capability/data manifest; two instruments only; no evaluation splits, warmups, or model-sufficiency threshold |
| 0.4 Docker | Early skeleton allowed, final acceptance D11 after offline replay; default offline profile and independently verified architectures |
| 1.1 Provider adapter/snapshots | D3–D4; immutable page-level lineage, complete pagination, interruption/resume, explicit revision selection |
| 1.2 Normalize sessions/actions | D5–D7; separate price scopes and availability timestamps; complete calendar spine; cash units and capability-specific invalidity; no historical membership schema implementation |
| 1.3 Data audit | D8–D10; quality report plus offline reproduction; freeze dataset only, not chronological research partitions |
| Sprints 2–7 | Deferred. Do not implement or further design models, signals, allocation, execution/accounting, experiment runners, or evaluation now |
| RESEARCH_SPEC sections 2–3 and 9–10 | Data sections defer to this plan; remove their ten-year target/12-stock expansion/model-window requirements from current work; preserve remaining text as future context |
| IMPLEMENTATION_HANDOFF first assignment | D0, then dependencies above. Replace automatic continuation into research with explicit stop after D12 |
| DECISIONS D003 | Dataset freeze now; research partitioning deferred. Preserve D001 existing subscription only and D002 macOS/Docker |
| Delivery checklist | Replace trade tracing and profitability verdicts with source-to-price/action-to-return tracing and data capability verdicts |

No additional user decision is needed for these defaults. Escalate only if subscription evidence makes the required regular-session price scope impossible, an action requires a material scope expansion, or the desired scope changes beyond XOM/XLE. Report technical failures and finish independent work; do not repeatedly request permission for ordinary implementation or tests. This planning deliverable does not start implementation.
