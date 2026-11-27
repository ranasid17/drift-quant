"""Offline subprocess fixture. Deliberate exits simulate process interruption."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import time

from drift_data.identity import build_id
from drift_data.storage.store import Store, StorageError
import drift_data.storage.store as storage_module
import test_storage as fixtures
import test_transport as transport_fixtures

root, phase = Path(sys.argv[1]), sys.argv[2]
store = Store(root)

if phase == "page_exit":
    snapshot = store.begin_snapshot(fixtures.CONFIG,["xom"])
    client, adapter, _ = transport_fixtures.TransportTests().client([
        transport_fixtures.response({"results":[transport_fixtures.cash()],"next_url":transport_fixtures.ACTION+"&cursor=two"}),
        transport_fixtures.response({"results":[transport_fixtures.cash(date="2026-01-03")]})])
    send = adapter.send
    def dispatch(*args, **kwargs):
        if len(adapter.calls) == 1:
            os._exit(77)
        return send(*args, **kwargs)
    adapter.send = dispatch
    store.acquire_partition(snapshot,fixtures.CONFIG,"xom",client,transport_fixtures.ACTION,online=True)
    raise AssertionError("exit did not happen")

descriptor = fixtures.descriptor()
audit = store.save_audit(descriptor,{"schema_version":1,"dataset_id":build_id(descriptor),"marker":"crash-fixture"})
if phase in {"before_rename", "after_rename"}:
    rename = storage_module.os.rename
    def intercept(source, destination):
        target = Path(destination)
        is_dataset = target.parent.name == "datasets"
        if is_dataset and phase == "before_rename":
            os._exit(77)
        result = rename(source,destination)
        if is_dataset and phase == "after_rename":
            os._exit(77)
        return result
    storage_module.os.rename = intercept
elif phase in {"before_catalog", "after_catalog"}:
    connect = store._db
    @contextmanager
    def intercept_db():
        if phase == "before_catalog":
            os._exit(77)
        with connect() as connection:
            yield connection
        os._exit(77)
    store._db = intercept_db
elif phase == "compete":
    (root/("ready-"+str(os.getpid()))).write_text("ready")
    deadline = time.monotonic()+10
    while not (root/"go").exists():
        if time.monotonic()>deadline:
            raise SystemExit(10)
        time.sleep(.01)
try:
    store.publish_dataset(descriptor,{"data.json":b"{}"},audit,fixtures.metadata())
except StorageError:
    raise SystemExit(3)
