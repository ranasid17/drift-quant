# Implementation decisions

## D0.1 — Strict TOML foundation configuration

Use Python 3.12's standard-library TOML parser for the initial configuration,
instead of adding YAML parsing to the skeleton. D0's data scope is fixed to
XOM/XLE in USD. Online transport and its explicit credential-file handling
are deferred to D1. Config parsing never resolves credentials.

## D0.2 — JSON contracts before Parquet adapters

Use packaged JSON Schema 2020-12 contracts plus a table registry for keys,
physical types and foreign-key declarations. Exact decimals use canonical
strings in interchange; later writers map them to decimal128(28,12). This
lets D0 enforce missing/null/boolean distinctions without prematurely adding
pandas/PyArrow ingestion. Cross-table/economic checks remain D5-D8.

## D0.3 — Bootstrap networking and offline checks

Dependency installation is explicitly networked and hash locked. Project
installation disables index access and build isolation. Runtime tests install
a Python network guard into subprocesses; D11 supplies OS/container network
isolation. The guard is not advertised as a system firewall.

## D0.4 — Input-only dataset identities

Build identity hashes only declared source-content/schema/config/calendar/
endpoint/source-tree inputs and transform version. It rejects circular output
fields. Audit/manifest integrity hashes and publication semantics remain D3.
