"""D3 storage uses mocked transport pages and local temporary files only."""
from dataclasses import replace
import gzip
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from drift_data.provider.errors import FailureCode, ProviderError
from drift_data.storage.store import Store, StorageError
import test_transport as transport_fixtures
from drift_data.identity import build_id

ACTION = transport_fixtures.ACTION
cash = transport_fixtures.cash
response = transport_fixtures.response

CONFIG = "a" * 64
OTHER = "b" * 64


def descriptor():
    return {"config_hash":CONFIG,"source_tree_hash":CONFIG,"calendar_hash":CONFIG,
            "endpoint_contract_hash":CONFIG,"schema_hash":CONFIG,
            "source_content_hashes":[CONFIG],"transform_version":"v1","schema_version":1}


def chain():
    client,_,_=transport_fixtures.TransportTests().client([
        response({"results":[cash()],"next_url":ACTION+"&cursor=two"}),
        response({"results":[cash(date="2026-01-03")]})])
    return client.fetch(ACTION)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name,lock_timeout=.1)

    def test_mock_paginated_replay_and_refresh_isolation(self):
        original=chain()
        snap=self.store.begin_snapshot(CONFIG,["xom"])
        self.store.save_partition(snap,CONFIG,"xom",original)
        self.assertEqual(self.store.resume(snap,CONFIG),("xom",))
        self.store.publish_snapshot(snap,CONFIG)
        pages=self.store.read_snapshot(snap)["xom"]
        self.assertEqual(pages,tuple(p.sanitized_body for p in original.pages))
        self.assertEqual(json.loads(pages[0])["results"][0]["cash_amount"],1)
        self.assertEqual(self.store.read_pointer(snap,"xom",1,"/results/0/cash_amount"),"1")
        with self.assertRaises(StorageError): self.store.read_pointer(snap,"xom",1,"/results/00")
        second=self.store.begin_snapshot(CONFIG,["xom"])
        self.assertNotEqual(snap,second)
        self.store.save_partition(second,CONFIG,"xom",original)
        self.store.publish_snapshot(second,CONFIG)
        self.assertEqual(self.store.read_snapshot(snap)["xom"],pages)
        with self.assertRaises(StorageError): self.store.save_partition(snap,CONFIG,"xom",original)

    def test_incomplete_attempt_retained_restart_and_config_mismatch(self):
        complete=chain()
        snap=self.store.begin_snapshot(CONFIG,["xom","xle"])
        self.store.save_partition(snap,CONFIG,"xom",complete)
        failure=ProviderError(FailureCode.RETRIES,attempts=5,completed_pages=(complete.pages[0],))
        attempt=self.store.save_partition(snap,CONFIG,"xle",failure)
        root=Path(self.tmp.name)/"raw"/snap
        failed=root/("xle--"+attempt)
        self.assertFalse(json.loads((failed/"manifest.json").read_text())["complete"])
        evidence,pages=self.store.read_attempt(snap,CONFIG,"xle",attempt)
        self.assertEqual(evidence["failure"]["code"],"retry_exhausted")
        self.assertEqual(pages,(complete.pages[0].sanitized_body,))
        self.assertEqual(self.store.resume(snap,CONFIG),("xom",))
        with self.assertRaises(StorageError): self.store.publish_snapshot(snap,CONFIG)
        with self.assertRaises(StorageError): self.store.resume(snap,OTHER)
        self.store.save_partition(snap,CONFIG,"xle",complete)
        self.store.publish_snapshot(snap,CONFIG)
        self.assertTrue(failed.exists())
        self.assertEqual(set(self.store.read_snapshot(snap)),{"xom","xle"})

    def test_corruption_blocks_resume_and_replay(self):
        snap=self.store.begin_snapshot(CONFIG,["xom"])
        attempt=self.store.save_partition(snap,CONFIG,"xom",chain())
        path=Path(self.tmp.name)/"raw"/snap/("xom--"+attempt)/"page-000001.json.gz"
        self.store.publish_snapshot(snap,CONFIG)
        path.write_bytes(gzip.compress(b"{}",mtime=0))
        with self.assertRaises(StorageError): self.store.resume(snap,CONFIG)
        with self.assertRaises(StorageError): self.store.read_snapshot(snap)

    def test_rejects_truncated_chain_and_bad_hash(self):
        valid=chain()
        snap=self.store.begin_snapshot(CONFIG,["xom"])
        with self.assertRaises(StorageError): self.store.save_partition(snap,CONFIG,"xom",replace(valid,pages=(valid.pages[0],),row_count=1))
        damaged=replace(valid.pages[0],sanitized_body=b"{}")
        with self.assertRaises(StorageError): self.store.save_partition(snap,CONFIG,"xom",replace(valid,pages=(damaged,valid.pages[1])))

    def audit(self, marker="initial"):
        return self.store.save_audit(descriptor(),{"schema_version":1,"dataset_id":build_id(descriptor()),"marker":marker})

    def test_initial_audit_is_required_and_later_audit_does_not_rewrite(self):
        with self.assertRaises(StorageError): self.store.publish_dataset(descriptor(),{"data.json":b"{}"},CONFIG)
        audit=self.audit()
        dataset=self.store.publish_dataset(descriptor(),{"data.json":b"{}"},audit)
        before=(Path(self.tmp.name)/"datasets"/dataset/"manifest.json").read_bytes()
        self.audit("later")
        self.assertEqual(before,(Path(self.tmp.name)/"datasets"/dataset/"manifest.json").read_bytes())
        (Path(self.tmp.name)/"audits"/audit/"audit.json").write_bytes(b"{}")
        with self.assertRaises(StorageError): self.store.read_dataset(dataset)

    def test_dataset_atomic_publish_identity_and_corruption(self):
        audit=self.audit()
        dataset=self.store.publish_dataset(descriptor(),{"prices.parquet":b"synthetic"},audit)
        before=self.store.read_dataset(dataset)
        with self.assertRaises(StorageError): self.store.publish_dataset(descriptor(),{"prices.parquet":b"changed"},self.audit("later"))
        self.assertEqual(self.store.read_dataset(dataset),before)
        (Path(self.tmp.name)/"datasets"/dataset/"prices.parquet").write_bytes(b"corrupt")
        with self.assertRaises(StorageError): self.store.read_dataset(dataset)

    def test_catalog_failure_after_rename_is_never_readable(self):
        audit=self.audit()
        with patch.object(self.store,"_db") as db:
            db.return_value.__enter__.return_value.execute.side_effect=OSError("disk full")
            with self.assertRaises(OSError): self.store.publish_dataset(descriptor(),{"data.json":b"{}"},audit)
        report=self.store.reconcile()
        self.assertEqual(len(report["orphan_directories"]),1)
        _,identifier=report["orphan_directories"][0]
        with self.assertRaises(StorageError): self.store.read_dataset(identifier)

    def test_disk_failure_before_rename_does_not_publish(self):
        audit=self.audit()
        with patch("drift_data.storage.store._write",side_effect=OSError("disk full")):
            with self.assertRaises(OSError): self.store.publish_dataset(descriptor(),{"data.json":b"{}"},audit)
        self.assertEqual(list((Path(self.tmp.name)/"datasets").iterdir()),[])

    def test_concurrent_writer_obeys_bounded_lock(self):
        snap=self.store.begin_snapshot(CONFIG,["xom"])
        errors=[]
        def writer():
            try: self.store.save_partition(snap,CONFIG,"xom",chain())
            except Exception as error: errors.append(error)
        with self.store._lock("snapshot",snap):
            thread=threading.Thread(target=writer)
            thread.start()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],StorageError)
        self.assertEqual(self.store.resume(snap,CONFIG),())

    def test_snapshot_catalog_failure_never_presents_success(self):
        snap=self.store.begin_snapshot(CONFIG,["xom"])
        self.store.save_partition(snap,CONFIG,"xom",chain())
        with patch.object(self.store,"_db") as db:
            db.return_value.__enter__.return_value.execute.side_effect=OSError("disk full")
            with self.assertRaises(OSError): self.store.publish_snapshot(snap,CONFIG)
        self.assertIn(("snapshot",snap),self.store.reconcile()["orphan_directories"])
        with self.assertRaises(StorageError): self.store.read_snapshot(snap)

    def test_partition_and_dataset_reject_unsafe_names(self):
        with self.assertRaises(StorageError): self.store.begin_snapshot(CONFIG,["../escape"])
        audit=self.audit()
        with self.assertRaises(StorageError): self.store.publish_dataset(descriptor(),{"../escape.json":b"{}"},audit)

    def test_reconciliation_reports_missing_catalog_target_and_staging(self):
        with self.store._db() as db: db.execute("INSERT INTO objects VALUES (?,?,?)",("dataset",CONFIG,CONFIG))
        (Path(self.tmp.name)/"staging"/"abandoned").mkdir()
        report=self.store.reconcile()
        self.assertEqual(report["missing_directories"],[("dataset",CONFIG)])
        self.assertIn("abandoned",report["staging"])
