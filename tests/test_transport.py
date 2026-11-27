"""D1 uses synthetic responses only; fake time makes retries instantaneous."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drift_data.provider.credentials import Credential, resolve_credential
from drift_data.provider.errors import FailureCode, ProviderError
from drift_data.provider.http import ConnectionFailure, HTTPSAdapter, Response, ResponseTooLarge
from drift_data.provider.sanitize import decode, encode, sanitize
from drift_data.provider.transport import Policy, Transport

SECRET = "SENTINEL-PRIVATE-KEY"
HOST = "https://api.polygon.io"
ACTION = HOST + "/stocks/v1/dividends?ticker=XOM"
AGGS = HOST + "/v2/aggs/ticker/XOM/range/1/day/2026-01-02/2026-01-05?adjusted=false"

class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def clock(self):
        return self.now

    def sleep(self, value):
        self.waits.append(value)
        self.now += value

    def wall(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.now)

class FakeAdapter:
    def __init__(self, events):
        self.events = list(events)
        self.calls = []

    def send(self, url, headers, **options):
        self.calls.append((url, headers, options))
        if not self.events:
            raise AssertionError("Unexpected extra provider request")
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

def response(body=None, status=200, headers=None, raw=None):
    return Response(status, headers or {}, raw if raw is not None else json.dumps(body if body is not None else {"status":"OK","results":[]}).encode())

def cash(date="2026-01-02", **fields):
    return dict(ticker="XOM", ex_dividend_date=date, cash_amount=1, **fields)

class CredentialTests(unittest.TestCase):
    def test_environment_precedes_explicit_file_without_opening_file(self):
        key = resolve_credential(environ={"POLYGON_API_KEY":SECRET},credentials_file="/missing/private-file")
        self.assertEqual(key.header(),"Bearer "+SECRET)
        self.assertNotIn(SECRET,str(key))
        self.assertNotIn(SECRET,repr(key))

    def test_explicit_file_key_only_and_no_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            filename=Path(directory)/"private.env"
            filename.write_text('OTHER=ignored\nPOLYGON_API_KEY="'+SECRET+'"\n')
            self.assertEqual(resolve_credential(environ={},credentials_file=filename).header(),"Bearer "+SECRET)
            filename.write_text('POLYGON_API_KEY='+SECRET+'\nPOLYGON_API_KEY='+SECRET)
            with self.assertRaises(ProviderError):
                resolve_credential(environ={},credentials_file=filename)

    def test_invalid_missing_or_header_injection_credentials_fail_safely(self):
        for value in ["", "short", SECRET+"\r\nInjected: x", None]:
            with self.subTest(value=value),self.assertRaises(ProviderError) as caught:
                resolve_credential(environ={"POLYGON_API_KEY":value})
            self.assertEqual(caught.exception.code,FailureCode.CREDENTIAL)
            self.assertNotIn(SECRET,str(caught.exception))
        with self.assertRaises(ProviderError) as caught:
            resolve_credential(environ={},credentials_file="/missing/SENTINEL_PRIVATE_PATH")
        self.assertNotIn("SENTINEL_PRIVATE_PATH",str(caught.exception))

class TransportTests(unittest.TestCase):
    def client(self, events, **policy):
        clock=FakeTime()
        adapter=FakeAdapter(events)
        transport=Transport(Credential(SECRET),online=True,adapter=adapter,policy=Policy(**policy),
            clock=clock.clock,sleep=clock.sleep,wall_clock=clock.wall,jitter=lambda:0)
        return transport,adapter,clock

    def fail(self, code, client, url=ACTION):
        with self.assertRaises(ProviderError) as caught:
            client.fetch(url)
        self.assertEqual(caught.exception.code,code)
        self.assertNotIn(SECRET,str(caught.exception))
        self.assertNotIn(SECRET,repr(caught.exception))
        return caught.exception

    def test_encoded_secret_and_unknown_query_modifiers_are_rejected(self):
        for query in ["cursor="+"".join("%"+format(ord(c),"02X") for c in SECRET), "ticker.bad=XOM", "cursor.gte=abc"]:
            client,adapter,_=self.client([])
            self.fail(FailureCode.URL,client,ACTION+"&"+query)
            self.assertEqual(adapter.calls,[])

    def test_malformed_second_page_preserves_completed_evidence(self):
        client,_,_=self.client([response({"results":[cash()],"next_url":ACTION+"&cursor=two"}),response(raw=b"{")])
        error=self.fail(FailureCode.RESPONSE,client)
        self.assertEqual(len(error.completed_pages),1)
        self.assertEqual(error.body_hash,hashlib.sha256(b"{").hexdigest())

    def test_retry_after_is_case_insensitive_and_huge_value_hits_deadline(self):
        client,_,clock=self.client([response(status=429,headers={"Retry-After":"30"}),response()])
        client.fetch(ACTION)
        self.assertEqual(clock.now,30)
        client,adapter,clock=self.client([response(status=429,headers={"Retry-After":"9"*10000})])
        self.fail(FailureCode.DEADLINE,client)
        self.assertEqual(len(adapter.calls),1)
        self.assertEqual(clock.waits,[])

    def test_explicit_http_entitlement_differs_from_unknown_forbidden(self):
        client,_,_=self.client([response({"status":"NOT_ENTITLED","message":SECRET},status=403)])
        self.fail(FailureCode.ENTITLEMENT,client)

    def test_open_close_without_adjustment_echo_uses_explicit_request(self):
        client,adapter,_=self.client([response({"status":"OK","symbol":"XOM","from":"2026-01-02","open":1,"close":2})])
        self.assertEqual(client.fetch(HOST+"/v1/open-close/XOM/2026-01-02").row_count,1)
        self.assertIn("adjusted=false",adapter.calls[0][0])

    def test_cursor_cannot_switch_even_between_approved_hosts(self):
        client,adapter,_=self.client([response({"results":[cash()],"next_url":ACTION.replace("api.polygon.io","api.massive.com")+"&cursor=two"})],allowed_hosts=("api.polygon.io","api.massive.com"))
        self.fail(FailureCode.URL,client)
        self.assertEqual(len(adapter.calls),1)

    def test_retry_bodies_count_toward_partition_byte_cap(self):
        client,adapter,_=self.client([response(raw=b"x"*60,status=503),response(raw=b"x"*60,status=503)],max_total_bytes=100)
        self.fail(FailureCode.SIZE,client)
        self.assertEqual(len(adapter.calls),2)

    def test_huge_numeric_count_is_a_typed_failure(self):
        client,_,_=self.client([response(raw=b'{"results":[],"count":'+b"9"*5000+b"}")])
        self.fail(FailureCode.RESPONSE,client)

    def test_timeout_429_and_5xx_exhaustion_are_bounded(self):
        for event in (TimeoutError(SECRET),response(status=429),response(status=503)):
            with self.subTest(kind=type(event).__name__):
                client,adapter,_=self.client([event]*5)
                with self.assertNoLogs():
                    error=self.fail(FailureCode.RETRIES,client)
                self.assertEqual(error.attempts,5)
                self.assertEqual(len(adapter.calls),5)

    def test_constructor_is_offline_and_default_fetch_is_blocked(self):
        adapter=FakeAdapter([])
        client=Transport(Credential(SECRET),adapter=adapter)
        self.fail(FailureCode.OFFLINE,client)
        self.assertEqual(adapter.calls,[])

    def test_empty_success_has_one_complete_page(self):
        client,adapter,clock=self.client([response()])
        chain=client.fetch(ACTION)
        self.assertTrue(chain.complete)
        self.assertTrue(chain.empty)
        self.assertEqual(chain.row_count,0)
        self.assertEqual(len(chain.pages),1)
        self.assertEqual(adapter.calls[0][1]["Authorization"],"Bearer "+SECRET)
        self.assertEqual(adapter.calls[0][2]["connect_timeout"],5)
        self.assertEqual(adapter.calls[0][2]["read_timeout"],30)
        self.assertEqual(clock.waits,[])

    def test_pagination_coverage_hashes_and_serial_rate_limit(self):
        next_url=ACTION+"&cursor=second&apiKey="+SECRET
        events=[response({"status":"OK","results":[cash()],"next_url":next_url}),
                response({"status":"OK","results":[cash("2026-01-05")],"request_id":"request_2"})]
        client,adapter,clock=self.client(events)
        chain=client.fetch(ACTION)
        self.assertEqual((chain.row_count,chain.observed_start,chain.observed_end),(2,"2026-01-02","2026-01-05"))
        self.assertEqual(clock.waits,[12])
        self.assertEqual(chain.pages[1].page_index,2)
        self.assertEqual(chain.pages[0].next_page_fingerprint,chain.pages[1].request_fingerprint)
        self.assertEqual(chain.pages[1].request_id,"request_2")
        for page in chain.pages:
            self.assertEqual(hashlib.sha256(page.sanitized_body).hexdigest(),page.storage_hash)
            self.assertNotIn(SECRET,repr(page))
        self.assertNotIn(SECRET,adapter.calls[1][0])
        self.assertNotIn("apiKey",adapter.calls[1][0])
        self.assertNotIn("apiKey",chain.pages[0].sanitized_body.decode())

    def test_rate_limit_also_applies_between_fetch_calls(self):
        client,adapter,clock=self.client([response(),response()])
        client.fetch(ACTION)
        client.fetch(ACTION)
        self.assertEqual(clock.waits,[12])

    def test_cross_host_userinfo_port_fragment_and_endpoint_rejected(self):
        urls=[ACTION.replace("https:","http:"),ACTION.replace("api.polygon.io","evil.invalid"),
              ACTION.replace("api.polygon.io","api.polygon.io.evil.invalid"),
              ACTION.replace("api.polygon.io","user@api.polygon.io"),ACTION+"#fragment",
              ACTION.replace("api.polygon.io","api.polygon.io:444"),
              ACTION.replace("/stocks/v1/dividends","/private/endpoint"),
              ACTION.replace("ticker=XOM","ticker=AAPL"),ACTION+"&ticker=XLE",
              ACTION+"&api_key="+SECRET+"\n"]
        for url in urls:
            with self.subTest(url=url):
                client,adapter,_=self.client([])
                self.fail(FailureCode.URL,client,url)
                self.assertFalse(adapter.calls)

    def test_cross_host_cursor_rejected_before_second_request(self):
        client,adapter,_=self.client([response({"status":"OK","results":[cash()],"next_url":ACTION.replace("api.polygon.io","api.massive.com")})])
        self.fail(FailureCode.URL,client)
        self.assertEqual(len(adapter.calls),1)

    def test_explicit_second_provider_host_is_supported_without_fallback(self):
        client,adapter,_=self.client([response()],allowed_hosts=("api.massive.com",))
        chain=client.fetch(ACTION.replace("api.polygon.io","api.massive.com"))
        self.assertTrue(chain.complete)
        self.assertEqual(len(adapter.calls),1)

    def test_cursor_path_changes_are_rejected(self):
        url=ACTION.replace("dividends","splits")+"&cursor=second"
        client,adapter,_=self.client([response({"results":[cash()],"next_url":url})])
        self.fail(FailureCode.URL,client)
        self.assertEqual(len(adapter.calls),1)

    def test_redirect_never_followed(self):
        client,adapter,_=self.client([response(status=302,headers={"location":"https://evil.invalid"})])
        self.fail(FailureCode.REDIRECT,client)
        self.assertEqual(len(adapter.calls),1)

    def test_http_errors_do_not_retry_or_retain_body(self):
        for status,code in [(401,FailureCode.AUTH),(403,FailureCode.ACCESS),(404,FailureCode.ENDPOINT),(400,FailureCode.REQUEST)]:
            client,adapter,_=self.client([response({"message":SECRET},status=status)])
            error=self.fail(code,client)
            self.assertEqual((len(adapter.calls),error.attempts),(1,1))
            self.assertIsNotNone(error.body_hash)

    def test_200_error_bodies_and_wrong_schema_are_not_empty_success(self):
        bodies=[{"status":"ERROR","resultsCount":0,"message":SECRET},
                {"status":"OK","error":"BAD","results":[]},
                {"status":"OK"}, {"status":"OK","results":{}},
                {"status":"OK","results":[1]}, {"status":"OK","results":[],"count":1},
                {"status":"OK","results":[cash(ticker_alias="bad")],"ticker":"XLE"}]
        for body in bodies:
            with self.subTest(body=body):
                client,adapter,_=self.client([response(body)])
                self.fail(FailureCode.RESPONSE,client)
                self.assertEqual(len(adapter.calls),1)
        client,_,_=self.client([response({"status":"NOT_ENTITLED","results":[]})])
        self.fail(FailureCode.ENTITLEMENT,client)

    def test_valid_v1_actions_without_status_are_accepted(self):
        client,_,_=self.client([response({"results":[cash()]})])
        self.assertEqual(client.fetch(ACTION).row_count,1)

    def test_bounded_retry_and_redacted_network_exception(self):
        client,adapter,clock=self.client([ConnectionFailure(SECRET)]*5)
        error=self.fail(FailureCode.RETRIES,client)
        self.assertEqual((len(adapter.calls),error.attempts),(5,5))
        self.assertEqual(clock.now,48)

    def test_transient_statuses_retry_then_succeed(self):
        client,adapter,clock=self.client([response(status=503),response(status=429),response()])
        page=client.fetch(ACTION).pages[0]
        self.assertEqual((len(adapter.calls),page.attempts),(3,3))
        self.assertEqual(clock.now,24)

    def test_retry_after_seconds_and_http_date(self):
        for header in ["30","Thu, 01 Jan 2026 00:00:30 GMT"]:
            with self.subTest(header=header):
                client,adapter,clock=self.client([response(status=429,headers={"retry-after":header}),response()])
                client.fetch(ACTION)
                self.assertEqual(clock.now,30)

    def test_retry_after_deadline_stops_without_sleep_or_retry(self):
        client,adapter,clock=self.client([response(status=429,headers={"retry-after":"3600"})])
        self.fail(FailureCode.DEADLINE,client)
        self.assertEqual(clock.waits,[])
        self.assertEqual(len(adapter.calls),1)

    def test_rate_wait_deadline_and_page_limit_preserve_prior_page(self):
        event=response({"results":[cash()],"next_url":ACTION+"&cursor=second"})
        for policy,code in [({"deadline_seconds":10},FailureCode.DEADLINE),({"max_pages":1},FailureCode.PAGES)]:
            client,adapter,_=self.client([event],**policy)
            error=self.fail(code,client)
            self.assertEqual(len(error.completed_pages),1)
            self.assertEqual(len(adapter.calls),1)

    def test_cyclic_cursor_is_incomplete(self):
        client,adapter,_=self.client([response({"results":[cash()],"next_url":ACTION})])
        error=self.fail(FailureCode.CYCLE,client)
        self.assertEqual(len(error.completed_pages),1)

    def test_byte_and_page_caps_fail_not_truncate(self):
        client,adapter,_=self.client([response(raw=b"x"*101)],max_response_bytes=100)
        self.fail(FailureCode.SIZE,client)
        client,adapter,_=self.client([ResponseTooLarge()])
        self.fail(FailureCode.SIZE,client)
        client,adapter,_=self.client([response()],max_total_bytes=1)
        self.fail(FailureCode.SIZE,client)

    def test_empty_page_with_cursor_fails(self):
        client,adapter,_=self.client([response({"results":[],"next_url":ACTION+"&cursor=2"})])
        self.fail(FailureCode.RESPONSE,client)

    def test_aggregate_adjustment_and_coverage(self):
        body={"status":"OK","ticker":"XOM","adjusted":False,"resultsCount":2,
              "results":[{"t":1000,"c":100.25},{"t":2000,"c":101.25}]}
        client,adapter,_=self.client([response(body)])
        chain=client.fetch(AGGS)
        self.assertEqual((chain.observed_start,chain.observed_end),("1000","2000"))
        self.assertIn("adjusted=false",adapter.calls[0][0])
        for altered in [dict(body,adjusted=True),dict(body,adjusted=None),dict(body,ticker="XLE"),dict(body,resultsCount=3)]:
            client,_,_=self.client([response(altered)])
            self.fail(FailureCode.RESPONSE,client,AGGS)
        client,_,_=self.client([])
        self.fail(FailureCode.URL,client,AGGS.replace("adjusted=false","adjusted=true"))

    def test_open_close_and_reference_response_contracts(self):
        summary=HOST+"/v1/open-close/XLE/2026-01-02"
        client,_,_=self.client([response({"status":"OK","symbol":"XLE","adjusted":False,"from":"2026-01-02","open":90,"close":91})])
        self.assertEqual(client.fetch(summary).row_count,1)
        client,_,_=self.client([response({"status":"OK","results":{"ticker":"XOM","name":"Synthetic"}})])
        self.assertEqual(client.fetch(HOST+"/v3/reference/tickers/XOM").row_count,1)

    def test_raw_json_precision_and_secret_sanitation(self):
        raw=('{{"status":"OK","results":[{{"ticker":"XOM","ex_dividend_date":"2026-01-02",'
             '"cash_amount":0.123456789012,"note":"{key}","apiKey":"{key}"}}],'
             '"request_id":"{key}","authorization":"Bearer {key}"}}').format(key=SECRET).encode()
        client,adapter,_=self.client([response(raw=raw)])
        page=client.fetch(ACTION).pages[0]
        self.assertIn(b'0.123456789012',page.sanitized_body)
        self.assertNotIn(SECRET,repr(page))
        self.assertNotIn(SECRET,page.sanitized_body.decode())
        self.assertIsNone(page.request_id)
        self.assertEqual(page.body_hash,hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(page.body_hash,page.storage_hash)

    def test_nonfinite_duplicate_and_malformed_json_fail(self):
        for raw in [b'{"results":[],"results":[]}',b'{"results":[],"a":NaN}',b'not-json',b'[]']:
            client,adapter,_=self.client([response(raw=raw)])
            self.fail(FailureCode.RESPONSE,client)

class AdapterTests(unittest.TestCase):
    def test_tls_timeout_and_no_redirect_dispatch(self):
        class Socket:
            def settimeout(self,value): self.timeout=value
        class Incoming:
            status=302
            def getheaders(self): return [("Location","https://evil.invalid"),("Set-Cookie",SECRET)]
            def read1(self,maximum): return b""
        class Connection:
            def __init__(self,*args,**kwargs):
                self.sock=Socket()
                self.options=kwargs
                self.requests=[]
                self.closed=False
            def connect(self): pass
            def request(self,*args,**kwargs): self.requests.append((args,kwargs))
            def getresponse(self): return Incoming()
            def close(self): self.closed=True
        connections=[]
        def factory(*args,**kwargs):
            conn=Connection(*args,**kwargs)
            connections.append(conn)
            return conn
        with patch("drift_data.provider.http.http.client.HTTPSConnection",side_effect=factory):
            result=HTTPSAdapter().send(ACTION,{"Authorization":"Bearer "+SECRET},connect_timeout=5,read_timeout=30,max_bytes=100,budget=60)
        self.assertEqual(result.status,302)
        self.assertEqual(len(connections),1)
        self.assertEqual(connections[0].options["timeout"],5)
        self.assertTrue(connections[0].options["context"].check_hostname)
        self.assertEqual(connections[0].sock.timeout,30)
        self.assertTrue(connections[0].closed)
        self.assertEqual(result.headers,{})

    def test_content_length_truncation_oversize_and_network_failures_are_safe(self):
        class Socket:
            def settimeout(self,value): pass
        class Incoming:
            status=200
            def __init__(self,length,chunks): self.length,self.chunks=length,list(chunks)
            def getheaders(self): return [] if self.length is None else [("Content-Length",self.length)]
            def read1(self,maximum): return self.chunks.pop(0) if self.chunks else b""
        class Connection:
            def __init__(self,incoming): self.sock,self.incoming,self.closed=Socket(),incoming,False
            def connect(self): pass
            def request(self,*args,**kwargs): pass
            def getresponse(self): return self.incoming
            def close(self): self.closed=True
        for incoming,error in [(Incoming("10",[b"{}"]),ConnectionFailure),(Incoming("101",[]),ResponseTooLarge),(Incoming(None,[b"x"*101]),ResponseTooLarge)]:
            connection=Connection(incoming)
            with patch("drift_data.provider.http.http.client.HTTPSConnection",return_value=connection):
                with self.assertRaises(error):
                    HTTPSAdapter().send(ACTION,{},connect_timeout=5,read_timeout=30,max_bytes=100,budget=60)
            self.assertTrue(connection.closed)
        connection=Connection(None)
        connection.connect=lambda: (_ for _ in ()).throw(OSError(SECRET))
        with patch("drift_data.provider.http.http.client.HTTPSConnection",return_value=connection):
            with self.assertRaises(ConnectionFailure) as caught:
                HTTPSAdapter().send(ACTION,{},connect_timeout=5,read_timeout=30,max_bytes=100,budget=60)
        self.assertIsNone(caught.exception.__context__)
        self.assertNotIn(SECRET,str(caught.exception))
