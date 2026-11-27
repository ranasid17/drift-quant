# D1 provider transport contract

This packet supplies a library boundary for XOM/XLE only. No import, constructor,
CLI help or configuration validation makes a request. Tests use synthetic
responses, fake clocks and a Python socket/DNS guard. Live endpoint semantics
and existing-subscription history are D2 acceptance after D3 storage exists.

## Invocation and credentials

`resolve_credential()` reads `POLYGON_API_KEY` at call time. A present environment
entry wins; an invalid or empty entry fails rather than falling back. Only an
explicit `credentials_file=Path(...)` is read otherwise: at most 64 KiB, exactly
one `POLYGON_API_KEY=value` assignment, optional matching quotes, no shell
expansion. Other entries are ignored. No QUSA path discovery, dotenv auto-load,
environment mutation, key logging or credential serialization occurs.

`Transport(credential)` defaults offline; `fetch(url)` fails `online_required`.
A future online caller must explicitly construct `Transport(credential,
online=True)` and reuse that single instance across partitions. The lock
serializes a client's requests. There is no cross-process/key-wide quota
coordination; D2/D4 must use one worker and one shared client.

Only HTTPS port 443 and exact allowlisted paths are accepted: XOM/XLE daily or
minute aggregate ranges, daily open-close, ticker reference, and symbol-filtered
v3 or stocks/v1 splits/dividends. Queries are allowlisted, reject duplicates,
and support date comparison filters. Price requests force `adjusted=false`.
Sensitive query fields are removed; secrets in other query values are rejected.
Redirects are never followed. Cursors must keep the initial host and endpoint
path; an explicitly configured second provider host never enables host switching.
Provider migration and additional endpoint schemas require reviewed changes.

## Limits and retries

| Policy | Default |
| --- | --- |
| Connect / read timeout | 5 / 30 seconds |
| Per-fetch deadline | 300 seconds, monotonic |
| Rate | 1 request every 12 seconds; initial request immediate |
| Attempts | At most 5 total per page |
| Response / chain byte cap | 2 MiB / 50 MiB, including retry bodies |
| Pages | At most 100 |

Only network failures/timeouts, 429 and 5xx retry. Exponential wait is
`min(60, 2**(attempt-1) + uniform(0,1))`; valid Retry-After seconds or aware HTTP
dates take precedence. Every retry also obeys the shared request interval.
An over-deadline wait fails immediately without sleeping or retrying.
TLS certificate verification and hostname checks are enabled; ambient proxies
are not used. Reads are bounded and declared Content-Length must match bytes.
Nonidentity content encoding, redirects, oversized bodies, malformed JSON,
duplicate keys, nonfinite constants and excessive JSON nesting fail closed.

## Result schemas and completeness

`PageChain` is immutable: pages tuple, complete, empty, row_count,
observed_start/end. Only an exhausted, validated cursor chain returns with
complete=true. Empty success requires a valid results list or explicit zero
resultsCount, never an error-shaped HTTP-200 response. Empty pages carrying a
cursor fail. Loops, caps and malformed later pages raise; they never truncate
silently or return a successful partial chain.

Each immutable `Page` includes page index, host, endpoint path, sanitized
parameters, SHA-256 request fingerprint, UTC start/retrieval instants, HTTP and
provider status, safe request ID, attempts, received byte count, source-body
hash, sanitized-body hash and bytes, row count, coverage field/start/end,
next-page fingerprint, response contract and sanitization version.

Response contracts are `aggregates-v2`, `open-close-v1`, `ticker-reference-v3`,
`actions-v1` and `actions-v3`. Aggregates require explicit OK/DELAYED plus
adjusted=false; open-close requires OK/DELAYED, matching date, open and close,
and rejects adjusted=true if echoed. Actions permit the v1 status-less envelope
only with a results list. Result counts and echoed symbols must agree. These
are transport envelopes, not economic row validation: D5-D8 own OHLC/action
values, calendars, ordering, deduplication, session alignment and returns.

Coverage is the observed min/max aggregate timestamp (epoch milliseconds),
action ex-dividend/execution date, or open-close date. Ticker reference has no
coverage date. This does not prove full requested coverage, entitlement start,
absence of missing sessions or final corporate-action completeness.

Sanitized JSON removes sensitive fields and URL query credentials, redacts
the active secret, and preserves all original numeric lexemes without float
rounding. It changes whitespace/escaping as well as credential fields. D3 must
record `json-lexemes-v1`, source hash and storage hash separately; do not label
the stored bytes as untouched wire bytes or put credentials in a manifest.

## Failure schema and D3 handoff

`ProviderError` exposes only code, http_status (optional), attempts,
completed_pages tuple and body_hash (optional). Its message is the code;
underlying exception messages, raw response text and private credential paths
are discarded. There is no HTTP/debug logger. A future caller must use these
allowlisted fields rather than dump request objects, headers or credentials.

| Codes | Behavior |
| --- | --- |
| online_required, credential_unavailable, unsafe_request | Fail before dispatch |
| authentication_failed | 401, no retry |
| entitlement_denied | Explicit NOT_ENTITLED evidence, no retry |
| access_denied_unknown | 403 or NOT_AUTHORIZED without proven entitlement reason |
| endpoint_unavailable, request_rejected | 404 / other terminal HTTP failure |
| redirect_rejected, invalid_response | Unusable response, no retry |
| retry_exhausted, deadline_exceeded | Incomplete chain; bounded stop |
| response_limit_exceeded, page_limit_exceeded, pagination_cycle | Incomplete chain; never truncate |

D3 must persist completed sanitized page evidence on a later-page failure,
record an incomplete acquisition and reason, and prevent publication. Failure
responses have only source hashes where safely available; no raw failure-body
archive is promised. A caller requiring a lower memory ceiling should lower
the byte caps. This packet performs no filesystem writes, cache reuse, snapshot
publication or resume. D3 owns atomic content-addressed persistence; D2 owns
live capability/coverage probing; D4 owns partition scheduling and ingestion.
