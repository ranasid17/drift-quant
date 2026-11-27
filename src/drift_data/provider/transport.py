"""Explicit online transport, serial rate limiting, safe page chains and evidence."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import math
import random
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .credentials import Credential
from .errors import FailureCode, ProviderError
from .http import ConnectionFailure, HTTPSAdapter, ResponseTooLarge
from .sanitize import RawNumber, SENSITIVE, decode, encode, sanitize

HOSTS = {"api.polygon.io", "api.massive.com"}
PATH = re.compile(r"(?:/v2/aggs/ticker/(?:XOM|XLE)/range/1/(?:day|minute)/(?:\d{4}-\d{2}-\d{2}|\d{10,16})/(?:\d{4}-\d{2}-\d{2}|\d{10,16})|/v1/open-close/(?:XOM|XLE)/\d{4}-\d{2}-\d{2}|/v3/reference/tickers/(?:XOM|XLE)|/v3/reference/(?:splits|dividends)|/stocks/v1/(?:splits|dividends))")
QUERY = {"adjusted", "sort", "order", "limit", "cursor", "ticker", "ex_dividend_date", "execution_date"}

@dataclass(frozen=True)
class Policy:
    allowed_hosts: tuple = ("api.polygon.io",)
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    deadline_seconds: float = 300.0
    requests_per_minute: float = 5.0
    max_attempts: int = 5
    max_pages: int = 100
    max_response_bytes: int = 2*1024*1024
    max_total_bytes: int = 50*1024*1024

    def __post_init__(self):
        if not isinstance(self.allowed_hosts, tuple) or not self.allowed_hosts or not set(self.allowed_hosts) <= HOSTS:
            raise ValueError("Invalid provider host policy.")
        for value in (self.connect_timeout, self.read_timeout, self.deadline_seconds, self.requests_per_minute):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid transport timing policy.")
        for value in (self.max_attempts, self.max_pages, self.max_response_bytes, self.max_total_bytes):
            if type(value) is not int or value < 1:
                raise ValueError("Invalid transport limit policy.")
        if self.max_attempts > 5:
            raise ValueError("At most five attempts are permitted.")

@dataclass(frozen=True)
class Page:
    page_index: int
    host: str
    endpoint_path: str
    parameters: tuple
    request_fingerprint: str
    started_at: str
    retrieved_at: str
    http_status: int
    provider_status: str | None
    request_id: str | None
    attempts: int
    received_bytes: int
    body_hash: str
    storage_hash: str
    sanitized_body: bytes
    row_count: int
    coverage_field: str | None
    observed_start: str | None
    observed_end: str | None
    next_page_fingerprint: str | None
    response_contract: str
    sanitization_version: str = "json-lexemes-v1"

@dataclass(frozen=True)
class PageChain:
    pages: tuple
    complete: bool
    empty: bool
    row_count: int
    observed_start: str | None
    observed_end: str | None

def _hash(value):
    return hashlib.sha256(value).hexdigest()

def _integer(value):
    return isinstance(value, RawNumber) and re.fullmatch(r"\d{1,20}", value) is not None

class Transport:
    def __init__(self, credential, *, online=False, policy=None, adapter=None,
                 clock=time.monotonic, sleep=time.sleep, wall_clock=lambda: datetime.now(timezone.utc),
                 jitter=lambda: random.uniform(0, 1)):
        if not isinstance(credential, Credential):
            raise ProviderError(FailureCode.CREDENTIAL)
        self._credential = credential
        self._online = online is True
        self.policy = policy or Policy()
        self._adapter = adapter if adapter is not None else HTTPSAdapter()
        self._clock, self._sleep, self._wall_clock, self._jitter = clock, sleep, wall_clock, jitter
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def _url(self, raw, *, original_path=None, symbol=None):
        failed = False
        try:
            if not isinstance(raw, str) or len(raw) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
                raise ValueError()
            parts = urlsplit(raw)
            if parts.scheme != "https" or parts.hostname not in self.policy.allowed_hosts or parts.port not in (None, 443) or parts.username is not None or parts.password is not None or parts.fragment or not PATH.fullmatch(parts.path):
                raise ValueError()
            if original_path is not None and parts.path != original_path:
                raise ValueError()
            pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
            clean = {}
            for key, value in pairs:
                if key.lower() in SENSITIVE:
                    continue
                base, _, modifier = key.partition(".")
                valid_key = key in QUERY or base in {"ex_dividend_date", "execution_date"} and modifier in {"gte", "lte", "gt", "lt", "eq"}
                if key in clean or not valid_key or any(ord(c) < 32 for c in value) or self._credential._value in key or self._credential._value in value:
                    raise ValueError()
                clean[key] = value
            is_actions = parts.path.endswith(("/splits", "/dividends"))
            ticker = clean.get("ticker")
            if is_actions and symbol is None and ticker not in ("XOM", "XLE"):
                raise ValueError()
            if ticker is not None and (ticker not in ("XOM", "XLE") or symbol is not None and ticker != symbol):
                raise ValueError()
            if "/aggs/" in parts.path or "/open-close/" in parts.path:
                if clean.get("adjusted", "false") != "false":
                    raise ValueError()
                clean["adjusted"] = "false"
            url = urlunsplit(("https", parts.hostname, parts.path, urlencode(sorted(clean.items())), ""))
            if self._credential._value in url:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            failed = True
        if failed:
            raise ProviderError(FailureCode.URL)
        return url

    def _wait(self, duration, deadline, pages, attempts=0):
        if self._clock() + max(0, duration) >= deadline:
            raise ProviderError(FailureCode.DEADLINE, attempts=attempts, completed_pages=pages)
        if duration > 0:
            self._sleep(duration)

    def _retry_after(self, headers):
        value = headers.get("retry-after", "")
        if value.isdigit():
            return float(value) if len(value) < 10 else math.inf
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                return None
            return max(0.0, (stamp-self._wall_clock()).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    def _request(self, url, deadline, pages, received):
        for attempt in range(1, self.policy.max_attempts+1):
            self._wait(max(0, self._next_allowed-self._clock()), deadline, pages, attempt-1)
            self._next_allowed = self._clock() + 60/self.policy.requests_per_minute
            started = self._wall_clock().isoformat(timespec="microseconds").replace("+00:00", "Z")
            failed = False
            too_large = False
            try:
                response = self._adapter.send(url, {"Authorization": self._credential.header(), "Accept": "application/json", "Accept-Encoding": "identity"},
                    connect_timeout=self.policy.connect_timeout, read_timeout=self.policy.read_timeout,
                    max_bytes=self.policy.max_response_bytes, budget=max(0.001, deadline-self._clock()))
            except (ConnectionFailure, TimeoutError, OSError):
                failed = True
            except ResponseTooLarge:
                too_large = True
            if too_large:
                raise ProviderError(FailureCode.SIZE, attempts=attempt, completed_pages=pages)
            if self._clock() >= deadline:
                raise ProviderError(FailureCode.DEADLINE, attempts=attempt, completed_pages=pages)
            if not failed:
                received[0] += len(response.body)
                if received[0] > self.policy.max_total_bytes:
                    raise ProviderError(FailureCode.SIZE, http_status=response.status, attempts=attempt, completed_pages=pages)
                if len(response.body) > self.policy.max_response_bytes:
                    raise ProviderError(FailureCode.SIZE, http_status=response.status, attempts=attempt, completed_pages=pages)
                if type(response.status) is not int or not 100 <= response.status <= 599:
                    raise ProviderError(FailureCode.RESPONSE, attempts=attempt, completed_pages=pages)
                if response.status != 429 and not 500 <= response.status <= 599:
                    if 300 <= response.status <= 399:
                        raise ProviderError(FailureCode.REDIRECT, http_status=response.status, attempts=attempt, completed_pages=pages, body_hash=_hash(response.body))
                    if response.status in (401,403,404) or not 200 <= response.status <= 299:
                        code = {401:FailureCode.AUTH,403:FailureCode.ACCESS,404:FailureCode.ENDPOINT}.get(response.status,FailureCode.REQUEST)
                        if response.status == 403:
                            try:
                                denied = decode(response.body)
                                if isinstance(denied, dict) and (denied.get("status") == "NOT_ENTITLED" or denied.get("error") == "NOT_ENTITLED"):
                                    code = FailureCode.ENTITLEMENT
                            except ProviderError:
                                pass
                        raise ProviderError(code, http_status=response.status, attempts=attempt, completed_pages=pages, body_hash=_hash(response.body))
                    return response, attempt, started
            if attempt == self.policy.max_attempts:
                raise ProviderError(FailureCode.RETRIES, http_status=None if failed else response.status, attempts=attempt, completed_pages=pages)
            server_wait = None if failed else self._retry_after({k.lower():v for k,v in response.headers.items()})
            jitter = self._jitter()
            if not isinstance(jitter,(int,float)) or not math.isfinite(jitter) or not 0 <= jitter <= 1:
                raise ValueError("Invalid jitter source.")
            delay = server_wait if server_wait is not None else min(60, 2**(attempt-1)+jitter)
            self._wait(delay,deadline,pages,attempt)

    def _envelope(self, payload, path, symbol):
        if not isinstance(payload,dict):
            raise ProviderError(FailureCode.RESPONSE)
        status=payload.get("status")
        code=payload.get("error")
        if status in ("NOT_AUTHORIZED","NOT_ENTITLED") or code in ("NOT_AUTHORIZED","NOT_ENTITLED"):
            raise ProviderError(FailureCode.ENTITLEMENT if "NOT_ENTITLED" in (status,code) else FailureCode.ACCESS)
        if "error" in payload or status is not None and status not in ("OK","DELAYED"):
            raise ProviderError(FailureCode.RESPONSE)
        for name in ("ticker","symbol"):
            if name in payload and payload[name] != symbol:
                raise ProviderError(FailureCode.RESPONSE)
        if "/aggs/" in path or "/open-close/" in path:
            if status not in ("OK","DELAYED") or ("/aggs/" in path and payload.get("adjusted") is not False) or ("adjusted" in payload and payload["adjusted"] is not False):
                raise ProviderError(FailureCode.RESPONSE)
        if "/open-close/" in path:
            if not all(key in payload for key in ("open","close","from")) or payload["from"] != path.rsplit("/",1)[-1]:
                raise ProviderError(FailureCode.RESPONSE)
            return [payload],"from","open-close-v1"
        results=payload.get("results")
        if "/reference/tickers/" in path:
            if not isinstance(results,dict) or results.get("ticker") != symbol:
                raise ProviderError(FailureCode.RESPONSE)
            return [results],None,"ticker-reference-v3"
        if results is None and "resultsCount" in payload and _integer(payload["resultsCount"]) and int(payload["resultsCount"])==0:
            results=[]
        if not isinstance(results,list) or any(not isinstance(row,dict) for row in results):
            raise ProviderError(FailureCode.RESPONSE)
        for name in ("resultsCount","count"):
            if name in payload and (not _integer(payload[name]) or int(payload[name]) != len(results)):
                raise ProviderError(FailureCode.RESPONSE)
        for row in results:
            if "ticker" in row and row["ticker"] != symbol:
                raise ProviderError(FailureCode.RESPONSE)
        field="t" if "/aggs/" in path else "ex_dividend_date" if path.endswith("dividends") else "execution_date"
        return results,field,"aggregates-v2" if "/aggs/" in path else "actions-"+ ("v1" if path.startswith("/stocks/") else "v3")

    def fetch(self, url):
        if not self._online:
            raise ProviderError(FailureCode.OFFLINE)
        with self._lock:
            return self._fetch(url)

    def _fetch(self, url):
        url=self._url(url)
        initial=urlsplit(url)
        params=dict(parse_qsl(initial.query))
        symbol=params.get("ticker") or next((name for name in ("XOM","XLE") if "/"+name in initial.path),None)
        pages=[]
        seen=set()
        received=[0]
        observed=[]
        deadline=self._clock()+self.policy.deadline_seconds
        while True:
            fingerprint=_hash(url.encode())
            if fingerprint in seen:
                raise ProviderError(FailureCode.CYCLE,completed_pages=pages)
            if len(pages) >= self.policy.max_pages:
                raise ProviderError(FailureCode.PAGES,completed_pages=pages)
            seen.add(fingerprint)
            response,attempts,started=self._request(url,deadline,pages,received)
            headers={k.lower():v for k,v in response.headers.items()}
            if headers.get("content-encoding","identity") not in ("identity",""):
                raise ProviderError(FailureCode.RESPONSE,completed_pages=pages)
            try:
                payload=decode(response.body)
                rows,field,contract=self._envelope(payload,initial.path,symbol)
                next_url=payload.get("next_url")
                if next_url is not None and (not isinstance(next_url,str) or not next_url or not rows):
                    raise ProviderError(FailureCode.RESPONSE)
                next_url=self._url(next_url,original_path=initial.path,symbol=symbol) if next_url else None
                if next_url and urlsplit(next_url).hostname != initial.hostname:
                    raise ProviderError(FailureCode.URL)
                safe=sanitize(payload,self._credential._value)
                stored=encode(safe).encode()
            except ProviderError as error:
                raise ProviderError(error.code,http_status=response.status,attempts=attempts,completed_pages=pages,body_hash=_hash(response.body)) from None
            values=[]
            for row in rows:
                value=row.get(field) if field else None
                if field=="t":
                    if not _integer(value):
                        raise ProviderError(FailureCode.RESPONSE,completed_pages=pages)
                    values.append(int(value))
                elif value is not None:
                    if not isinstance(value,str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}",value) is None:
                        raise ProviderError(FailureCode.RESPONSE,completed_pages=pages)
                    values.append(value)
            observed.extend(values)
            request_id=safe.get("request_id")
            if not isinstance(request_id,str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}",request_id) is None:
                request_id=None
            parts=urlsplit(url)
            page=Page(len(pages)+1,parts.hostname,parts.path,tuple(parse_qsl(parts.query)),fingerprint,
                started,self._wall_clock().isoformat(timespec="microseconds").replace("+00:00","Z"),
                response.status,safe.get("status"),request_id,attempts,len(response.body),_hash(response.body),_hash(stored),stored,
                len(rows),field,str(min(values)) if values else None,str(max(values)) if values else None,
                _hash(next_url.encode()) if next_url else None,contract)
            pages.append(page)
            if next_url is None:
                return PageChain(tuple(pages),True,not any(p.row_count for p in pages),sum(p.row_count for p in pages),
                                 str(min(observed)) if observed else None,str(max(observed)) if observed else None)
            url=next_url
