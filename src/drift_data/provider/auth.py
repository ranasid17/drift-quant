"""Explicit, runtime-only credential resolution. No shell evaluation."""
from dataclasses import dataclass, field
import os
from pathlib import Path

from .errors import FailureCode, ProviderError

@dataclass(frozen=True, repr=False)
class Credential:
    _value: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self._value, str) or not 8 <= len(self._value) <= 512 or any(not 33 <= ord(c) <= 126 for c in self._value):
            raise ProviderError(FailureCode.CREDENTIAL)

    def __repr__(self):
        return "Credential(<redacted>)"

    def header(self):
        return "Bearer " + self._value

def resolve_credential(*, environ=None, credentials_file=None):
    environment = os.environ if environ is None else environ
    if "POLYGON_API_KEY" in environment:
        return Credential(environment["POLYGON_API_KEY"])
    values = []
    failed = False
    if credentials_file is not None:
        try:
            with Path(credentials_file).open("rb") as stream:
                data = stream.read(65537)
            if len(data) > 65536:
                failed = True
            else:
                for line in data.decode("utf-8").splitlines():
                    name, separator, value = line.partition("=")
                    if separator and name.strip() == "POLYGON_API_KEY":
                        value = value.strip()
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                            value = value[1:-1]
                        values.append(value)
        except (OSError, ValueError, UnicodeError):
            failed = True
    if failed or len(values) != 1:
        raise ProviderError(FailureCode.CREDENTIAL)
    return Credential(values[0])
