"""Deterministic XOM/XLE endpoint probes, with no credential-bearing URLs."""
from datetime import date, timedelta
from urllib.parse import urlencode
from .probe_calendar import latest_before, diagnostics, milliseconds

VERSION="polygon-probes-v1"
ENDPOINTS={"identity":"ticker-reference-v3","day":"aggregates-day-v2",
           "summary":"open-close-v1","minute":"aggregates-minute-v2",
           "dividends":"dividends-v1","splits":"splits-v1",
           "dividends-legacy":"dividends-v3-explicit","splits-legacy":"splits-v3-explicit"}
DOCS={"identity":"https://massive.com/docs/rest/stocks/tickers/ticker-overview",
      "day":"https://massive.com/docs/rest/stocks/aggregates/custom-bars",
      "minute":"https://massive.com/knowledge-base/article/does-massive-offer-pre-market-and-after-hours-data",
      "summary":"https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary",
      "dividends":"https://massive.com/docs/rest/stocks/corporate-actions/dividends",
      "splits":"https://massive.com/docs/rest/stocks/corporate-actions/splits"}


def task(symbol, endpoint, session, *, label="history", start=None, end=None):
    day=session["date"]
    return {"symbol":symbol,"endpoint":endpoint,"contract":ENDPOINTS[endpoint],"label":label,
            "start":start or day,"end":end or day,"session":session}


def plan(calendar, *, legacy=False):
    recent=calendar["sessions"][-1]
    year,month,day=map(int,recent["date"].split("-"))
    tasks=[task(symbol,"identity",recent,label="identity") for symbol in ("XOM","XLE")]
    for age in (0,2,5,10,20):
        target=date(year-age,month,min(day,28)).isoformat() if age else recent["date"]
        session=latest_before(calendar,max(target,calendar["sessions"][0]["date"]))
        for symbol in ("XOM","XLE"):
            for endpoint in ("day","summary","minute","dividends","splits"):
                start=(date.fromisoformat(session["date"])-timedelta(days=90)).isoformat() if endpoint in {"dividends","splits"} else session["date"]
                tasks.append(task(symbol,endpoint,session,label=f"history-{age}y",start=start))
            if legacy:
                for endpoint in ("dividends-legacy","splits-legacy"):
                    tasks.append(task(symbol,endpoint,session,label=f"legacy-{age}y",start=(date.fromisoformat(session["date"])-timedelta(days=90)).isoformat()))
    for label,session in diagnostics(calendar).items():
        if label=="ordinary" and session["date"]==recent["date"]:
            continue
        for symbol in ("XOM","XLE"):
            for endpoint in ("day","summary","minute"):
                tasks.append(task(symbol,endpoint,session,label=label))
    earliest=calendar["sessions"][0]
    for symbol in ("XOM","XLE"):
        for endpoint in ("day","summary","minute"):
            tasks.append(task(symbol,endpoint,earliest,label="documented-price-floor"))
        tasks.append(task(symbol,"dividends",earliest,label="documented-action-floor",start="2000-01-15",end="2000-04-15"))
        tasks.append(task(symbol,"splits",earliest,label="documented-action-floor",start="1978-10-25",end="1979-01-25"))
    unique={}
    for item in tasks:
        unique.setdefault((item["symbol"],item["endpoint"],item["start"],item["end"]),item)
    return list(unique.values())


def url_for(item, host):
    symbol,endpoint=item["symbol"],item["endpoint"]
    session=item["session"]
    if endpoint=="identity":
        path=f"/v3/reference/tickers/{symbol}"
        query={"date":item["end"]}
    elif endpoint=="summary":
        path=f"/v1/open-close/{symbol}/{item['start']}"
        query={"adjusted":"false"}
    elif endpoint in {"day","minute"}:
        lower,upper=(str(milliseconds(session["open"])),str(milliseconds(session["close"])-1)) if endpoint=="minute" else (item["start"],item["end"])
        path=f"/v2/aggs/ticker/{symbol}/range/1/{endpoint}/{lower}/{upper}"
        query={"adjusted":"false","sort":"asc","limit":"5000"}
    else:
        action=endpoint.split("-")[0]
        prefix="/v3/reference/" if endpoint.endswith("-legacy") else "/stocks/v1/"
        path=prefix+action
        field="ex_dividend_date" if action=="dividends" else "execution_date"
        query={"ticker":symbol,field+".gte":item["start"],field+".lte":item["end"],"limit":"1000",
               "sort":field if endpoint.endswith("-legacy") else field+".asc"}
        if endpoint.endswith("-legacy"):
            query["order"]="asc"
    return "https://"+host+path+"?"+urlencode(query)
