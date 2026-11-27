import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
from drift_data.config import ConfigError, load_config
from drift_data.identity import build_id
from drift_data.schemas import ContractError, registry, schema_for, validate_row

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "configs/data_v1.toml").read_text()

class ConfigurationTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.toml"
            source.write_text(text)
            return load_config(source)

    def test_portable_config_resolves_without_creating_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.toml"
            source.write_text(CONFIG)
            config = load_config(source)
            self.assertEqual(config.symbols, ("XOM", "XLE"))
            self.assertEqual(config.data_root, Path(directory).resolve() / "data")
            self.assertEqual(config.currency, "USD")
            self.assertFalse(config.data_root.exists())
            self.assertFalse(config.reports_root.exists())

    def test_contract_scope_versions_and_unknown_keys(self):
        for text in [CONFIG.replace("schema_version = 1", "schema_version = true"),
                     CONFIG.replace("schema_version = 1", "schema_version = 2"),
                     CONFIG.replace('"XOM", "XLE"', '"XOM", "XOM"'),
                     CONFIG.replace('"USD"', '"EUR"'),
                     CONFIG.replace('schema_version = 1', 'schema_version = 1\napi_key = "SENTINEL"'),
                     CONFIG.replace('currency = "USD"', 'currency = "USD"\nunexpected = 1')]:
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.load(text)

    def test_traversal_overlap_absolute_and_empty_storage_rejected(self):
        for value in ['"../data"', '"/private/data"', '""', '"."', '"reports"', '"reports/nested"']:
            with self.subTest(value=value), self.assertRaises(ConfigError):
                self.load(CONFIG.replace('data_root = "data"', 'data_root = ' + value))

    def test_oversized_and_control_character_config_rejected(self):
        with self.assertRaises(ConfigError):
            self.load("#" * 65537)
        with self.assertRaises(ConfigError):
            self.load(CONFIG.replace('data_root = "data"', 'data_root = "bad\\u0000path"'))

class SchemaTests(unittest.TestCase):
    def test_all_expected_contracts_packaged_and_valid(self):
        expected = {"instruments", "aliases", "sessions", "capabilities", "raw_request_manifest",
                    "vendor_bars", "session_prices", "actions", "action_coverage", "returns",
                    "aligned_pair", "quality_issues", "dataset_manifest"}
        self.assertEqual(set(registry()["tables"]), expected)
        for name, entry in registry()["tables"].items():
            schema = schema_for(name)
            Draft202012Validator.check_schema(schema)
            self.assertTrue(set(entry["primary_key"]) <= set(schema["required"]))
            self.assertFalse(schema["additionalProperties"])

    def test_dates_instants_and_strict_schema_versions(self):
        row = dict(schema_version=1, calendar_id="us_equities_v1", session_date="2026-11-27",
                   open_utc="2026-11-27T14:30:00.000000Z", close_utc="2026-11-27T18:00:00.000000Z",
                   previous_session="2026-11-25", next_session="2026-11-30", early_close=True,
                   calendar_version="fixture", calendar_hash="a" * 64)
        validate_row("sessions", row)
        for change in [{"session_date":"2026-02-30"}, {"open_utc":"2026-11-27T09:30:00-05:00"},
                       {"schema_version":True}, {"early_close":0}, {"calendar_hash":"short"}]:
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate_row("sessions", dict(row, **change))

    def price(self):
        return dict(schema_version=1,dataset_id="a"*64,instrument_id="xom",session_date="2026-11-25",
                    open=None,close=None,high=None,low=None,volume=None,observed_open_start=None,
                    observed_open_end=None,observed_close_start=None,observed_close_end=None,
                    open_print_time=None,close_print_time=None,price_method="unverified",currency="USD",
                    open_valid=False,close_valid=False,session_semantics_verified=False,
                    historical_availability="unknown",reasons=["missing_bar"],source_refs=[])

    def test_missing_is_distinct_from_zero_and_false(self):
        row = self.price()
        validate_row("session_prices", row)
        validate_row("session_prices", dict(row, close="0"))  # D5 checks economic positivity.
        for change in [{"close":False}, {"close":0}, {"open_valid":None}, {"open_valid":0},
                       {"close":"NaN"}, {"close":"1.1234567890123"}, {"close":"10000000000000000"},
                       {"reasons":["unknown_reason"]}, {"reasons":["missing_bar","missing_bar"]},
                       {"reasons":["missing_bar","invalid_price"]}, {"currency":"EUR"}]:
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate_row("session_prices", dict(row, **change))
        validate_row("session_prices", dict(row, close="9999999999999999.999999999999"))
        del row["close"]
        with self.assertRaises(ContractError):
            validate_row("session_prices", row)

    def test_lineage_is_typed_and_unknown_fields_rejected(self):
        ref=dict(snapshot_id="acq-1", partition_id="xom-day", page_index=1,
                 json_pointer="/results/0", content_hash="b"*64)
        row=dict(self.price(),source_refs=[ref])
        validate_row("session_prices", row)
        for change in [dict(row,source_refs=[dict(ref,page_index=0)]), dict(row,api_key="SENTINEL")]:
            with self.assertRaises(ContractError):
                validate_row("session_prices", change)

    def test_derived_numbers_must_be_finite(self):
        row=dict(schema_version=1,dataset_id="a"*64,instrument_id="xom",session_date="2026-11-25",
                 previous_expected_session="2026-11-24",previous_price_key=["a"*64,"xom","2026-11-24"],
                 current_price_key=["a"*64,"xom","2026-11-25"],split_factor="1",cash_per_prior_share="0",
                 price_return=0.0,total_return=0.0,valid=True,reasons=[],action_keys=[],segment_id="1",total_return_index=100.0)
        validate_row("returns", row)
        for value in [float("nan"),float("inf"),float("-inf"),10**400,True]:
            with self.assertRaises(ContractError):
                validate_row("returns",dict(row,total_return=value))

class IdentityTests(unittest.TestCase):
    def descriptor(self):
        return {"config_hash":"1"*64,"source_tree_hash":"2"*64,"calendar_hash":"3"*64,
                "endpoint_contract_hash":"4"*64,"schema_hash":"5"*64,
                "source_content_hashes":["6"*64,"7"*64],"transform_version":"v1","schema_version":1}

    def test_input_order_independent_and_changes_meaningfully(self):
        descriptor=self.descriptor()
        baseline=build_id(descriptor)
        self.assertEqual(baseline,build_id(dict(reversed(list(descriptor.items())))))
        self.assertEqual(baseline,build_id(dict(descriptor,source_content_hashes=["7"*64,"6"*64,"6"*64])))
        self.assertNotEqual(baseline,build_id(dict(descriptor,calendar_hash="0"*64)))
        self.assertEqual(len(baseline),64)

    def test_output_and_clock_fields_rejected_instead_of_hashed(self):
        for field in ["dataset_id","audit_id","output_hash","retrieved_at","credential_path"]:
            with self.subTest(field=field),self.assertRaises(ContractError):
                build_id(dict(self.descriptor(),**{field:"value"}))

class InstalledOfflineTests(unittest.TestCase):
    def call(self,*args):
        with tempfile.TemporaryDirectory() as directory:
            return subprocess.run([sys.executable,*args],cwd=directory,text=True,capture_output=True)

    def test_installed_help_and_config_without_credentials(self):
        self.assertNotIn("POLYGON_API_KEY",os.environ)
        self.assertEqual(self.call("-m","drift_data","--help").returncode,0)
        result=self.call("-m","drift_data","validate-config","--config",str(ROOT/"configs/data_v1.toml"))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)["symbols"],["XOM","XLE"])
        executable=Path(sys.executable).with_name("drift-data")
        result=subprocess.run([str(executable),"--help"],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_errors_suppress_values_and_credential_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"PRIVATE_CREDENTIAL_LOCATION.toml"
            source.write_text('schema_version = 1\napi_key = "SENTINEL_SECRET"')
            result=self.call("-m","drift_data","validate-config","--config",str(source))
            self.assertEqual(result.returncode,2)
            for secret in ["SENTINEL_SECRET","PRIVATE_CREDENTIAL_LOCATION",directory]:
                self.assertNotIn(secret,result.stdout+result.stderr)
        result=self.call("-m","drift_data","validate-config","--config","/missing/private-key.toml")
        self.assertEqual(result.returncode,2)
        self.assertNotIn("private-key",result.stderr)

    def test_network_guard_applies_to_subprocesses_and_imports(self):
        result=self.call("-c","import drift_data, drift_data.cli, drift_data.schemas, drift_data.provider.transport, drift_data.provider.credentials, drift_data.provider.http")
        self.assertEqual(result.returncode,0,result.stderr)
        for expression in ["socket.create_connection(('example.com',443))", "socket.getaddrinfo('example.com',443)"]:
            result=self.call("-c","import socket; "+expression)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("Network access is forbidden",result.stderr)

    def test_imported_plan_hash(self):
        provenance=json.loads((ROOT/"docs/PLAN_PROVENANCE.json").read_text())
        actual=hashlib.sha256((ROOT/"docs/DRIFT_DATA_FOUNDATION_PLAN.md").read_bytes()).hexdigest()
        self.assertEqual(actual,provenance["source_sha256"])
        self.assertEqual(actual,provenance["imported_sha256"])

    def test_runtime_artifacts_ignored_and_example_tracked(self):
        paths=["configs/data/prices.parquet","reports/index.html", ".env.local",
               "catalog.sqlite-wal","credentials.toml","logs/provider.log"]
        for candidate in paths:
            result=subprocess.run(["git","check-ignore",candidate],cwd=ROOT,capture_output=True)
            self.assertEqual(result.returncode,0,candidate)
        result=subprocess.run(["git","check-ignore",".env.example"],cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,1)
