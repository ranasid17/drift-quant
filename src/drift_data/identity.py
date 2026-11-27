"""Input-only build identity. Financial transformations are later packets."""
import hashlib
import json
import re

from drift_data.schemas import ContractError

HASH_FIELDS = ("config_hash", "source_tree_hash", "calendar_hash", "endpoint_contract_hash", "schema_hash")
FIELDS = {*HASH_FIELDS, "source_content_hashes", "transform_version", "schema_version"}

def build_id(descriptor):
    if not isinstance(descriptor, dict) or set(descriptor) != FIELDS:
        raise ContractError("Build identity requires only the declared v1 input fields.")
    valid_hash = lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if any(not valid_hash(descriptor[field]) for field in HASH_FIELDS):
        raise ContractError("Build identity requires SHA-256 input hashes.")
    sources = descriptor["source_content_hashes"]
    if not isinstance(sources, list) or not sources or any(not valid_hash(value) for value in sources):
        raise ContractError("Build identity requires source content hashes.")
    if type(descriptor["schema_version"]) is not int or descriptor["schema_version"] != 1:
        raise ContractError("Unsupported build schema version.")
    if not isinstance(descriptor["transform_version"], str) or not descriptor["transform_version"]:
        raise ContractError("Build identity requires a transform version.")
    normalized = dict(descriptor, source_content_hashes=sorted(set(sources)))
    content = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(content).hexdigest()
