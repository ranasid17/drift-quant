"""Packaged v1 row schemas; no remote references or I/O beyond package data."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from importlib.resources import files
import json
import re
from jsonschema import Draft202012Validator, FormatChecker

class ContractError(ValueError):
    """Safe row-contract failure without input values."""

FORMATS = FormatChecker()

@FORMATS.checks("utc-microsecond")
def _instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False

@FORMATS.checks("decimal28-12")
def _decimal(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9]\d*)(\.\d{1,12})?", value):
        return False
    try:
        number = Decimal(value)
        return number.is_finite() and number.copy_abs() < Decimal("1e16")
    except InvalidOperation:
        return False

def registry():
    return json.loads(files("drift_data").joinpath("contracts/registry.json").read_text())

def schema_for(table):
    entry = registry()["tables"].get(table)
    if entry is None:
        raise ContractError("Unknown v1 table contract.")
    return json.loads(files("drift_data").joinpath("contracts", entry["schema_file"]).read_text())

def validate_row(table, row):
    schema = schema_for(table)
    try:
        json.dumps(row, allow_nan=False)
    except (ValueError, TypeError):
        raise ContractError("Row is not finite JSON data.") from None
    if not Draft202012Validator(schema, format_checker=FORMATS).is_valid(row):
        raise ContractError("Row violates the v1 table contract.")
    if "reasons" in row and row["reasons"] != sorted(row["reasons"]):
        raise ContractError("Reason codes must be sorted.")
