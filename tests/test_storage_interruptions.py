"""Real child-process exits and competing publishers; all provider data mocked."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from drift_data.identity import build_id
from drift_data.provider.errors import FailureCode, ProviderError
from drift_data.storage.store import Store, StorageError
import test_storage as fixtures
import test_transport as transport_fixtures

WORKER=Path(__file__).with_name("storage_process_worker.py")

def client():
    return transport_fixtures.TransportTests().client([
        transport_fixtures.response({"results":[transport_fixtures.cash()],"next_url":transport_fixtures.ACTION+"&cursor=two"}),
        transport_fixtures.response({"results":[transport_fixtures.cash(date="2026-01-03")]})])

class InterruptionTests(unittest.TestCase):
    def test_process_exits_around_dataset_publication(self):
        for phase in ("before_rename","after_rename","before_catalog","after_catalog"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                prior_store=Store(directory)
                prior_descriptor=dict(fixtures.descriptor(),transform_version="previous")
                prior_audit=prior_store.save_audit(prior_descriptor,{"schema_version":1,"dataset_id":build_id(prior_descriptor),"marker":"previous"})
                prior_id=prior_store.publish_dataset(prior_descriptor,{"data.json":b"prior"},prior_audit,fixtures.metadata())
                prior_manifest=(Path(directory)/"datasets"/prior_id/"manifest.json").read_bytes()
                result=subprocess.run([sys.executable,str(WORKER),directory,phase],capture_output=True,timeout=15)
                self.assertEqual(result.returncode,77,result.stderr.decode())
                store=Store(directory)
                dataset=build_id(fixtures.descriptor())
                self.assertEqual(prior_manifest,(Path(directory)/"datasets"/prior_id/"manifest.json").read_bytes())
                self.assertEqual(store.read_dataset(prior_id)["dataset_id"],prior_id)
                if phase=="after_catalog":
                    self.assertEqual(store.read_dataset(dataset)["dataset_id"],dataset)
                    self.assertEqual(store.reconcile()["orphan_directories"],[])
                else:
                    with self.assertRaises(StorageError): store.read_dataset(dataset)
                    expected=0 if phase=="before_rename" else 1
                    self.assertEqual(len(store.reconcile()["orphan_directories"]),expected)

    def test_two_processes_publish_once_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            Store(root)
            processes=[subprocess.Popen([sys.executable,str(WORKER),directory,"compete"],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
            try:
                deadline=time.monotonic()+10
                while len(list(root.glob("ready-*")))<2 and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertEqual(len(list(root.glob("ready-*"))),2)
                (root/"go").write_text("go")
                results=[(process.communicate(timeout=15),process.returncode) for process in processes]
                self.assertEqual(sorted(code for _,code in results),[0,3],results)
                store=Store(root)
                dataset=build_id(fixtures.descriptor())
                before=(root/"datasets"/dataset/"manifest.json").read_bytes()
                self.assertEqual(store.read_dataset(dataset)["dataset_id"],dataset)
                self.assertEqual(before,(root/"datasets"/dataset/"manifest.json").read_bytes())
                self.assertEqual(len(list((root/"datasets").iterdir())),1)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_exit_during_fetch_retains_page_before_request_two_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(WORKER),directory,"page_exit"],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,77,result.stderr.decode())
            store=Store(directory)
            snapshot=next((Path(directory)/"raw").iterdir()).name
            journal=next((Path(directory)/"raw"/snapshot/"checkpoints").iterdir()).name.split("--",1)[1]
            evidence=store.read_journal(snapshot,fixtures.CONFIG,"xom",journal)
            self.assertEqual(len(evidence),1)
            self.assertEqual(evidence[0][0]["raw_request_manifest"]["completion_state"],"incomplete")
            self.assertIn(b'cash_amount',evidence[0][1])
            self.assertEqual(store.resume(snapshot,fixtures.CONFIG),())
            with self.assertRaises(StorageError): store.publish_snapshot(snapshot,fixtures.CONFIG)
            transport,adapter,_=client()
            store.acquire_partition(snapshot,fixtures.CONFIG,"xom",transport,transport_fixtures.ACTION,online=True)
            self.assertNotIn("cursor=",adapter.calls[0][0])
            self.assertEqual(len(adapter.calls),2)
            store.publish_snapshot(snapshot,fixtures.CONFIG)
            self.assertEqual(len(store.read_snapshot(snapshot)["xom"]),2)
            self.assertEqual(len(store.read_journal(snapshot,fixtures.CONFIG,"xom",journal)),1)

    def test_checkpoint_failure_stops_before_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            snapshot=store.begin_snapshot(fixtures.CONFIG,["xom"])
            transport,adapter,_=client()
            import drift_data.storage.store as module
            write=module._write
            def failing_write(path, content):
                if path.name=="page.json.gz":
                    raise OSError("synthetic disk full")
                return write(path,content)
            with patch.object(module,"_write",side_effect=failing_write):
                with self.assertRaises(OSError): store.acquire_partition(snapshot,fixtures.CONFIG,"xom",transport,transport_fixtures.ACTION,online=True)
            self.assertEqual(len(adapter.calls),1)
            self.assertEqual(store.resume(snapshot,fixtures.CONFIG),())

    def test_transport_failure_preserves_journal_and_failure_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            snapshot=store.begin_snapshot(fixtures.CONFIG,["xom"])
            transport,adapter,_=client()
            adapter.events[1]=transport_fixtures.response(status=403)
            with self.assertRaises(ProviderError) as caught:
                store.acquire_partition(snapshot,fixtures.CONFIG,"xom",transport,transport_fixtures.ACTION,online=True)
            self.assertEqual(caught.exception.code,FailureCode.ACCESS)
            journal=next((Path(directory)/"raw"/snapshot/"checkpoints").iterdir()).name.split("--",1)[1]
            self.assertEqual(len(store.read_journal(snapshot,fixtures.CONFIG,"xom",journal)),1)
            attempt=next((Path(directory)/"raw"/snapshot).glob("xom--*")).name.split("--",1)[1]
            evidence,pages=store.read_attempt(snapshot,fixtures.CONFIG,"xom",attempt)
            self.assertFalse(evidence["complete"])
            self.assertEqual(len(pages),1)

    def test_journal_corruption_and_config_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            snapshot=store.begin_snapshot(fixtures.CONFIG,["xom"])
            transport,_,_=client()
            store.acquire_partition(snapshot,fixtures.CONFIG,"xom",transport,transport_fixtures.ACTION,online=True)
            journal_dir=next((Path(directory)/"raw"/snapshot/"checkpoints").iterdir())
            journal=journal_dir.name.split("--",1)[1]
            with self.assertRaises(StorageError): store.read_journal(snapshot,fixtures.OTHER,"xom",journal)
            (journal_dir/"page-000001"/"page.json.gz").write_bytes(b"corrupt")
            with self.assertRaises(StorageError): store.read_journal(snapshot,fixtures.CONFIG,"xom",journal)

    def test_offline_acquisition_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            snapshot=store.begin_snapshot(fixtures.CONFIG,["xom"])
            transport,adapter,_=client()
            with self.assertRaises(StorageError): store.acquire_partition(snapshot,fixtures.CONFIG,"xom",transport,transport_fixtures.ACTION)
            self.assertEqual(adapter.calls,[])
