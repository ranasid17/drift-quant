# D2 bounded subscription feasibility

`doctor` assesses XOM/XLE identities, endpoint access, observed history and
session-method candidates using only the current runtime credential. It never
purchases access, switches providers or downloads a continuous bulk history.
Public documentation is an API contract, never proof of account entitlement.

## Install and run

Activate the existing Drift Conda environment, then install the updated lock
and project. The lock adds exchange-calendars 4.13.3 and pinned transitive
calendar dependencies, including numpy/pandas/tzdata. These serve calendar
resolution, not statistical modeling. Both arm64 macOS and Linux are tested by
the normal native/CI paths; other platforms remain unverified.

```sh
python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
PIP_NO_INDEX=1 python -m pip install --no-deps --no-build-isolation .
python scripts/check_offline.py
drift-data doctor --help
```

Live commands require explicit opt-in and a key already set as
`POLYGON_API_KEY` in the environment, or a user-selected credentials file.
Never put a key on the command line; no dotenv/QUSA discovery occurs.

```sh
drift-data doctor --online --config configs/data_v1.toml
# Continue a saved probe using the ID printed by the command:
drift-data doctor --online --config configs/data_v1.toml --resume PROBE_ID
```

`--max-attempts` accepts 1..80 per invocation, counting all HTTP dispatch
reservations including retries and pagination. A reservation is fsynced before
dispatch; process interruption may conservatively overcount a call never sent.
`--deadline-seconds` accepts 1..3600 (default 1200). There is one shared worker
at five requests/minute. A root-wide invocation lock prevents two doctors using
the same data root from dispatching concurrently; independently configured roots
still require the operator to respect the account-wide quota. A persisted UTC
dispatch reservation restores the initial wait across continuations. No automatic second invocation is started at the cap.
`--as-of` optionally freezes an aware ISO instant no later than invocation time.
An explicit `--host api.massive.com` selects the alternate approved provider
host; the default remains api.polygon.io. There is no redirect forwarding or
automatic host fallback. `--legacy-actions` probes deprecated v3 action routes
separately; use that flag again when resuming such a probe.

## Frozen request plan

The pinned XNYS calendar resolves the latest fully completed session strictly
before captured UTC as-of, without weekday arithmetic. Provider delivery/finality
is verified separately and is not assumed merely because the exchange closed.
The full schedule, library versions and UTC instants are saved. The current
XNYS schedule is the diagnostic core-session candidate for verified XNYS XOM
and ARCX XLE identities; [NYSE's current hours/calendar](https://www.nyse.com/trade/hours-calendars)
supports matching core hours and stated holiday/early-close schedules. This
does not certify historical venue continuity; D5 freezes full normalized sessions.

The initial plan probes both identities and single-session day/summary/minute
samples at recent, approximately 2/5/10/20-year dates, plus 90-day split/dividend
windows around each sample. It includes separate documented-price-floor and
bounded documented-action-floor samples. Current action routes are preferred;
there is no recurring-only filter. Additional ordinary, DST-before/after and
early-close samples use the frozen schedule, with duplicate queries removed.

Prices explicitly use adjusted=false. Minute requests span scheduled open
through scheduled close minus one millisecond; returned timestamps are checked
against [open,close), and the first and final scheduled minute must be present
for boundary validity. Missing interior minutes remain visible and do not prove
transport loss. Equal summary/minute prices are only diagnostics, not proof of
summary field semantics; disagreements remain blocking. No exact print/auction
time or historical next-open availability is invented.

Boundary refinement bisects trading sessions only between a nonempty successful
query and a strictly older explicit NOT_ENTITLED query, using the same endpoint
and ticker. An unknown 403, empty price interval or empty sparse action response
does not create that bracket. Results retain observed min/max separately from
an entitlement boundary. Adjacent tested sessions are point evidence, not proof
that every intervening historical interval is complete.

## Evidence and continuation

All provider calls go through D3's Store.acquire_partition, journaling sanitized
pages before requesting another. Each task gets a distinct acquisition; complete
chains are verified and published, failed chains remain incomplete. The doctor
state persists the active snapshot before dispatch. An interrupted task restarts
from page one; previous journals remain linked by interrupted snapshot IDs.
Already-recorded completed queries are not fetched again. Ctrl-C records an
interrupted state and continuation; a ledger write failure stops dispatch rather
than being retried as a network error. Resume rehashes saved
successful evidence and the frozen calendar, and requires the same implementation,
calendar dependency versions, host, legacy flag and as-of configuration.

The data root contains probes/PROBE_ID/state.json and calendar.json plus raw D3
evidence. The report root contains probes/PROBE_ID/{DATA_FEASIBILITY.md,
capabilities.json,endpoint_contracts.json}. These runtime directories are ignored
by Git. Reports preserve safe request IDs, schema-validated capability rows and
source snapshot/page/JSON pointers; they contain no key or credential-file path.
Only typed failure categories/status/body hashes are retained for failure bodies.
No raw response, secret, or subscription-specific report is published to GitHub.

Completed attempts include ok, delayed, empty_no_events,
empty_before_reported_listing, empty_closed_session_interval, empty_unexplained,
response_values_unverified and observations_outside_request. Transport failures
remain distinct, including authentication_failed, access_denied_unknown,
entitlement_denied, endpoint_unavailable and invalid_response. Current reference
identity does not prove aliases across a name/security transition.

Report `status=complete` means the planned probe queue (including possible
refinement) finished. It does not mean every endpoint is available or the data
foundation is ready: foundation_ready always remains false here. Sparse-action
boundaries and other unresolved observations remain explicit. `candidate_verified`
means only that the sampled minute proxy met diagnostics and identities; full
ingestion, corporate actions, quality gates and dataset publication remain later.

CLI exit 0: queue complete and minute candidate verified; 3: credentials/auth
unavailable; 4: continuation required for budget/deadline; 5: queue complete but
method blocked; 2: invalid configuration/state or local storage failure. Only
allowlisted summaries are printed. Later normalization/reporting commands remain
offline by design.

## Public contract references

- [Ticker identity](https://massive.com/docs/rest/stocks/tickers/ticker-overview)
- [Custom bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
- [Daily summary](https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary)
- [Minute session separation](https://massive.com/knowledge-base/article/does-massive-offer-pre-market-and-after-hours-data)
- [Current dividends](https://massive.com/docs/rest/stocks/corporate-actions/dividends)
- [Current splits](https://massive.com/docs/rest/stocks/corporate-actions/splits)
- [Original versus split-adjusted cash](https://massive.com/knowledge-base/article/does-massive-adjust-historic-dividends-for-splits)

Reviewed 2026-11-27. Endpoint contracts are versioned as polygon-probes-v1;
documentation statements about plan allowances are never treated as observed
account entitlements. Reports are diagnostic JSON/Markdown, not the later D9
HTML data-quality report.
