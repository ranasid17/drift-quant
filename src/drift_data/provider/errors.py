"""Allowlisted diagnostics; never retain response text or underlying errors."""
from enum import StrEnum

class FailureCode(StrEnum):
    BUDGET = "attempt_budget_exhausted"
    OFFLINE = "online_required"
    CREDENTIAL = "credential_unavailable"
    URL = "unsafe_request"
    AUTH = "authentication_failed"
    ACCESS = "access_denied_unknown"
    ENTITLEMENT = "entitlement_denied"
    ENDPOINT = "endpoint_unavailable"
    REQUEST = "request_rejected"
    RESPONSE = "invalid_response"
    REDIRECT = "redirect_rejected"
    RETRIES = "retry_exhausted"
    DEADLINE = "deadline_exceeded"
    SIZE = "response_limit_exceeded"
    PAGES = "page_limit_exceeded"
    CYCLE = "pagination_cycle"

class ProviderError(RuntimeError):
    def __init__(self, code, *, http_status=None, attempts=0, completed_pages=(), body_hash=None):
        self.code = FailureCode(code)
        self.http_status = http_status
        self.attempts = attempts
        self.completed_pages = tuple(completed_pages)
        self.body_hash = body_hash
        super().__init__(self.code.value)
