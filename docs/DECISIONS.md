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

## D0.5 — Python 3.15 and Conda

The project owner requested the latest stable Python and prefers Conda. On
26 November 2026 the latest documented stable release is Python 3.15.2.
Target the 3.15 series in package metadata and CI and pin 3.15.2 in the Conda
setup example. Runtime/build dependencies remain hash locked. The originally
approved plan is retained unchanged; this decision supersedes its 3.12 default.
Verify native installation and CI for 3.15 before claiming support.


## D1.1 — Explicit standard-library HTTPS transport

Use Bearer headers rather than credential query parameters. The provider's
[official REST quickstart](https://massive.com/docs/rest/quickstart?auth=signup)
documents Bearer authentication. Keep the default host `api.polygon.io`;
`api.massive.com` requires explicit policy selection, with no automatic
fallback or cursor host switching. Use verified TLS and disable redirects.
No new networking dependency is needed for the bounded GET-only scope.

## D1.2 — Safe page evidence before persistence

Retain source-body SHA-256 plus sanitized-body SHA-256. Sanitized JSON preserves
numeric lexemes exactly, but removes credential-bearing values/URL fields;
it is explicitly not byte-identical to the wire body. Page errors retain only
allowlisted codes, HTTP status, attempts, source hash when available and
previously completed sanitized pages. D3 must archive these as incomplete
evidence, never publish a partial chain as a complete snapshot. Raw failed
response text is deliberately not retained. D2 verifies real endpoint contracts
after D3; mocked acceptance does not establish subscription access or history.
