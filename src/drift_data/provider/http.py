"""Bounded HTTPS GET with verified TLS, no redirects/proxies, no HTTP logging."""
from dataclasses import dataclass, field
import http.client
import ssl
import time
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Response:
    status: int
    headers: dict = field(repr=False)
    body: bytes = field(repr=False)

class ConnectionFailure(Exception):
    """Network failure with all underlying exception details discarded."""

class ResponseTooLarge(Exception):
    pass

class HTTPSAdapter:
    def send(self, url, headers, *, connect_timeout, read_timeout, max_bytes, budget):
        parts = urlsplit(url)
        end = time.monotonic() + budget
        connection = http.client.HTTPSConnection(parts.hostname, port=443,
            timeout=min(connect_timeout, budget), context=ssl.create_default_context())
        failed = False
        too_large = False
        response = None
        try:
            connection.connect()
            connection.sock.settimeout(min(read_timeout, max(0.001, end-time.monotonic())))
            target = parts.path + ("?" + parts.query if parts.query else "")
            connection.request("GET", target, headers=headers)
            incoming = connection.getresponse()
            safe_headers = {key.lower(): value for key, value in incoming.getheaders()
                            if key.lower() in {"content-length", "content-type", "content-encoding", "retry-after"}}
            length = safe_headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                too_large = True
            else:
                chunks = []
                size = 0
                while True:
                    remaining = end-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    if connection.sock is not None:
                        connection.sock.settimeout(min(read_timeout, remaining))
                    chunk = incoming.read1(min(65536, max_bytes-size+1))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        too_large = True
                        break
                if not too_large:
                    body = b"".join(chunks)
                    if length is not None and len(body) != int(length):
                        failed = True
                    else:
                        response = Response(incoming.status, safe_headers, body)
        except (OSError, http.client.HTTPException, ValueError):
            failed = True
        finally:
            connection.close()
        if too_large:
            raise ResponseTooLarge()
        if failed or response is None:
            raise ConnectionFailure()
        return response
