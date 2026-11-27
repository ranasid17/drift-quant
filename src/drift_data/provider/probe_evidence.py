"""Pure feasibility evidence interpretation. No normalization or financial returns."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from .probe_calendar import milliseconds, diagnostics
from .probe_plan import ENDPOINTS, task
from .sanitize import RawNumber, decode

NY=ZoneInfo("America/New_York")
PRICE={"day","summary","minute"}


def positive(value):
    if not isinstance(value,RawNumber):
        return False
    try:
        number=Decimal(value)
        return number.is_finite() and 0<number<Decimal("1e16")
    except (InvalidOperation,ValueError):
        return False


def identity_details(symbol, value):
    kept={key:value.get(key) for key in ("ticker","type","active","currency_name","primary_exchange","locale","market","list_date","cik","composite_figi","share_class_figi")}
    expected={"XOM":("CS","XNYS"),"XLE":("ETF","ARCX")}[symbol]
    valid=(kept["ticker"]==symbol and (kept["type"],kept["primary_exchange"])==expected and kept["active"] is True
           and str(kept["currency_name"]).lower()=="usd" and kept["locale"]=="us" and kept["market"]=="stocks"
           and any(isinstance(kept[key],str) and kept[key] for key in ("cik","composite_figi","share_class_figi")))
    try:
        date.fromisoformat(kept["list_date"])
    except (ValueError,TypeError):
        valid=False
    return {"verified":bool(valid),"fields":kept,"historical_alias_continuity":"unverified"}


def interpret(item, chain, snapshot, as_of, probe_id, identity=None, calendar=None):
    endpoint=item["endpoint"]
    rows=[]
    refs=[]
    for page in chain.pages:
        payload=decode(page.sanitized_body)
        value=payload if endpoint=="summary" else payload["results"] if "results" in payload else []
        rows.extend(value if isinstance(value,list) else [value])
        refs.append({"snapshot_id":snapshot,"partition_id":"probe","page_index":page.page_index,
                     "json_pointer":"" if endpoint=="summary" or "results" not in payload else "/results","content_hash":page.storage_hash})
    observed=[]
    semantic=True
    for row in rows:
        try:
            if endpoint in {"day","minute"}:
                timestamp=int(row["t"])
                observed.append(datetime.fromtimestamp(timestamp/1000,timezone.utc).astimezone(NY).date().isoformat())
                semantic=semantic and all(positive(row.get(field)) for field in ("o","c","h","l"))
            elif endpoint=="summary":
                observed.append(date.fromisoformat(row["from"]).isoformat())
                semantic=semantic and positive(row.get("open")) and positive(row.get("close"))
            elif endpoint!="identity":
                field="ex_dividend_date" if endpoint.startswith("dividends") else "execution_date"
                observed.append(date.fromisoformat(row[field]).isoformat())
        except (KeyError,TypeError,ValueError,OverflowError,OSError):
            semantic=False
    in_bounds=all(item["start"]<=day<=item["end"] for day in observed)
    category="delayed" if any(page.provider_status=="DELAYED" for page in chain.pages) else "ok"
    if not rows:
        category="empty_no_events" if endpoint.split("-")[0] in {"dividends","splits"} else "empty_unexplained"
        if endpoint in PRICE and calendar is not None and not any(item["start"]<=session["date"]<=item["end"] for session in calendar["sessions"]):
            category="empty_closed_session_interval"
        listed=identity.get("fields",{}).get("list_date") if identity else None
        if isinstance(listed,str) and item["end"]<listed:
            category="empty_before_reported_listing"
    elif not semantic:
        category="response_values_unverified"
    elif not in_bounds:
        category="observations_outside_request"
    capability={"schema_version":1,"probe_id":probe_id,"instrument_id":item["symbol"],
                "endpoint_contract_id":item["contract"],"requested_start":item["start"],"requested_end":item["end"],
                "as_of":as_of,"http_status":chain.pages[-1].http_status,"status_category":category,
                "observed_start":min(observed) if observed else None,"observed_end":max(observed) if observed else None,
                "row_count":chain.row_count,"pagination_complete":True,"access_state":"allowed",
                "boundary_precision":"observations_only","source_refs":refs}
    detail={"task":item,"capability":capability,"snapshot_id":snapshot,"semantic_valid":bool(semantic and in_bounds),
            "schema_observed":sorted(set().union(*(row.keys() for row in rows))) if rows else [],
            "request_ids":[p.request_id for p in chain.pages if p.request_id],"historical_availability":"unknown"}
    if endpoint=="identity" and rows:
        detail["identity"]=identity_details(item["symbol"],rows[0])
    if endpoint=="summary" and rows:
        detail["prices"]={"open":str(rows[0].get("open")),"close":str(rows[0].get("close")),"print_time":None}
    if endpoint=="minute":
        lower,upper=milliseconds(item["session"]["open"]),milliseconds(item["session"]["close"])
        times=[int(row["t"]) for row in rows if isinstance(row.get("t"),RawNumber)]
        by_time={int(row["t"]):row for row in rows if isinstance(row.get("t"),RawNumber)}
        good=bool(rows) and semantic and len(times)==len(rows)==len(set(times)) and all(lower<=value<upper and (value-lower)%60000==0 for value in times)
        boundary=lower in by_time and upper-60000 in by_time
        detail["minute_diagnostic"]={"boundary_bars_present":boundary,"timestamps_valid":bool(good),
              "expected_minutes":(upper-lower)//60000,"observed_minutes":len(times),
              "missing_minutes":sorted(set(range(lower,upper,60000))-set(times)),
              "first_interval_start":min(times) if times else None,"last_interval_start":max(times) if times else None,
              "open":str(by_time[lower]["o"]) if good and boundary else None,
              "close":str(by_time[upper-60000]["c"]) if good and boundary else None,"print_time":None}
    return detail


def failure(item, error, snapshot, as_of, probe_id):
    refs=[{"snapshot_id":snapshot,"partition_id":"probe","page_index":p.page_index,"json_pointer":"",
           "content_hash":p.storage_hash} for p in error.completed_pages]
    return {"task":item,"snapshot_id":snapshot,"semantic_valid":False,
      "failure":{"code":error.code.value,"http_status":error.http_status,"attempts":error.attempts,"body_hash":error.body_hash},
      "capability":{"schema_version":1,"probe_id":probe_id,"instrument_id":item["symbol"],
      "endpoint_contract_id":item["contract"],"requested_start":item["start"],"requested_end":item["end"],"as_of":as_of,
      "http_status":error.http_status,"status_category":error.code.value,"observed_start":None,"observed_end":None,
      "row_count":sum(p.row_count for p in error.completed_pages),"pagination_complete":False,
      "access_state":"denied" if error.code.value=="entitlement_denied" else "unknown",
      "boundary_precision":"unresolved","source_refs":refs}}


def boundaries(results, calendar):
    days=[s["date"] for s in calendar["sessions"]]
    output=[]
    for symbol in ("XOM","XLE"):
        for endpoint,contract in ENDPOINTS.items():
            subset=[r for r in results if r["task"]["symbol"]==symbol and r["task"]["endpoint"]==endpoint]
            good=[r for r in subset if r["capability"]["row_count"] and r.get("semantic_valid") and r["capability"]["status_category"] in {"ok","delayed"}]
            observed=[r["capability"]["observed_start"] for r in good if r["capability"]["observed_start"]]
            latest=[r["capability"]["observed_end"] for r in good if r["capability"]["observed_end"]]
            oldest=min((r["task"]["start"] for r in good),default=None)
            denied=max((r["task"]["end"] for r in subset if r["capability"]["status_category"]=="entitlement_denied" and oldest and r["task"]["end"]<oldest),default=None)
            precision="unresolved"
            if endpoint in PRICE and oldest:
                if oldest==days[0]:
                    precision="documented_provider_floor_observed"
                elif denied in days and oldest in days and days.index(oldest)-days.index(denied)==1:
                    precision="adjacent_tested_sessions"
            output.append({"symbol":symbol,"endpoint":endpoint,"contract":contract,"oldest_observed":min(observed) if observed else None,
                           "newest_observed":max(latest) if latest else None,"oldest_successful_query":oldest,
                           "latest_explicit_denied_query":denied,"boundary_precision":precision,"boundary_unresolved":precision=="unresolved"})
    return output


def refinement_tasks(results, calendar, planned):
    days=[s["date"] for s in calendar["sessions"]]
    seen={(t["symbol"],t["endpoint"],t["start"],t["end"]) for t in planned}
    additions=[]
    for bound in boundaries(results,calendar):
        if bound["endpoint"] not in PRICE or bound["boundary_precision"]!="unresolved":
            continue
        denied,working=bound["latest_explicit_denied_query"],bound["oldest_successful_query"]
        if denied in days and working in days and days.index(working)-days.index(denied)>1:
            index=(days.index(working)+days.index(denied))//2
            item=task(bound["symbol"],bound["endpoint"],calendar["sessions"][index],label="boundary-refinement")
            key=(item["symbol"],item["endpoint"],item["start"],item["end"])
            if key not in seen:
                additions.append(item)
    return additions


def method_contract(results, calendar):
    identities={r["task"]["symbol"]:r["identity"] for r in results if "identity" in r}
    required={s["date"] for s in diagnostics(calendar).values()}
    checks=[]
    blockers=[]
    for symbol in ("XOM","XLE"):
        if not identities.get(symbol,{}).get("verified"):
            blockers.append(symbol+":identity_unverified")
        for day in sorted(required):
            minute=next((r for r in results if r["task"]["symbol"]==symbol and r["task"]["endpoint"]=="minute" and r["task"]["start"]==day),None)
            summary=next((r for r in results if r["task"]["symbol"]==symbol and r["task"]["endpoint"]=="summary" and r["task"]["start"]==day),None)
            diag=minute.get("minute_diagnostic",{}) if minute else {}
            verified=diag.get("timestamps_valid",False) and diag.get("boundary_bars_present",False)
            matches=None
            if verified and summary and summary.get("semantic_valid") and "prices" in summary:
                matches=all(abs(Decimal(diag[k])-Decimal(summary["prices"][k]))<=Decimal("0.000001") for k in ("open","close"))
                if not matches:
                    blockers.append(symbol+":"+day+":summary_minute_disagreement")
            if not verified:
                blockers.append(symbol+":"+day+":minute_boundary_unverified")
            checks.append({"symbol":symbol,"session":day,"minute_boundary_verified":bool(verified),"summary_matches_minute":matches})
    return {"version":"regular-session-method-v1","status":"blocked" if blockers else "candidate_verified",
            "selected_method":None if blockers else "unadjusted_scheduled_boundary_minute_proxy",
            "daily_summary_regular_session_semantics_verified":False,
            "daily_summary_reason":"documentation does not unambiguously define auction/session print semantics",
            "minute_interval":"[scheduled_open, scheduled_close)","requires_first_and_last_scheduled_minute":True,
            "exact_print_times":None,"historical_availability":"unknown","checks":checks,"blockers":sorted(set(blockers)),
            "scope":"diagnostic samples only; full history and action continuity require later ingestion/audit"}
