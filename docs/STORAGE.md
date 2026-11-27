# D3 storage contract (offline)

`drift_data.storage.store.Store(root)` is an explicit local filesystem API. It
creates a private workspace and SQLite catalog but never accesses the provider.
The caller supplies a SHA-256 of the complete frozen acquisition configuration;
it must include endpoint/symbol, request intervals, provider options, and
partition definitions without credentials. Storage compares this hash but does
not construct or validate the underlying configuration. Store roots must be
private, trusted local directories on one filesystem supporting flock, hard
links, fsync and atomic rename. Network filesystems and Windows are unverified.

`begin_snapshot(config_hash, partition_ids)` allocates a unique acquisition.
`save_partition` consumes a D1 `PageChain` or `ProviderError`, stores each
sanitized page in deterministic gzip, and writes a sealed attempt manifest.
Source-body hashes, sanitized-body hashes, compressed archive hashes and D1
lineage remain distinct. Failure attempts preserve completed pages and typed
failure metadata. They cannot count as complete. `read_attempt` verifies and
returns this evidence, including for failed acquisitions.

Resume uses `resume(snapshot, config_hash)`: only complete, re-read,
hash-verified partitions from that exact configuration are reusable. Failed
chains start again at their first page as new immutable attempts. A refresh
allocates a new snapshot. `publish_snapshot` refuses missing/failed partitions;
it verifies all complete chains, writes the manifest durably, then commits its
catalog record. `read_snapshot` checks both catalog and manifests and rehashes
every page. `read_pointer` applies RFC 6901 pointers to verified pages and
returns numeric tokens as strings to retain precision. Stored pages are D1
sanitized representations, not original provider bytes.

`save_audit` stores content-addressed synthetic audit evidence, and
`publish_dataset` uses `identity.build_id` on the input-only descriptor, checks
the referenced audit exists, stages files on the same filesystem, verifies
hashes, renames the directory and commits the catalog last. `read_dataset`
checks identity, audit and file hashes. A second audit is independent and never
rewrites the first manifest. The sealed storage envelope includes a validated D0 `dataset_manifest` row.
Its audit check validates storage identity only, not quality findings. Until D8
implements semantic acceptance, this storage API rejects capabilities other
than `blocked`; publication is not a quality-readiness assertion. The caller
provides source snapshot IDs and input hashes; D3 does not independently prove
that the supplied source hashes or row counts match the claimed sources. No production publisher or
quality gate is exposed by the CLI.

Manifests are canonical JSON with `manifest_hash` calculated excluding that
field. Snapshot fields are version, snapshot_id, config_hash, partitions mapping
to attempt-directory and manifest-hash. Partition fields are version,
snapshot_id, partition_id, attempt_id, config_hash, complete, typed failure,
and ordered D1 Page fields plus archive filename/hash. Dataset envelope fields
are version, dataset_id, input descriptor, file hashes, initial audit ID,
validated dataset_manifest row, and envelope manifest hash. Each page entry
also includes a validated D0 raw_request_manifest row. Their manifest hashes
exclude their own hash fields.

The catalog is a convenience index, never sole evidence: after rename but before
catalog commit, a directory is an orphan and cannot be read as published.
`reconcile()` reports catalog/directory discrepancies and abandoned staging
without repair, success claims or deletion. The caller must resolve orphans
deliberately; there is no automatic resume of an uncommitted publication.
Successful snapshot manifest staging is cleaned; other failed stages remain
for inspection. No automatic retention/deletion policy is implemented.

One bounded per-object `flock` serializes writers on the local host. Immutable
attempt/dataset identifiers prevent overwriting prior artifacts. Exceptions
caused by the filesystem or SQLite may propagate; callers must not log paths or
private input blindly. Hashes detect accidental alteration, not a malicious
actor able to rewrite every manifest and the catalog. Storage assumes pages
came from trusted D1 sanitization and callers do not pass arbitrary secrets.
