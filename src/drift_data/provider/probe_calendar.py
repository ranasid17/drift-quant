"""Frozen exchange schedule for bounded probes; no weekday substitutes."""
from datetime import datetime, timedelta, timezone
from importlib.metadata import version


def freeze(as_of):
    import exchange_calendars
    if as_of.tzinfo is None:
        raise ValueError("UTC as-of required")
    calendar=exchange_calendars.get_calendar("XNYS",start="2003-09-10",end=f"{as_of.year+1}-12-31")
    sessions=[]
    for label,row in calendar.schedule.iterrows():
        close=row["close"].to_pydatetime()
        if close >= as_of:
            break
        sessions.append({"date":str(label.date()),"open":row["open"].isoformat(),"close":row["close"].isoformat()})
    if not sessions:
        raise ValueError("No completed sessions in supported calendar range")
    return {"calendar":"XNYS","timezone":"America/New_York",
            "exchange_calendars":version("exchange-calendars"),"tzdata":version("tzdata"),
            "timezone_resolution":"calendar-library runtime; frozen UTC instants authoritative",
            "sessions":sessions}


def latest_before(calendar, day):
    matches=[s for s in calendar["sessions"] if s["date"]<=day]
    if not matches:
        raise ValueError("Date outside frozen schedule")
    return matches[-1]


def diagnostics(calendar):
    sessions=calendar["sessions"]
    recent=sessions[-1]
    transitions=[]
    for previous,current in zip(sessions,sessions[1:]):
        if current["date"][:4]==recent["date"][:4] and previous["open"][11:16]!=current["open"][11:16]:
            transitions.append((previous,current))
    early=[s for s in sessions if (datetime.fromisoformat(s["close"])-datetime.fromisoformat(s["open"])).total_seconds()<6.5*3600]
    ordinary=[s for s in sessions if (datetime.fromisoformat(s["close"])-datetime.fromisoformat(s["open"])).total_seconds()==6.5*3600]
    result={"ordinary":ordinary[-1] if ordinary else recent}
    if transitions:
        result.update(dst_before=transitions[-1][0],dst_after=transitions[-1][1])
    if early:
        result["early_close"]=early[-1]
    return result


def milliseconds(instant):
    return int(datetime.fromisoformat(instant).timestamp()*1000)
