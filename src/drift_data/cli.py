"""Offline foundation commands; future online commands require explicit flags."""
import argparse
from datetime import datetime
import sqlite3
import json
import sys
from drift_data import __version__
from drift_data.config import ConfigError, load_config
from drift_data.enums import ExitCode

def main(argv=None):
    parser = argparse.ArgumentParser(prog="drift-data", description="Drift XOM/XLE data foundation (offline by default).")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-config", help="Validate v1 TOML without network or credentials.")
    validate.add_argument("--config", required=True)
    doctor = commands.add_parser("doctor", help="Probe the existing subscription with explicit online opt-in.")
    doctor.add_argument("--config", required=True)
    doctor.add_argument("--online", action="store_true")
    doctor.add_argument("--credentials-file")
    doctor.add_argument("--resume", metavar="PROBE_ID")
    doctor.add_argument("--host", choices=("api.polygon.io","api.massive.com"))
    doctor.add_argument("--as-of", help="Optional timezone-aware ISO instant, frozen across continuation.")
    doctor.add_argument("--legacy-actions", action="store_true", help="Probe deprecated action routes separately; never automatic.")
    doctor.add_argument("--max-attempts", type=int, default=80)
    doctor.add_argument("--deadline-seconds", type=float, default=1200)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return int(ExitCode.CONTRACT)
    if args.command == "doctor":
        from drift_data.provider.doctor import run
        from drift_data.provider.errors import ProviderError
        from drift_data.storage.store import StorageError
        from drift_data.schemas import ContractError
        if not args.online:
            print("online_required",file=sys.stderr)
            return int(ExitCode.CONTRACT)
        try:
            as_of=datetime.fromisoformat(args.as_of.replace("Z","+00:00")) if args.as_of else None
            result=run(config,online=True,host=args.host,as_of=as_of,resume=args.resume,
                       credentials_file=args.credentials_file,max_attempts=args.max_attempts,
                       deadline_seconds=args.deadline_seconds,legacy=args.legacy_actions)
        except ProviderError as error:
            print(error.code.value,file=sys.stderr)
            return int(ExitCode.ACCESS)
        except (StorageError,ContractError,OSError,sqlite3.Error,ValueError,TypeError):
            print("doctor_failed",file=sys.stderr)
            return int(ExitCode.CONTRACT)
        print(json.dumps({key:result[key] for key in ("probe_id","status","attempts_total","completed_tasks","requested_tasks")},sort_keys=True))
        if result["status"] in {"credentials_unavailable","authentication_failed"}:
            return int(ExitCode.ACCESS)
        if result["status"] != "complete":
            return int(ExitCode.INCOMPLETE)
        return int(ExitCode.OK if result["method"]["status"]=="candidate_verified" else ExitCode.QUALITY)
    print(json.dumps({"status": "valid", "schema_version": config.schema_version,
                      "symbols": config.symbols, "currency": config.currency}, sort_keys=True))
    return int(ExitCode.OK)
