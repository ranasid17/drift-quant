"""Offline foundation commands; future online commands require explicit flags."""
import argparse
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
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return int(ExitCode.CONTRACT)
    print(json.dumps({"status": "valid", "schema_version": config.schema_version,
                      "symbols": config.symbols, "currency": config.currency}, sort_keys=True))
    return int(ExitCode.OK)
