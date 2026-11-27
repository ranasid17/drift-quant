"""D2 tests use a synthetic provider, fake monotonic time and real frozen schedules."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs

from drift_data.config import Config
from drift_data.provider.auth import Credential
from drift_data.provider.doctor import run, BudgetedAdapter
from drift_data.provider.errors import FailureCode, ProviderError
from drift_data.provider.probe_calendar import freeze,diagnostics,milliseconds
from drift_data.provider.probe_plan import plan,task,url_for
from drift_data.provider.probe_evidence import boundaries,refinement_tasks,interpret,method_contract
from drift_data.provider.transport import Transport,Policy
from drift_data.storage.store import Store,StorageError,canonical,digest,_seal
import test_transport as transport_fixtures

ASOF=datetime(2026,11,28,tzinfo=timezone.utc)
SECRET=transport_fixtures.SECRET

class Provider:
    def __init__(self, status=None):
        self.calls=[]
        self.status=status

    def send(self,url,headers,**options):
        self.calls.append((url,headers,options))
        if self.status:
            return transport_fixtures.response({"status":"ERROR","message":SECRET},status=self.status)
        path=urlsplit(url).path
        query=parse_qs(urlsplit(url).query)
        if "/reference/tickers/" in path:
            symbol=path.rsplit("/",1)[1]
            return transport_fixtures.response({"status":"OK","results":{"ticker":symbol,"active":True,"type":"CS" if symbol=="XOM" else "ETF",
                "primary_exchange":"XNYS" if symbol=="XOM" else "ARCX","locale":"us","market":"stocks","currency_name":"usd",
                "list_date":"1960-01-01" if symbol=="XOM" else "1998-12-16","composite_figi":"SYNTHETIC"}})
        if "/open-close/" in path:
            symbol,day=path.split("/")[-2:]
            return transport_fixtures.response({"status":"OK","symbol":symbol,"from":day,"open":1,"close":2})
        if "/aggs/" in path:
            symbol=path.split("/")[4]
            lower,upper=path.split("/")[-2:]
            if "/minute/" in path:
                times=[int(lower),int(upper)+1-60000]
            else:
                times=[int(datetime.fromisoformat(lower).replace(hour=14,minute=30,tzinfo=timezone.utc).timestamp()*1000)]
            return transport_fixtures.response({"status":"OK","ticker":symbol,"adjusted":False,"results":[{"t":stamp,"o":1,"h":2,"l":1,"c":2,"v":10} for stamp in times]})
        return transport_fixtures.response({"status":"OK","results":[]})

class CalendarTests(unittest.TestCase):
    def test_completed_session_holiday_and_early_close(self):
        calendar=freeze(datetime(2026,11,27,17,tzinfo=timezone.utc))
        self.assertEqual(calendar["sessions"][-1]["date"],"2026-11-25")
        after=freeze(datetime(2026,11,27,19,tzinfo=timezone.utc))
        self.assertEqual(after["sessions"][-1]["close"],"2026-11-27T18:00:00+00:00")
        self.assertFalse(any(s["date"]=="2026-11-26" for s in calendar["sessions"]))

    def test_diagnostics_freeze_dst_and_normal_session(self):
        calendar=freeze(ASOF)
        diag=diagnostics(calendar)
        self.assertEqual(set(diag),{"ordinary","dst_before","dst_after","early_close"})
        self.assertNotEqual(diag["dst_before"]["open"][11:16],diag["dst_after"]["open"][11:16])
        self.assertEqual(milliseconds(diag["ordinary"]["close"])-milliseconds(diag["ordinary"]["open"]),390*60000)
        self.assertEqual(milliseconds(diag["early_close"]["close"])-milliseconds(diag["early_close"]["open"]),210*60000)

class DoctorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar=freeze(ASOF)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.config=Config(1,("XOM","XLE"),"USD",root/"data",root/"reports")
        self.clock=transport_fixtures.FakeTime()
        self.provider=Provider()

    def invoke(self, tasks=None, **options):
        with patch("drift_data.provider.doctor.freeze",return_value=self.calendar):
            with patch("drift_data.provider.doctor.plan",return_value=tasks if tasks is not None else plan(self.calendar)):
                return run(self.config,online=True,credential=Credential(SECRET),adapter=self.provider,
                           clock=self.clock.clock,sleep=self.clock.sleep,now=ASOF,**options)

    def test_without_online_no_files_or_dispatch(self):
        with self.assertRaises(ProviderError): run(self.config)
        self.assertFalse(self.config.data_root.exists())
        self.assertEqual(self.provider.calls,[])

    def test_missing_credential_is_pending_without_network(self):
        with patch("drift_data.provider.doctor.freeze",return_value=self.calendar), patch("drift_data.provider.doctor.resolve_credential",side_effect=ProviderError(FailureCode.CREDENTIAL)):
            result=run(self.config,online=True,now=ASOF,adapter=self.provider)
        self.assertEqual(result["status"],"credentials_unavailable")
        self.assertFalse(result["credential_present"])
        self.assertEqual(self.provider.calls,[])

    def test_limit_validation_precedes_requests(self):
        for maximum in (0,81,True):
            with self.assertRaises(ValueError): self.invoke(max_attempts=maximum)
        self.assertEqual(self.provider.calls,[])

    def test_authentication_failure_stops_globally_and_is_resumable(self):
        self.provider=Provider(401)
        result=self.invoke()
        self.assertEqual(result["status"],"authentication_failed")
        self.assertEqual(result["completed_tasks"],0)
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(result["authentication_result"],"failed")

    def test_403_is_unknown_denial_without_invented_boundary(self):
        self.provider=Provider(403)
        result=self.invoke(tasks=plan(self.calendar)[:2])
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(result["rows"][0]["status_category"],"access_denied_unknown")
        self.assertTrue(all(b["boundary_unresolved"] for b in result["boundaries"]))

    def test_retries_count_toward_invocation_budget(self):
        self.provider=Provider(503)
        result=self.invoke(max_attempts=3)
        self.assertEqual(len(self.provider.calls),3)
        self.assertEqual(result["status"],"attempt_budget_exhausted")
        self.assertEqual(result["completed_tasks"],0)
        self.assertEqual(result["invocations"][0]["attempts_reserved"],3)

    def test_budget_continuation_skips_finished_tasks_and_keeps_asof(self):
        result=self.invoke(max_attempts=2)
        probe=result["probe_id"]
        initial_urls=[call[0] for call in self.provider.calls]
        continued=self.invoke(resume=probe,max_attempts=2)
        self.assertEqual(continued["as_of"],result["as_of"])
        self.assertEqual(continued["completed_tasks"],4)
        self.assertEqual(continued["attempts_total"],4)
        self.assertEqual(len(continued["invocations"]),2)
        self.assertTrue(all(url not in initial_urls for url,_,_ in self.provider.calls[2:]))

    def test_deadline_stops_without_dispatching_after_wait(self):
        result=self.invoke(deadline_seconds=5)
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(result["status"],"deadline_exceeded")

    def test_report_redaction_and_raw_provenance(self):
        result=self.invoke(max_attempts=2)
        for path in self.config.reports_root.rglob("*"):
            if path.is_file(): self.assertNotIn(SECRET,path.read_text())
        for row in result["rows"]:
            for ref in row["source_refs"]:
                store=Store(self.config.data_root)
                value=store.read_pointer(ref["snapshot_id"],ref["partition_id"],ref["page_index"],ref["json_pointer"])
                self.assertIn(value["ticker"],("XOM","XLE"))

    def test_empty_actions_do_not_establish_entitlement_start(self):
        item=task("XOM","dividends",self.calendar["sessions"][-1],start="2026-08-01")
        result=self.invoke(tasks=[item])
        self.assertEqual(result["rows"][0]["status_category"],"empty_no_events")
        bound=next(b for b in result["boundaries"] if b["symbol"]=="XOM" and b["endpoint"]=="dividends")
        self.assertIsNone(bound["oldest_observed"])
        self.assertTrue(bound["boundary_unresolved"])

    def test_legacy_and_hosts_are_explicit(self):
        tasks=plan(self.calendar)
        self.assertFalse(any(t["endpoint"].endswith("-legacy") for t in tasks))
        self.assertTrue(any(t["endpoint"].endswith("-legacy") for t in plan(self.calendar,legacy=True)))
        result=self.invoke(tasks=tasks[:2],host="api.massive.com")
        self.assertEqual(result["completed_tasks"],2)
        self.assertTrue(all(urlsplit(url).hostname=="api.massive.com" for url,_,_ in self.provider.calls))
        with self.assertRaises(StorageError): self.invoke(resume=result["probe_id"],host="api.polygon.io")

    def test_complete_probe_does_not_refetch_and_identifies_minute_candidate(self):
        result=self.invoke(max_attempts=80)
        if result["status"]!="complete":
            result=self.invoke(resume=result["probe_id"],max_attempts=80)
        self.assertEqual(result["status"],"complete")
        self.assertTrue(all(identity["verified"] for identity in result["identities"].values()))
        self.assertEqual(result["method"]["status"],"candidate_verified")
        self.assertFalse(result["method"]["daily_summary_regular_session_semantics_verified"])
        count=len(self.provider.calls)
        self.invoke(resume=result["probe_id"])
        self.assertEqual(len(self.provider.calls),count)

    def test_state_tampering_rejected_without_request(self):
        result=self.invoke(max_attempts=1)
        path=self.config.data_root/"probes"/result["probe_id"]/"state.json"
        state=json.loads(path.read_text())
        state["cursor"]=50
        path.write_text(json.dumps(state))
        count=len(self.provider.calls)
        with self.assertRaises(StorageError): self.invoke(resume=result["probe_id"])
        self.assertEqual(len(self.provider.calls),count)

    def test_refinement_requires_explicit_entitlement_denial(self):
        dates=self.calendar["sessions"][-5:]
        def record(index,category,good):
            item=task("XOM","day",dates[index])
            return {"task":item,"semantic_valid":good,"capability":{"status_category":category,"row_count":int(good),
              "observed_start":item["start"] if good else None,"observed_end":item["end"] if good else None}}
        results=[record(0,"entitlement_denied",False),record(4,"ok",True)]
        planned=[r["task"] for r in results]
        additions=refinement_tasks(results,self.calendar,planned)
        self.assertEqual(len(additions),1)
        self.assertEqual(additions[0]["start"],dates[2]["date"])
        results[0]["capability"]["status_category"]="access_denied_unknown"
        self.assertEqual(refinement_tasks(results,self.calendar,planned),[])

    def test_missing_boundary_bar_blocks_method(self):
        result=self.invoke(max_attempts=80)
        if result["status"]!="complete": result=self.invoke(resume=result["probe_id"])
        state=json.loads((self.config.data_root/"probes"/result["probe_id"]/"state.json").read_text())
        entry=next(r for r in state["results"] if r["task"]["endpoint"]=="minute" and r["task"]["label"]=="dst_before")
        entry["minute_diagnostic"]["boundary_bars_present"]=False
        method=method_contract(state["results"],self.calendar)
        self.assertEqual(method["status"],"blocked")

    def test_plan_has_unique_capability_primary_keys(self):
        tasks=plan(self.calendar,legacy=True)
        keys=[(t["symbol"],t["contract"],t["start"],t["end"]) for t in tasks]
        self.assertEqual(len(keys),len(set(keys)))

    def test_pagination_counts_toward_global_budget_and_retains_partial_evidence(self):
        class Pages:
            def __init__(self): self.calls=[]
            def send(self,url,headers,**options):
                self.calls.append(url)
                current=len(self.calls)
                return transport_fixtures.response({"results":[transport_fixtures.cash(date="2026-11-27")],
                    "next_url":"https://api.polygon.io/stocks/v1/dividends?ticker=XOM&cursor="+str(current)})
        self.provider=Pages()
        item=task("XOM","dividends",self.calendar["sessions"][-1])
        result=self.invoke(tasks=[item],max_attempts=3)
        self.assertEqual(len(self.provider.calls),3)
        self.assertEqual(result["status"],"attempt_budget_exhausted")
        self.assertFalse(result["rows"][0]["pagination_complete"])
        self.assertEqual(result["rows"][0]["row_count"],3)
        self.assertEqual(len(result["rows"][0]["source_refs"]),3)

    def test_corrupt_completed_evidence_blocks_continuation_without_fetch(self):
        result=self.invoke(max_attempts=2)
        ref=result["rows"][0]["source_refs"][0]
        page=next((self.config.data_root/"raw"/ref["snapshot_id"]).glob("probe--*/page-000001.json.gz"))
        page.write_bytes(b"corrupt")
        count=len(self.provider.calls)
        with self.assertRaises(StorageError): self.invoke(resume=result["probe_id"])
        self.assertEqual(len(self.provider.calls),count)

    def test_minute_request_ends_before_scheduled_close(self):
        session=diagnostics(self.calendar)["early_close"]
        path=urlsplit(url_for(task("XLE","minute",session),"api.polygon.io")).path
        self.assertEqual(int(path.rsplit("/",1)[1]),milliseconds(session["close"])-1)
