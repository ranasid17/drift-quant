"""Strict, offline TOML configuration; never resolves credentials."""
from dataclasses import dataclass
from pathlib import Path
import tomllib

class ConfigError(ValueError):
    """An allowlisted configuration error safe to display."""

@dataclass(frozen=True)
class Config:
    schema_version: int
    symbols: tuple[str, ...]
    currency: str
    data_root: Path
    reports_root: Path

def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != expected:
        raise ConfigError("Configuration fields do not match the v1 contract.")

def _directory(value, base):
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        raise ConfigError("Storage directories must be nonempty paths.")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or value == ".":
        raise ConfigError("Storage directories must be relative without parent traversal.")
    try:
        return (base / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        raise ConfigError("Storage directory could not be resolved.") from None

def load_config(filename):
    source = Path(filename)
    try:
        with source.open("rb") as stream:
            content = stream.read(65537)
        if len(content) > 65536:
            raise ConfigError("Configuration exceeds the size limit.")
        data = tomllib.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise ConfigError("Configuration could not be read as TOML.") from None
    _keys(data, {"schema_version", "data", "storage"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ConfigError("Unsupported configuration schema version.")
    _keys(data["data"], {"symbols", "currency"})
    if data["data"]["symbols"] != ["XOM", "XLE"] or data["data"]["currency"] != "USD":
        raise ConfigError("The v1 data scope is XOM and XLE in USD.")
    _keys(data["storage"], {"data_root", "reports_root"})
    base = source.resolve().parent
    data_root = _directory(data["storage"]["data_root"], base)
    reports_root = _directory(data["storage"]["reports_root"], base)
    if data_root == reports_root or data_root in reports_root.parents or reports_root in data_root.parents:
        raise ConfigError("Data and report directories must not overlap.")
    return Config(1, ("XOM", "XLE"), "USD", data_root, reports_root)
