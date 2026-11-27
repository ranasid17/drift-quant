"""Offline snapshot storage. A completed catalog entry never substitutes for verification."""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import gzip
import io
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from drift_data.identity import build_id
from drift_data.schemas import validate_row, ContractError
from drift_data.provider.errors import ProviderError
from drift_data.provider.transport import Page, PageChain


class StorageError(Exception):
    """Storage operation failed without exposing paths or submitted values."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _name(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value) is None:
        raise StorageError("invalid identifier")
    return value


def _hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise StorageError("invalid hash")
    return value


def _validate(table, row):
    try:
        validate_row(table, row)
    except (ContractError, KeyError, TypeError):
        raise StorageError("row contract failure") from None


def _page_row(snapshot, partition, metadata, complete):
    row = {"schema_version":1, "snapshot_id":snapshot, "partition_id":partition,
           "page_index":metadata["page_index"], "host":metadata["host"],
           "endpoint_path":metadata["endpoint_path"], "parameters":dict(metadata["parameters"]),
           "request_fingerprint":metadata["request_fingerprint"], "started_at":metadata["started_at"],
           "retrieved_at":metadata["retrieved_at"], "http_status":metadata["http_status"],
           "request_id":metadata["request_id"], "byte_count":metadata["received_bytes"],
           "body_hash":metadata["body_hash"], "storage_hash":metadata["storage_hash"],
           "next_page_fingerprint":metadata["next_page_fingerprint"],
           "retry_count":metadata["attempts"]-1, "response_schema_version":metadata["response_contract"],
           "completion_state":"published" if complete else "incomplete",
           "sanitization_version":metadata["sanitization_version"]}
    _validate("raw_request_manifest",row)
    return row


def _seal(value):
    result = dict(value)
    result["manifest_hash"] = digest(canonical(value))
    return result


def _verify_manifest(data):
    if not isinstance(data, dict) or not isinstance(data.get("manifest_hash"), str):
        raise StorageError("invalid manifest")
    content = dict(data)
    recorded = content.pop("manifest_hash")
    if digest(canonical(content)) != recorded:
        raise StorageError("manifest integrity failure")
    return data


def _write(path, content):
    with path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    """Use one local filesystem root. All writes are explicit; no provider access."""

    def __init__(self, root, *, lock_timeout=5.0):
        self.root = Path(root)
        if lock_timeout <= 0 or lock_timeout > 60:
            raise StorageError("invalid lock timeout")
        self.lock_timeout = lock_timeout
        self.root.mkdir(parents=True, exist_ok=True)
        for part in ("raw", "datasets", "audits", "staging", "locks"):
            (self.root / part).mkdir(exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS objects (kind TEXT NOT NULL, id TEXT NOT NULL, manifest_hash TEXT NOT NULL, PRIMARY KEY(kind,id))")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.root / "catalog.sqlite3", timeout=self.lock_timeout)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _lock(self, kind, identifier):
        path = self.root / "locks" / (kind + "-" + _name(identifier) + ".lock")
        with path.open("a+b") as stream:
            end = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= end:
                        raise StorageError("lock timeout") from None
                    time.sleep(min(.05, max(0, end-time.monotonic())))
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _stage(self, kind):
        directory = self.root / "staging" / (kind + "-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        return directory

    def _read(self, path):
        try:
            return _verify_manifest(json.loads(path.read_bytes()))
        except (OSError, ValueError, TypeError, UnicodeError):
            raise StorageError("manifest read failure") from None

    def begin_snapshot(self, config_hash, partitions):
        _hash(config_hash)
        if not isinstance(partitions, (list, tuple)) or not partitions:
            raise StorageError("partitions required")
        partitions = [_name(p) for p in partitions]
        if len(set(partitions)) != len(partitions):
            raise StorageError("duplicate partition")
        snapshot = uuid.uuid4().hex
        directory = self.root / "raw" / snapshot
        directory.mkdir(mode=0o700)
        _write(directory / "acquisition.json", canonical(_seal({"version":1,"snapshot_id":snapshot,"config_hash":config_hash,"partitions":sorted(partitions)})))
        _sync_dir(directory)
        _sync_dir(directory.parent)
        return snapshot

    def _acquisition(self, snapshot, config_hash):
        _name(snapshot)
        _hash(config_hash)
        acquisition = self._read(self.root / "raw" / snapshot / "acquisition.json")
        if acquisition.get("snapshot_id") != snapshot or acquisition.get("config_hash") != config_hash:
            raise StorageError("acquisition configuration mismatch")
        return acquisition

    def save_partition(self, snapshot, config_hash, partition, outcome):
        _name(partition)
        with self._lock("snapshot", snapshot):
            acquisition = self._acquisition(snapshot, config_hash)
            if partition not in acquisition["partitions"]:
                raise StorageError("unknown partition")
            root = self.root / "raw" / snapshot
            if (root / "manifest.json").exists():
                raise StorageError("snapshot already published")
            complete = isinstance(outcome, PageChain) and outcome.complete is True
            if complete:
                pages = outcome.pages
                failure = None
            elif isinstance(outcome, ProviderError):
                pages = outcome.completed_pages
                failure = {"code":outcome.code.value,"http_status":outcome.http_status,"attempts":outcome.attempts,"body_hash":outcome.body_hash}
            else:
                raise StorageError("invalid partition outcome")
            existing = self._completed(root, partition)
            if existing is not None:
                raise StorageError("partition already completed")
            if not isinstance(pages, tuple) or (complete and not pages):
                raise StorageError("invalid page chain")
            stage = self._stage("partition")
            entries = []
            for index, page in enumerate(pages, 1):
                if not isinstance(page, Page) or page.page_index != index or digest(page.sanitized_body) != page.storage_hash:
                    raise StorageError("page integrity failure")
                if index > 1 and pages[index-2].next_page_fingerprint != page.request_fingerprint:
                    raise StorageError("page chain mismatch")
                metadata = asdict(page)
                body = metadata.pop("sanitized_body")
                name = "page-%06d.json.gz" % index
                compressed = gzip.compress(body, mtime=0)
                _write(stage / name, compressed)
                metadata["raw_request_manifest"] = _page_row(snapshot, partition, metadata, complete)
                metadata["archive_hash"] = digest(compressed)
                metadata["file"] = name
                entries.append(metadata)
            if complete and (pages[-1].next_page_fingerprint is not None or outcome.row_count != sum(p.row_count for p in pages)):
                raise StorageError("incomplete page chain")
            attempt = uuid.uuid4().hex
            manifest = _seal({"version":1,"snapshot_id":snapshot,"partition_id":partition,"attempt_id":attempt,"config_hash":config_hash,"complete":complete,"failure":failure,"pages":entries})
            _write(stage / "manifest.json", canonical(manifest))
            self._verify_partition(stage, snapshot, config_hash, partition)
            _sync_dir(stage)
            destination = root / (partition + "--" + attempt)
            os.rename(stage, destination)
            _sync_dir(root)
            return attempt

    def _verify_partition(self, directory, snapshot, config_hash, partition):
        manifest = self._read(directory / "manifest.json")
        if (manifest.get("snapshot_id"),manifest.get("config_hash"),manifest.get("partition_id")) != (snapshot,config_hash,partition):
            raise StorageError("partition identity mismatch")
        entries = manifest.get("pages")
        if not isinstance(entries,list):
            raise StorageError("invalid page manifest")
        previous = None
        for index, entry in enumerate(entries,1):
            expected = "page-%06d.json.gz" % index
            if entry.get("page_index") != index or entry.get("file") != expected or (previous is not None and previous != entry.get("request_fingerprint")):
                raise StorageError("invalid page order")
            try:
                compressed = (directory / expected).read_bytes()
                if len(compressed) > 3*1024*1024 or digest(compressed) != entry.get("archive_hash"):
                    raise StorageError("page integrity failure")
                with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
                    body = source.read(2*1024*1024+1)
                if len(body) > 2*1024*1024:
                    raise StorageError("page limit exceeded")
            except (OSError, EOFError, ValueError):
                raise StorageError("page read failure") from None
            if digest(compressed) != entry.get("archive_hash") or digest(body) != entry.get("storage_hash"):
                raise StorageError("page integrity failure")
            row = _page_row(snapshot, partition, entry, manifest.get("complete") is True)
            if entry.get("raw_request_manifest") != row:
                raise StorageError("raw request contract mismatch")
            previous = entry.get("next_page_fingerprint")
        if manifest.get("complete") is True and (not entries or previous is not None or manifest.get("failure") is not None):
            raise StorageError("invalid complete chain")
        return manifest

    def _completed(self, root, partition):
        matches = []
        for directory in root.glob(partition + "--*"):
            manifest = self._read(directory / "manifest.json")
            if manifest.get("complete") is True:
                matches.append(directory)
        if len(matches) > 1:
            raise StorageError("multiple completed partitions")
        return matches[0] if matches else None

    def read_attempt(self, snapshot, config_hash, partition, attempt):
        _name(snapshot)
        _name(partition)
        if not isinstance(attempt, str) or re.fullmatch(r"[0-9a-f]{32}", attempt) is None:
            raise StorageError("invalid attempt")
        acquisition = self._acquisition(snapshot, config_hash)
        if partition not in acquisition["partitions"]:
            raise StorageError("unknown partition")
        directory = self.root / "raw" / snapshot / (partition + "--" + attempt)
        manifest = self._verify_partition(directory, snapshot, config_hash, partition)
        if manifest.get("attempt_id") != attempt:
            raise StorageError("attempt identity mismatch")
        return manifest, tuple(gzip.decompress((directory / page["file"]).read_bytes()) for page in manifest["pages"])

    def resume(self, snapshot, config_hash):
        with self._lock("snapshot", snapshot):
            acquisition = self._acquisition(snapshot, config_hash)
            root = self.root / "raw" / snapshot
            ready = []
            for partition in acquisition["partitions"]:
                directory = self._completed(root, partition)
                if directory is not None:
                    self._verify_partition(directory, snapshot, config_hash, partition)
                    ready.append(partition)
            return tuple(ready)

    def publish_snapshot(self, snapshot, config_hash):
        with self._lock("snapshot", snapshot):
            acquisition = self._acquisition(snapshot, config_hash)
            root = self.root / "raw" / snapshot
            if (root / "manifest.json").exists():
                raise StorageError("snapshot already published")
            partitions = {}
            for name in acquisition["partitions"]:
                directory = self._completed(root, name)
                if directory is None:
                    raise StorageError("incomplete acquisition")
                manifest = self._verify_partition(directory, snapshot, config_hash, name)
                partitions[name] = {"directory":directory.name,"manifest_hash":manifest["manifest_hash"]}
            manifest = _seal({"version":1,"snapshot_id":snapshot,"config_hash":config_hash,"partitions":partitions})
            stage = self._stage("snapshot-manifest")
            _write(stage / "manifest.json", canonical(manifest))
            _sync_dir(stage)
            os.link(stage / "manifest.json", root / "manifest.json")
            _sync_dir(root)
            (stage / "manifest.json").unlink()
            stage.rmdir()
            with self._db() as db:
                db.execute("INSERT INTO objects VALUES (?,?,?)", ("snapshot",snapshot,manifest["manifest_hash"]))
            return manifest["manifest_hash"]

    def read_snapshot(self, snapshot):
        _name(snapshot)
        root = self.root / "raw" / snapshot
        manifest = self._read(root / "manifest.json")
        with self._db() as db:
            row = db.execute("SELECT manifest_hash FROM objects WHERE kind=? AND id=?",("snapshot",snapshot)).fetchone()
        if not row or row[0] != manifest["manifest_hash"] or manifest.get("snapshot_id") != snapshot:
            raise StorageError("snapshot not cataloged")
        acquisition = self._acquisition(snapshot,manifest["config_hash"])
        if set(manifest["partitions"]) != set(acquisition["partitions"]):
            raise StorageError("partition set mismatch")
        result = {}
        for name, item in manifest["partitions"].items():
            _name(name)
            directory = item["directory"]
            if not re.fullmatch(re.escape(name)+r"--[0-9a-f]{32}", directory):
                raise StorageError("invalid partition location")
            part = self._verify_partition(root / directory, snapshot, manifest["config_hash"], name)
            if not part["complete"] or part["manifest_hash"] != item["manifest_hash"]:
                raise StorageError("partition manifest mismatch")
            result[name] = tuple(gzip.decompress((root / directory / e["file"]).read_bytes()) for e in part["pages"])
        return result

    def save_audit(self, descriptor, audit):
        identifier = build_id(descriptor)
        if not isinstance(audit, dict) or audit.get("dataset_id") != identifier or audit.get("schema_version") != 1:
            raise StorageError("invalid audit evidence")
        data = canonical(audit)
        audit_id = digest(data)
        with self._lock("audit", audit_id):
            directory = self.root / "audits" / audit_id
            if directory.exists():
                if (directory / "audit.json").read_bytes() != data:
                    raise StorageError("audit integrity failure")
                return audit_id
            stage = self._stage("audit")
            _write(stage / "audit.json", data)
            _sync_dir(stage)
            os.rename(stage, directory)
            _sync_dir(directory.parent)
        return audit_id

    def read_pointer(self, snapshot, partition, page_index, pointer):
        pages = self.read_snapshot(snapshot)
        _name(partition)
        if partition not in pages or type(page_index) is not int or not 1 <= page_index <= len(pages[partition]):
            raise StorageError("page not found")
        if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
            raise StorageError("invalid JSON pointer")
        try:
            value = json.loads(pages[partition][page_index-1], parse_float=str, parse_int=str)
            for token in pointer.split("/")[1:] if pointer else ():
                if re.search(r"~(?![01])", token):
                    raise ValueError()
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                        raise ValueError()
                    value = value[int(token)]
                elif isinstance(value, dict):
                    value = value[token]
                else:
                    raise ValueError()
            return value
        except (ValueError, KeyError, IndexError, TypeError):
            raise StorageError("invalid JSON pointer") from None

    def publish_dataset(self, descriptor, files, audit_id, metadata):
        identifier = build_id(descriptor)
        _hash(audit_id)
        try:
            audit_data = (self.root / "audits" / audit_id / "audit.json").read_bytes()
            audit = json.loads(audit_data)
        except (OSError, ValueError, TypeError):
            raise StorageError("initial audit missing") from None
        if digest(audit_data) != audit_id or audit.get("dataset_id") != identifier or audit.get("schema_version") != 1:
            raise StorageError("initial audit integrity failure")
        if not isinstance(files, dict) or not files:
            raise StorageError("dataset files required")
        if not isinstance(metadata, dict):
            raise StorageError("dataset metadata required")
        with self._lock("dataset", identifier):
            destination = self.root / "datasets" / identifier
            if destination.exists():
                raise StorageError("dataset already exists")
            stage = self._stage("dataset")
            hashes = {}
            for name, content in sorted(files.items()):
                if not isinstance(name,str) or re.fullmatch(r"[A-Za-z0-9_-]+\.(?:parquet|json|csv)",name) is None or name == "manifest.json" or not isinstance(content,bytes):
                    raise StorageError("invalid dataset file")
                _write(stage / name, content)
                hashes[name] = digest(content)
            row = dict(metadata)
            generated = {"schema_version":1, "dataset_id":identifier,
                         "config_hash":descriptor["config_hash"],
                         "normalizer_version":descriptor["transform_version"],
                         "source_tree_hash":descriptor["source_tree_hash"],
                         "calendar_hash":descriptor["calendar_hash"],
                         "endpoint_contract_hash":descriptor["endpoint_contract_hash"],
                         "table_hashes":hashes, "initial_audit_id":audit_id,
                         "publication_status":"published"}
            if set(metadata) & (set(generated) | {"manifest_hash"}):
                raise StorageError("generated dataset field provided")
            row.update(generated)
            row["manifest_hash"] = digest(canonical(row))
            _validate("dataset_manifest", row)
            if any(value != "blocked" for value in row["capabilities"].values()):
                raise StorageError("quality gate unavailable")
            if set(row["table_row_counts"]) != set(hashes):
                raise StorageError("dataset table count mismatch")
            manifest = _seal({"version":1,"dataset_id":identifier,"build_inputs":descriptor,"file_hashes":hashes,"initial_audit_id":audit_id,"dataset_manifest":row})
            _write(stage / "manifest.json", canonical(manifest))
            self._verify_dataset(stage, identifier)
            _sync_dir(stage)
            os.rename(stage, destination)
            _sync_dir(destination.parent)
            with self._db() as db:
                db.execute("INSERT INTO objects VALUES (?,?,?)",("dataset",identifier,manifest["manifest_hash"]))
            return identifier

    def _verify_dataset(self, directory, identifier):
        manifest = self._read(directory / "manifest.json")
        if manifest.get("dataset_id") != identifier or build_id(manifest.get("build_inputs")) != identifier:
            raise StorageError("dataset identity mismatch")
        row = manifest.get("dataset_manifest")
        _validate("dataset_manifest", row)
        unsigned = dict(row)
        row_hash = unsigned.pop("manifest_hash")
        if digest(canonical(unsigned)) != row_hash or row["dataset_id"] != identifier or row["table_hashes"] != manifest.get("file_hashes") or row["initial_audit_id"] != manifest.get("initial_audit_id"):
            raise StorageError("dataset contract mismatch")
        descriptor = manifest["build_inputs"]
        for row_key, input_key in (("config_hash","config_hash"),("source_tree_hash","source_tree_hash"),("calendar_hash","calendar_hash"),("endpoint_contract_hash","endpoint_contract_hash"),("normalizer_version","transform_version")):
            if row[row_key] != descriptor[input_key]:
                raise StorageError("dataset input mismatch")
        if any(value != "blocked" for value in row["capabilities"].values()):
            raise StorageError("quality gate unavailable")
        if set(row["table_row_counts"]) != set(row["table_hashes"]):
            raise StorageError("dataset table count mismatch")
        audit_id = _hash(manifest.get("initial_audit_id"))
        try:
            audit_data = (self.root / "audits" / audit_id / "audit.json").read_bytes()
            audit = json.loads(audit_data)
        except (OSError, ValueError, TypeError):
            raise StorageError("initial audit missing") from None
        if digest(audit_data) != audit_id or audit.get("dataset_id") != identifier:
            raise StorageError("initial audit integrity failure")
        for name, expected in manifest["file_hashes"].items():
            if re.fullmatch(r"[A-Za-z0-9_-]+\.(?:parquet|json|csv)", name) is None:
                raise StorageError("invalid dataset filename")
            try:
                actual = digest((directory / name).read_bytes())
            except OSError:
                raise StorageError("dataset read failure") from None
            if actual != expected:
                raise StorageError("dataset integrity failure")
        return manifest

    def read_dataset(self, identifier):
        _hash(identifier)
        manifest = self._verify_dataset(self.root / "datasets" / identifier, identifier)
        with self._db() as db:
            row = db.execute("SELECT manifest_hash FROM objects WHERE kind=? AND id=?",("dataset",identifier)).fetchone()
        if not row or row[0] != manifest["manifest_hash"]:
            raise StorageError("dataset not cataloged")
        return manifest

    def reconcile(self):
        """Report discrepancies without repairing, deleting, or asserting success."""
        with self._db() as db:
            rows = set(db.execute("SELECT kind,id FROM objects"))
        found = set()
        for kind, directory in (("snapshot",self.root/"raw"),("dataset",self.root/"datasets")):
            for item in directory.iterdir():
                if item.is_dir() and (item / "manifest.json").is_file():
                    found.add((kind,item.name))
        return {"orphan_directories":sorted(found-rows),"missing_directories":sorted(rows-found),
                "staging":sorted(p.name for p in (self.root/"staging").iterdir())}
