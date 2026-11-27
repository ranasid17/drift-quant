"""Shared v1 vocabulary; later packets extend contracts explicitly."""
from enum import IntEnum, StrEnum

class ExitCode(IntEnum):
    OK = 0
    CONTRACT = 2
    ACCESS = 3
    INCOMPLETE = 4
    QUALITY = 5
    INTEGRITY = 6

class Lifecycle(StrEnum):
    STAGING = "staging"
    INCOMPLETE = "incomplete"
    QUARANTINED = "quarantined"
    PUBLISHED = "published"

class Readiness(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"

class Capability(StrEnum):
    RAW_PRICES = "raw_prices_ready"
    REGULAR_SESSION_PRICES = "regular_session_prices_ready"
    TOTAL_RETURNS = "total_returns_ready"
    ALIGNED_PAIR = "aligned_pair_ready"
    PAYMENT_METADATA = "payment_metadata_ready"

class Reason(StrEnum):
    MISSING_BAR = "missing_bar"
    MISSING_BOUNDARY_MINUTE = "missing_boundary_minute"
    INVALID_PRICE = "invalid_price"
    INVALID_VOLUME = "invalid_volume"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    ADJUSTMENT_MISMATCH = "adjustment_mismatch"
    IDENTITY_UNVERIFIED = "identity_unverified"
    ACTION_COVERAGE_UNKNOWN = "action_coverage_unknown"
    AMBIGUOUS_ACTION_UNITS = "ambiguous_action_units"
    UNSUPPORTED_ACTION = "unsupported_action"
    CONTINUITY_BLOCKED = "continuity_blocked"
    PRICE_SEMANTICS_UNVERIFIED = "price_semantics_unverified"
    INITIAL_SEED = "initial_seed"
    PREVIOUS_CLOSE_MISSING = "previous_close_missing"
    PAYMENT_DATE_MISSING = "payment_date_missing"
