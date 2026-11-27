# D0 contracts

`drift_data/contracts/registry.json` declares v1 tables, primary keys, field
types, nullability and foreign keys. Packaged `*.schema.json` files use JSON
Schema 2020-12 without remote references. `schema_for`, `registry`, and
`validate_row` are the public contract APIs. Keys are required and non-null.
JSON Schema validation is local and all messages suppress submitted values.

Canonical interchange uses decimal strings for exact original values and
ratios: at most 16 integer digits and 12 fractional digits, matching
decimal128(28,12). Dates are real ISO dates; instants are UTC with six digits
and a trailing Z. Derived returns use finite float64-compatible JSON numbers.
Later Parquet adapters map the registry's physical types; no Parquet writer is
implemented in D0. Rows always include nullable fields explicitly. A missing
observation uses null and false validity, never zero. Calendar-generated rows
may have empty source_refs, while observed rows must gain raw provenance in
D5-D8. Reason codes are unique, sorted enums. Capability readiness states
(`ready`, `partial`, `blocked`) are separate from row-validity booleans and
artifact lifecycle states. Supported scope is XOM/XLE in USD.

D0 validates row shape, types, formats, finite values, schema versions and
reason ordering. Registry foreign keys document cross-table relationships;
dataset referential integrity, identity intervals, OHLC economics, complete
action units and session adjacency are deliberately enforced in D5-D8. A row
passing its schema is not a publication/readiness verdict.

`identity.build_id` accepts only the declared input hashes, source content
hashes, transform version and schema version. Source hash sets are normalized;
all other input values retain their meaning. It rejects output hashes, audit
IDs, dataset IDs, paths and clock fields rather than silently ignoring them.
Table hashes and manifest integrity hashes are produced later by storage.
This prevents output identity from referring back to itself.

Configuration uses `config.load_config` and returns a frozen `Config`. Unknown
fields are errors, including credential values. It does not read environment
variables, create output paths, instantiate a provider or make network calls.
Relative paths are resolved against the config file's directory; parent
traversal, empty paths and overlapping data/report directories are rejected.
