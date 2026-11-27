# Drift data foundation

An auditable local XOM/XLE data foundation using the existing Polygon subscription.
Current packet: D0, offline package and shared contracts. See the
[approved plan](docs/DRIFT_DATA_FOUNDATION_PLAN.md), [status](docs/STATUS.md),
[contracts](docs/CONTRACTS.md), and [delivery tracker](https://github.com/ranasid17/drift-quant/issues/1).

Requires Python 3.15. On macOS, create an isolated Conda environment from the
repository root:

```sh
conda create -n drift -c conda-forge python=3.15.2 pip
conda activate drift
python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
PIP_NO_INDEX=1 python -m pip install --no-deps --no-build-isolation .
drift-data --help
drift-data validate-config --config configs/data_v1.toml
python scripts/check_offline.py
```

On Sid's Mac, the verified native environment is already installed separately
from the older Anaconda installation. In a terminal, activate it with:

```sh
source ~/miniforge3/etc/profile.d/conda.sh
conda activate ~/miniforge3/envs/drift
```

This switches Conda for the current terminal only; the shell startup files are
unchanged. The existing Anaconda environments remain under `~/opt/anaconda3`.

Dependency bootstrap above uses the package index. Installation of this project
and all runtime/test commands afterward are offline. No API key is required for
D0. The test harness rejects socket connections and DNS in Python, including
subprocesses. It is a regression guard, not an OS-level firewall; Docker network
isolation is tested in D11.

Configuration is strict v1 TOML. It supports exactly XOM/XLE in USD. Storage
paths are relative to the config file; validation creates no directories and
prints no private path or configuration values. `--help` and `--version` are
offline. Provider requests, fetching, normalization, returns, reporting and
Docker are later packets. CLI errors use exit 2 for invalid contracts/config.

The lock includes runtime and build dependencies, pinned with hashes covering
release wheels for supported platforms. Refresh it deliberately by resolving
the pinned top-level requirements with `pip install --dry-run --ignore-installed
--report resolution.json setuptools==80.9.0 wheel==0.45.1 jsonschema==4.25.1`,
reviewing transitive versions, and recording the release wheel SHA-256 values
from PyPI. CI uses the checked-in lock rather than resolving afresh. Platform
verification is listed in STATUS; a lock alone does not verify a platform.

Human owner: @ranasid17. A Codex agent claims one ready ticket and records its
branch and evidence. Start with the repository issue's acceptance criteria.
Do not start models, signals, portfolios or backtests in this phase.
