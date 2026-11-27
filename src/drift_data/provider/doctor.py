"""Explicit-online bounded feasibility probes with durable evidence and continuation."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from importlib.metadata import version
import re
import tempfile
import time
import uuid

from drift_data.schemas import validate_row
from drift_data.storage.store import Store, StorageError, canonical, digest, _seal, _verify_manifest, _sync_dir
from .auth import resolve_credential
from .errors import FailureCode, ProviderError
from .http import HTTPSAdapter
from .transport import Transport, Policy, HOSTS
from .probe_calendar import freeze
from .probe_plan import VERSION, ENDPOINTS, DOCS, plan, url_for
from .probe_evidence import interpret, failure, boundaries, refinement_tasks, method_contract


def atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        temporary=None
        _sync_dir(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def implementation_hash():
    names=("doctor.py","probe_plan.py","probe_calendar.py","probe_evidence.py","transport.py")
    dependencies=canonical({name:version(name) for name in ("exchange-calendars","pandas","numpy","tzdata")})
    return digest(dependencies+b"".join((Path(__file__).parent/name).read_bytes() for name in names))


class BudgetedAdapter:
    """Count and persist a reservation before each dispatch, including retries."""
    def __init__(self, adapter, state, maximum, deadline, persist, clock):
        self.adapter,self.state,self.maximum,self.deadline=adapter,state,maximum,deadline
        self.persist,self.clock,self.used=persist,clock,0

    def send(self, url, headers, **options):
        if self.used>=self.maximum:
            raise ProviderError(FailureCode.BUDGET)
        remaining=self.deadline-self.clock()
        if remaining<=0:
            raise ProviderError(FailureCode.DEADLINE)
        self.used+=1
        self.state["attempts_total"]+=1
        self.state["last_dispatch_utc"]=datetime.now(timezone.utc).isoformat()
        self.state["invocations"][-1]["attempts_reserved"]=self.used
        try:
            self.persist()
        except OSError:
            raise StorageError("Request reservation could not be persisted") from None
        options["budget"]=min(options["budget"],remaining)
        return self.adapter.send(url,headers,**options)


def _contracts(state):
    contracts=[]
    paths={"identity":"/v3/reference/tickers/{ticker}","day":"/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}",
           "minute":"/v2/aggs/ticker/{ticker}/range/1/minute/{open_ms}/{close_ms_minus_one}",
           "summary":"/v1/open-close/{ticker}/{date}","dividends":"/stocks/v1/dividends","splits":"/stocks/v1/splits",
           "dividends-legacy":"/v3/reference/dividends","splits-legacy":"/v3/reference/splits"}
    for endpoint,identifier in ENDPOINTS.items():
        results=[r for r in state["results"] if r["task"]["endpoint"]==endpoint]
        contracts.append({"id":identifier,"host":state["host"],"endpoint":endpoint,
                          "docs_url":DOCS[endpoint.split("-")[0]],"docs_reviewed":"2026-11-27", "path_template":paths[endpoint],
                          "query_policy":"explicit adjusted=false; ascending; one session" if endpoint in {"day","minute","summary"} else "symbol/date filtered; no recurring-only filter; full returned fields",
                          "minute_timestamp_semantics":"bar start; [scheduled_open,scheduled_close)" if endpoint=="minute" else None,
                          "original_cash_field":"cash_amount" if endpoint.startswith("dividends") else None,
                          "restated_cash_field":"split_adjusted_cash_amount" if endpoint=="dividends" else None,
                          "event_share_ratio":"split_to / split_from" if endpoint.startswith("splits") else None,
                          "cumulative_factor_is_event_ratio":False,
                          "explicit_legacy":endpoint.endswith("-legacy"),
                          "observed_response_fields":sorted(set().union(*(set(r.get("schema_observed",[])) for r in results))),
                          "successful_probe_count":sum(r["capability"]["access_state"]=="allowed" for r in results),
                          "units":"event cash_amount/original shares; split_to / split_from; cumulative factors not event ratios" if endpoint.split("-")[0] in {"splits","dividends"} else "instrument identity, currency and listing metadata" if endpoint=="identity" else "unadjusted observed price; not a promised fill"})
    return {"version":VERSION,"contracts":contracts,"method":method_contract(state["results"],state["calendar"])}


def render(state, reports_root):
    outcomes=list(state["results"])
    if state.get("pending_result"):
        outcomes.append(state["pending_result"])
    rows=[r["capability"] for r in outcomes]
    for row in rows:
        validate_row("capabilities",row)
    bound=boundaries(state["results"],state["calendar"])
    contracts=_contracts(state)
    continuation=None if state["status"]=="complete" else {"probe_id":state["probe_id"],"next_task":state["cursor"],"restart_incomplete_chain":True}
    capabilities={"schema_version":1,"probe_id":state["probe_id"],"as_of":state["as_of"],"implementation_hash":state["implementation_hash"],
       "resolved_calendar_end":state["calendar"]["sessions"][-1]["date"],"status":state["status"],
       "credential_present":state["credential_present"],"authentication_result":state["authentication_result"],
       "attempts_total":state["attempts_total"],"invocations":state["invocations"],"rows":rows,
       "boundaries":bound,"identities":{r["task"]["symbol"]:r["identity"] for r in state["results"] if "identity" in r},
       "method":contracts["method"],"continuation":continuation,
       "requested_tasks":len(state["tasks"]),"completed_tasks":state["cursor"],
       "probe_execution_complete":state["status"]=="complete","foundation_ready":False,
       "interrupted_snapshots":state["interrupted_snapshots"],
       "limitations":["Point probes do not prove contiguous intervening history.",
         "Empty actions never establish an oldest entitlement date or independent vendor completeness.",
         "Historical alias continuity, causal availability and provider finality remain unverified.",
         "Full-history ingestion, action classification and quality acceptance are later packets."]}
    target=Path(reports_root)/"probes"/state["probe_id"]
    atomic(target/"capabilities.json",canonical(capabilities))
    atomic(target/"endpoint_contracts.json",canonical(contracts))
    lines=["# Data feasibility — XOM / XLE", "",f"Probe: {state['probe_id']}",f"Captured UTC as-of: {state['as_of']}",
           f"Status: {state['status']}; completed tasks {state['cursor']}/{len(state['tasks'])}; reserved HTTP attempts {state['attempts_total']}.",
           "", "This is sampled subscription evidence, not complete ingestion or model readiness.","",
           "| Symbol | Endpoint | Oldest observation | Newest observation | Boundary |", "| --- | --- | --- | --- | --- |"]
    for item in bound:
        lines.append(f"| {item['symbol']} | {item['endpoint']} | {item['oldest_observed'] or 'unknown'} | {item['newest_observed'] or 'unknown'} | {item['boundary_precision']} |")
    lines.extend(["",f"Session method: {contracts['method']['status']}.",
                  "Daily summary semantics remain unverified; minute candidates require scheduled boundary bars and diagnostics.",
                  "Exact print times and historical causal availability remain unknown.","", "## Blockers"])
    lines.extend("- "+value for value in contracts["method"]["blockers"])
    if continuation:
        lines.append("- Continuation required: rerun doctor with --online --resume "+state["probe_id"]+" and the same config.")
    lines.extend(["", "## Evidence", "", "capabilities.json contains schema-validated per-query rows and raw snapshot/page/JSON-pointer references.",
                  "Successful snapshots are cataloged; failed requests retain incomplete journals and typed failure evidence.",
                  "No plan tier or contiguous coverage is inferred. No alternate provider, bulk download or paid upgrade is used.",
                  "", "## Public contracts", ""])
    lines.extend("- "+url for url in sorted(set(DOCS.values())))
    atomic(target/"DATA_FEASIBILITY.md",("\n".join(lines)+"\n").encode())
    return capabilities


def run(config, *, online=False, host=None, as_of=None, resume=None, credentials_file=None,
        credential=None, max_attempts=80, deadline_seconds=1200, legacy=False,
        adapter=None, clock=time.monotonic, sleep=time.sleep, now=None):
    if online is not True:
        raise ProviderError(FailureCode.OFFLINE)
    if type(max_attempts) is not int or not 1<=max_attempts<=80 or type(deadline_seconds) not in (int,float) or not 1<=deadline_seconds<=3600:
        raise ValueError("Invalid doctor limits")
    if host is not None and host not in HOSTS:
        raise ValueError("Invalid doctor host")
    started=now or datetime.now(timezone.utc)
    if started.tzinfo is None:
        raise ValueError("UTC clock required")
    store=Store(config.data_root)
    # The whole invocation holds one lock, including state updates and transport.
    if resume:
        if re.fullmatch(r"[0-9a-f]{32}",resume) is None:
            raise StorageError("Invalid probe identifier")
        probe_id=resume
    else:
        probe_id=uuid.uuid4().hex
    state_path=config.data_root/"probes"/probe_id/"state.json"
    with store._lock("doctor","invocation"), store._lock("doctor",probe_id):
        if resume:
            try:
                state=_verify_manifest(json.loads(state_path.read_bytes()))
            except (OSError,ValueError,TypeError):
                raise StorageError("Probe state unavailable") from None
            state.pop("manifest_hash",None)
            try:
                calendar_copy=_verify_manifest(json.loads((state_path.parent/"calendar.json").read_bytes()))
                calendar_copy.pop("manifest_hash",None)
            except (OSError,ValueError,TypeError):
                raise StorageError("Frozen probe calendar unavailable") from None
            if calendar_copy!=state["calendar"]:
                raise StorageError("Frozen probe calendar mismatch")
            for outcome in state["results"]:
                if outcome["capability"]["access_state"]=="allowed":
                    store.read_snapshot(outcome["snapshot_id"])
            if state["probe_id"]!=probe_id or state["version"]!=VERSION or state["implementation_hash"]!=implementation_hash() or (host and host!=state["host"]) or legacy!=state["legacy"]:
                raise StorageError("Probe continuation configuration mismatch")
            if as_of and as_of.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")!=state["as_of"]:
                raise StorageError("Probe continuation as-of mismatch")
            if state["status"]=="complete":
                return render(state,config.reports_root)
            if state.get("active_snapshot"):
                state["interrupted_snapshots"].append(state["active_snapshot"])
                state["active_snapshot"]=None
        else:
            captured=as_of or started
            if captured.tzinfo is None or captured>started:
                raise ValueError("Invalid as-of instant")
            calendar=freeze(captured)
            state={"version":VERSION,"probe_id":probe_id,"implementation_hash":implementation_hash(),
               "symbols":["XOM","XLE"],"currency":"USD","host":host or "api.polygon.io","legacy":legacy,
               "as_of":captured.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z"),
               "calendar":calendar,"tasks":plan(calendar,legacy=legacy),"cursor":0,"results":[],"pending_result":None,
               "active_snapshot":None,"interrupted_snapshots":[],"attempts_total":0,"invocations":[],
               "credential_present":False,"authentication_result":"unknown","status":"initialized"}
            atomic(state_path.parent/"calendar.json",canonical(_seal(calendar)))
        def persist():
            atomic(state_path,canonical(_seal(state)))
        state["invocations"].append({"started_at":started.astimezone(timezone.utc).isoformat(),"max_attempts":max_attempts,"attempts_reserved":0})
        state["status"]="running"
        persist()
        try:
            key=credential if credential is not None else resolve_credential(credentials_file=credentials_file)
        except ProviderError:
            state["status"]="credentials_unavailable"
            state["credential_present"]=False
            state["invocations"][-1]["stop_reason"]=state["status"]
            persist()
            return render(state,config.reports_root)
        state["credential_present"]=True
        budget=BudgetedAdapter(adapter if adapter is not None else HTTPSAdapter(),state,max_attempts,clock()+deadline_seconds,persist,clock)
        transport=Transport(key,online=True,adapter=budget,policy=Policy(allowed_hosts=(state["host"],),max_pages=10,max_total_bytes=10*1024*1024),
                            clock=clock,sleep=sleep,wall_clock=lambda: datetime.now(timezone.utc))
        if state.get("last_dispatch_utc"):
            last=datetime.fromisoformat(state["last_dispatch_utc"])
            if last.tzinfo is None:
                raise StorageError("Invalid dispatch timestamp")
            gap=max(0.0,12-(datetime.now(timezone.utc)-last).total_seconds())
            transport._next_allowed=clock()+gap
        try:
            while True:
                if state["cursor"]>=len(state["tasks"]):
                    extra=refinement_tasks(state["results"],state["calendar"],state["tasks"])
                    if not extra:
                        state["status"]="complete"
                        break
                    state["tasks"].extend(extra)
                if budget.used>=max_attempts or clock()>=budget.deadline:
                    state["status"]="attempt_budget_exhausted" if budget.used>=max_attempts else "deadline_exceeded"
                    break
                item=state["tasks"][state["cursor"]]
                config_hash=digest(canonical({"version":VERSION,"calendar_hash":digest(canonical(state["calendar"])),
                                            "host":state["host"],"as_of":state["as_of"],"task":item}))
                snapshot=store.begin_snapshot(config_hash,["probe"])
                state["active_snapshot"]=snapshot
                state["pending_result"]=None
                persist()
                transport.policy=replace(transport.policy,deadline_seconds=max(.001,min(300,budget.deadline-clock())))
                try:
                    _,chain=store.acquire_partition(snapshot,config_hash,"probe",transport,url_for(item,state["host"]),online=True)
                    store.publish_snapshot(snapshot,config_hash)
                except ProviderError as error:
                    outcome=failure(item,error,snapshot,state["as_of"],probe_id)
                    if error.code in {FailureCode.BUDGET,FailureCode.DEADLINE,FailureCode.AUTH}:
                        state["pending_result"]=outcome
                        state["status"]=error.code.value
                        if error.code==FailureCode.AUTH:
                            state["authentication_result"]="failed"
                        break
                else:
                    identity=next((r["identity"] for r in state["results"] if r["task"]["symbol"]==item["symbol"] and "identity" in r),None)
                    outcome=interpret(item,chain,snapshot,state["as_of"],probe_id,identity,state["calendar"])
                    state["authentication_result"]="confirmed"
                state["results"].append(outcome)
                state["cursor"]+=1
                state["active_snapshot"]=None
                persist()
                render(state,config.reports_root)
        except KeyboardInterrupt:
            state["status"]="interrupted"
        state["invocations"][-1]["stop_reason"]=state["status"]
        persist()
        return render(state,config.reports_root)
