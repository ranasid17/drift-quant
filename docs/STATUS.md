# Implementation status

## D0 — implemented; awaiting PR review

**Python-version update:** The owner requested Python 3.15 and Conda after
the original 3.12 testing. The project and CI now target Python 3.15; the
3.12 results below are historical evidence, not 3.15 verification. The
locked dependencies have Python 3.15 macOS arm64 wheels. Python 3.15 CI and native macOS arm64 Conda verification both passed.
See the current verification below and D0.5 in DECISIONS.md; PR review and
merge remain required for D0 acceptance.

Date: 26 November 2026 (America/Chicago). Human owner: @ranasid17.
Implementer: Codex in the originating quant chat; no delegated agents.
Issue: https://github.com/ranasid17/drift-quant/issues/2
Tracker: https://github.com/ranasid17/drift-quant/issues/1
Branch: `codex/d0-data-foundation`.
Verified baseline: `bbaf2e48af0c39bfd7bd1848d8319628bc02b58f`.
Remote: `git@github.com:ranasid17/drift-quant.git`.
Separate checkout: `drift-quant`, beside the original quant planning workspace.

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

### Remaining gates and next packet

Draft PR: https://github.com/ranasid17/drift-quant/pull/15.
PR review/merge is required before closing D0 and marking D1 ready. The first
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
