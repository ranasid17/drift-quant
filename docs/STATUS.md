# Implementation status

## D0 — merged and done

**Python-version update:** The owner requested Python 3.15 and Conda after
the original 3.12 testing. The project and CI now target Python 3.15; the
3.12 results below are historical evidence, not 3.15 verification. The
locked dependencies have Python 3.15 macOS arm64 wheels. Python 3.15 CI and native macOS arm64 Conda verification both passed.
See the native verification below and D0.5 in DECISIONS.md.
PR #15 merged on 27 November 2026; issue #2 is closed and marked done.

Date: 26 November 2026 (America/Chicago). Human owner: @ranasid17.
Implementer: Codex in the originating quant chat; no delegated agents.
Issue: https://github.com/ranasid17/drift-quant/issues/2
Tracker: https://github.com/ranasid17/drift-quant/issues/1
Branch: `codex/d0-data-foundation`.
Verified baseline: `bbaf2e48af0c39bfd7bd1848d8319628bc02b58f`.
Remote: `git@github.com:ranasid17/drift-quant.git`.
Current checkout: `/Users/sidrana/Projects/drift`, beside QUSA.

### Delivered

- Installable `src/drift_data` package and offline `drift-data` CLI.
- Strict TOML config with XOM/XLE/USD scope, schema version 1, safe errors and
  relative storage paths. Validation creates no output directories.
- Packaged machine-readable table registry and 13 JSON Schema row contracts,
  including aliases, typed lineage, nullability, compound keys and declared
  relationships. Cross-table integrity/economic validation remains D5-D8.
- Shared capability/lifecycle/reason/exit enums and input-only build identity.
- Hash-locked runtime/build dependencies; no statistical/model packages.
- Exact approved-plan import and provenance hash; README, contract notes,
  ignore rules, credential-name-only example, pinned offline CI workflow.
- Network-guarded tests covering installed CLI/imports, config failures,
  packaged contracts, strict missing/zero/boolean semantics, finite numbers,
  build identity exclusions, secret-safe errors, provenance and ignore rules.

### Verification evidence

Tested host: macOS arm64, Python **3.12.14** from the bundled runtime, fresh
venv `/private/tmp/drift-d0-build`. Commands executed from the Drift root:

```sh
/private/tmp/drift-d0-build/bin/python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
PIP_NO_INDEX=1 /private/tmp/drift-d0-build/bin/python -m pip install --no-deps --no-build-isolation .
/private/tmp/drift-d0-build/bin/python scripts/check_offline.py
/private/tmp/drift-d0-build/bin/python -m pip check
/private/tmp/drift-d0-build/bin/drift-data --help
/private/tmp/drift-d0-build/bin/drift-data validate-config --config configs/data_v1.toml
git diff --check
shasum -a 256 docs/DRIFT_DATA_FOUNDATION_PLAN.md
```

Results: **16 tests passed**; no broken dependency requirements; CLI help exits
0; valid config exits 0; invalid CLI configuration exits 2 without submitted
values/private paths. Tests launch from outside the source root and exercise
the installed package and packaged schema resources. Socket connections and
DNS are disabled in test Python processes and subprocesses. Dependency
bootstrap used PyPI; project installation used `PIP_NO_INDEX=1` and no build
isolation/dependency resolution.

Plan SHA-256:
`b85f66c1c336f794d882a69025256da200e0978a22a3462ad5247b1344d0d4e8`.

### Merge and remaining phase gates

Merged PR: https://github.com/ranasid17/drift-quant/pull/15.
Merge commit: `ffb09235e959db4f6b7fbd24a2b040df9ac12a9e`.
D0 issue #2 and PR #15 carry `status:done`; their board items are Done. The first
remote run failed workflow parsing before any jobs because a colon-bearing
command was a YAML plain scalar; changed it to a block scalar and validated
the YAML locally. Replacement push and pull-request CI both passed on Linux
for code commit `1b4503c` (16 tests). Evidence:
https://github.com/ranasid17/drift-quant/actions/runs/45946797305 .
This handoff-only update does not change runtime or test code; consult the PR
for the latest workflow status.
Linux/amd64 and Docker have not been exercised locally; container acceptance
belongs to D11. Provider/identity/session/action semantics and subscription
entitlements remain unverified, as expected before D2. No real-data acceptance
or financial return computation is claimed.

Next: **D1 / issue #3 — safe provider transport**, mocked tests only; then
**D3 / issue #4 — immutable store**, before **D2 / issue #5 — live probes**.

## Current native Conda verification — 27 November 2026

Installed checksum-verified Miniforge 26.9.4-2 / Conda 26.9.4 alongside the old
Anaconda installation, without shell initialization. Created the native
`~/miniforge3/envs/drift` environment using conda-forge with Python 3.15.2.
The old base and seven named environment specifications were exported to a
private backup outside this repository; these are recovery specifications,
not full copies of installed package files. Original conda-meta histories and
shell startup/configuration hashes were checked unchanged afterward.

Executed from this repository:

```sh
~/miniforge3/envs/drift/bin/python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
PIP_NO_INDEX=1 ~/miniforge3/envs/drift/bin/python -m pip install --no-deps --no-build-isolation .
~/miniforge3/envs/drift/bin/python -m pip check
~/miniforge3/envs/drift/bin/python scripts/check_offline.py
~/miniforge3/envs/drift/bin/drift-data validate-config --config configs/data_v1.toml
```

Results: Python **3.15.2**, **arm64**; all **16 tests passed**; no broken
dependencies; configuration valid. Activation through Miniforge's conda.sh
was also verified in an isolated zsh session. Linux Python 3.15 CI previously
passed at commit `8b3deb2`. Docker remains D11 scope.


## D1 — merged

Date: 27 November 2026 (America/Chicago). Human owner: @ranasid17.
Active implementer: Codex in this originating quant chat; no delegated agents.
Issue: https://github.com/ranasid17/drift-quant/issues/3
Branch: `codex/d1-provider-transport`.
Draft PR: https://github.com/ranasid17/drift-quant/pull/16 .
Baseline: merged D0 `ffb09235e959db4f6b7fbd24a2b040df9ac12a9e`.
PR #16 merged in commit `fbd11488c37ecaa0f1c22196a11ce290edf5b15c`;
issue #3 and PR #16 are marked done on the project board.

Delivered `src/drift_data/provider/{auth,errors,http,sanitize,transport}.py`:
runtime credentials, stdlib verified HTTPS, exact XOM/XLE endpoint allowlist,
explicit online opt-in, sequential rate limiting, bounded retries/deadlines,
secure same-host pagination, versioned response envelopes, redacted page
evidence, source/storage hashes and observed coverage. No new dependencies.
Changed `tests/test_transport.py`, the offline import test, README and decision
documentation; the approved plan and D0 schemas remain unchanged.

Verification on installed package, Python 3.15.2 macOS arm64, from repo root:

```sh
PIP_NO_INDEX=1 ~/miniforge3/envs/drift/bin/python -m pip install --no-deps --no-build-isolation .
~/miniforge3/envs/drift/bin/python scripts/check_offline.py
~/miniforge3/envs/drift/bin/python -m pip check
git diff --check
```

Result: **54 tests passed** (16 foundation + 38 credential/transport/adapter
tests), including synthetic TLS-adapter dispatch, truncation, caps, retries,
credential redaction and adversarial pagination. No real API credentials,
market-data requests, subscription probes or downloads were used. Provider
authentication documentation was read publicly; endpoint compatibility,
entitlements and historical coverage are not live-verified. The transport is
library-only; there is no fetching command or persistence yet. Exact behavior,
failure codes and D3 integration constraints are in PROVIDER_TRANSPORT.md.

Next packet after review/merge: **D3 / issue #4 — immutable raw store**.
D2 / issue #5 may use live provider probes only after D3 can preserve evidence.
Docker remains D11; no model, signal, portfolio or backtest work is included.

Packaging verification: initial Linux CI caught the global `credentials*`
ignore rule excluding the source module. Renamed it to tracked `auth.py`
without weakening private-file ignores. Installed a clean `git archive HEAD`
tree and reran all 54 tests successfully against that installed package.
Review uses `status:in-review`; project issue/PR remain In Progress because
the current board has Todo / In Progress / Done. Do not mark Done before merge.


## D3 — in implementation

Human owner: @ranasid17. Implementer: Codex in this chat; no delegated agents.
Issue: https://github.com/ranasid17/drift-quant/issues/4
Branch: `codex/d3-raw-store`; baseline `fbd11488c37ecaa0f1c22196a11ce290edf5b15c`.

Implemented local raw attempt archives, lineage and checksums, resume,
incomplete-attempt evidence, verified JSON pointers, dataset storage envelopes,
audit sidecars, bounded writer locks, catalog-last publication and discrepancy
reporting. API/format and explicit limitations: `docs/STORAGE.md`.
Changed `src/drift_data/storage/`, `tests/test_storage.py`, `docs/STORAGE.md`,
and this status file. Offline synthetic data only.

Native macOS arm64 / Conda Python 3.15.2 verification:

```sh
PIP_NO_INDEX=1 ~/miniforge3/envs/drift/bin/python -m pip install --no-deps --no-build-isolation .
~/miniforge3/envs/drift/bin/python scripts/check_offline.py
~/miniforge3/envs/drift/bin/python -m pip check
git diff --check
```

67 tests pass, including mocked replay, corruption, failed-chain restart,
locks, and failures before/after publication. These simulate filesystem errors;
they do not verify actual power loss, remote filesystems or Windows. The storage envelope now includes a D0-schema-validated dataset manifest, and
page metadata includes a D0-schema-validated raw request row. The audit is not
a semantic readiness verdict; all capabilities remain blocked until D8 owns
quality enforcement. Caller-supplied source links and row counts need downstream
validation before production use.
D2 live capability probes remain next after D3 review/merge. No live credentials
or provider calls were used.


## D3 follow-up — durable page evidence and acceptance review

Issue #4 remains open; PR #17 is merged. Active implementer: Codex in this
chat; owner @ranasid17; no delegated agents. Branch `codex/d3-durable-pages`,
baseline `405f4dfec1f6aa2bd33fafe11a2f405c2d968e62`.

Review disposition and criterion-level evidence: D3_ACCEPTANCE_REVIEW.md.
Added a synchronous transport page callback, storage-integrated acquisition
and verified incomplete journals. Added storage_process_worker.py and
test_storage_interruptions.py for real child exits, restart and competing
publishers. Updated STORAGE.md and PROVIDER_TRANSPORT.md with the mandatory
D2/D4 acquisition boundary. No live requests or real keys used.

Installed-package macOS arm64 / Conda Python 3.15.2 checks:

```sh
PIP_NO_INDEX=1 ~/miniforge3/envs/drift/bin/python -m pip install --no-deps --no-build-isolation .
~/miniforge3/envs/drift/bin/python scripts/check_offline.py
~/miniforge3/envs/drift/bin/python -m pip check
git diff --check
```

Result: 74 tests passed, including child-process termination at four dataset
publication points, in-flight pagination interruption, two-process publication
contention, journal corruption, config mismatch and disk-write failure.
Capabilities remain blocked. After follow-up review/merge, close D3 and start
D2; source relationship/row-count semantics remain later consumer/quality work.
Process interruption evidence does not imply hardware power-loss support.
