# D3 storage contract (offline)

`drift_data.storage.store.Store(root)` is an explicit local filesystem API. It
creates a local workspace and SQLite catalog without accessing the provider.
All reads, publication and replay remain offline. `acquire_partition` explicitly
invokes a supplied transport and requires its own `online=True` opt-in as well
as an online-enabled transport. The caller supplies a SHA-256 of the complete frozen acquisition configuration;
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


## Durable acquisition boundary

Live D2/D4 callers must use `acquire_partition(snapshot, config_hash, partition,
transport, url, online=True)`. A new journal is allocated per acquisition
attempt, and the transport calls its synchronous `on_page` sink after validating
and sanitizing each page, before dispatching the next request or returning.
Callback failures propagate immediately, with no network retry or next request.
Callbacks must not re-enter the same transport instance.

Each journal lives under `raw/<snapshot>/checkpoints/<partition>--<journal_id>`.
Its sealed `journal.json` permanently declares complete=false. Each received
page is compressed into a same-filesystem stage directory with a sealed page
manifest and D0 raw-request row, fsynced, atomically renamed to `page-NNNNNN`,
and its parent directory fsynced before the callback acknowledges it. A page
not yet acknowledged at process exit may be absent; a page acknowledged before
the next request is retained subject to the local filesystem's fsync guarantees.
Only validated sanitized pages are journaled; failed responses keep D1's typed
summary/hash behavior. No unvalidated/raw credential-bearing body is archived.

`read_journal` verifies configuration, journal identity, sequential indices,
cursor fingerprints, D0 rows, and archive/content hashes with bounded gzip
decoding. It returns an inspected prefix, never a resume cursor or a successful
partition. A killed process leaves immutable journal evidence; `resume` ignores
that incomplete chain and a new acquisition starts again at the first request.
Only the existing full-chain verification and `save_partition` path can record
a completed partition. Successful calls return `(attempt_id, PageChain)`.
Handled provider failures also save the ordinary failed-attempt manifest.

Journals are retained after success or failure, so a successful chain currently
has both checkpoint and final archive copies. This deliberate duplication
supports review of crash evidence; no automatic cleanup is performed. D2/D4
must retain D1's bounded page/body/chain policy and one shared transport worker.

The legacy `save_partition(PageChain|ProviderError)` remains useful for saved
outcomes and fixtures but cannot protect in-flight network pages by itself.
The new process tests exit children before/after dataset rename and catalog
commit, and during pagination. These establish process-interruption behavior;
they do not establish hardware power-loss, Windows or network-filesystem support.
