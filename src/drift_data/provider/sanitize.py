"""Sanitize JSON while preserving numeric lexemes for raw-page consumers."""
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import FailureCode, ProviderError

SENSITIVE = {"apikey", "api_key", "authorization", "token", "access_token", "password", "secret", "cookie", "set-cookie"}

class RawNumber(str):
    """A validated original JSON numeric token, serialized without quotes."""

def _invalid_constant(value):
    raise ValueError("Nonfinite JSON constant")

def decode(body):
    failed = False
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON field")
                result[key] = value
            return result
        result = json.loads(body, parse_float=RawNumber, parse_int=RawNumber,
                            parse_constant=_invalid_constant, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        failed = True
    if failed:
        raise ProviderError(FailureCode.RESPONSE)
    return result

def scrub_url(value, secret):
    failed = False
    try:
        parts = urlsplit(value)
        pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=64)
        host = parts.hostname or ""
        if parts.port not in (None, 443):
            host += ":" + str(parts.port)
        return urlunsplit((parts.scheme, host, parts.path,
                           urlencode([(k.replace(secret,"<redacted>"), v.replace(secret,"<redacted>")) for k, v in pairs if k.lower() not in SENSITIVE]), ""))
    except (ValueError, UnicodeError):
        failed = True
    if failed:
        return "<invalid-url>"

def sanitize(value, secret, *, depth=0):
    if depth > 40:
        raise ProviderError(FailureCode.RESPONSE)
    if isinstance(value, RawNumber):
        return value
    if isinstance(value, str):
        value = re.sub(r"https?://[^\s\"<>]+", lambda match: scrub_url(match.group(), secret), value)
        return value.replace(secret, "<redacted>")
    if isinstance(value, list):
        return [sanitize(item, secret, depth=depth+1) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            clean_key = key.replace(secret, "<redacted>")
            if clean_key in result:
                raise ProviderError(FailureCode.RESPONSE)
            result[clean_key] = "<redacted>" if key.lower() in SENSITIVE else sanitize(item, secret, depth=depth+1)
        return result
    return value

def encode(value):
    if isinstance(value, RawNumber):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=True) + ":" + encode(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(encode(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)
