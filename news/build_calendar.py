"""
SPX News calendar for Adam's iPhone: liamanderson2306.github.io/news/spx-news.ics (subscribe once, it updates itself).

Runs every day on GitHub Actions (.github/workflows/news-calendar.yml). It:
  1. downloads this week's US news from the free Forex Factory feed (forecast + previous),
  2. adds TJR's verdict for each day (same rules as Can I Trade Today), what history says, and where to watch,
  3. keeps the last 2 weeks so past events don't vanish, and writes spx-news.ics + index.html.
Standard library only.
"""
import hashlib, html, json, re, sys, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
ET, PERTH = ZoneInfo("America/New_York"), ZoneInfo("Australia/Perth")
FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STORE, ICS, PAGE = HERE / "events.json", HERE / "spx-news.ics", HERE / "index.html"
SITE = "https://liamanderson2306.github.io/news/"
HIST = json.loads((HERE / "history_summary.json").read_text(encoding="utf-8"))

BIG4 = re.compile(r"\bCPI\b|\bPPI\b|FOMC(?! Member)|Federal Funds|Non-Farm|\bNFP\b", re.I)
FED_CHAIR = re.compile(r"Fed Chair", re.I)
NYSE_CLOSED = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
               "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24", "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29",
               "2028-06-19", "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25"}
NYSE_HALF = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-11-24"}
OPEN, CLOSE = 570, 660                                   # 9:30-11:00am New York: Adam's window


def canon(title):
    """Forex Factory names Fed Chair appearances several ways; the history file pools them as 'Fed Chair Speaks/Testifies'."""
    m = re.match(r"^(?:Fed Chair(?:man)?|FOMC Member) (\w+) (Speaks|Testifies)$", title)
    if m and (title.startswith("Fed Chair") or m.group(1) == "Warsh"):
        return f"Fed Chair {m.group(2)}"
    return title


def hm(t):
    return t.strftime("%I:%M%p").lstrip("0").lower()


# ------------------------------------------------------------------ 1. news (feed + rolling store)
def load_store():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"events": {}, "covered": []}


def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0 (spx-news-calendar)"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    out = []
    for e in data:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium", "Holiday"):
            continue
        t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        out.append(dict(title=e["title"], impact=e["impact"], forecast=e.get("forecast", ""), previous=e.get("previous", ""), ts=int(t.timestamp())))
    days = sorted({datetime.fromisoformat(e["date"]).astimezone(ET).date().isoformat() for e in data})
    return out, days


store = load_store()
try:
    fresh, covered = fetch()
    lo, hi = covered[0], covered[-1]
    # replace everything inside the fetched week (catches moved or cancelled events), keep older weeks
    store["events"] = {k: v for k, v in store["events"].items()
                       if not (lo <= datetime.fromtimestamp(v["ts"], ET).date().isoformat() <= hi)}
    for e in fresh:
        store["events"][f"{e['title']}|{e['ts']}"] = e
    store["covered"] = sorted(set(store["covered"]) | set(covered))
    print(f"feed ok: {len(fresh)} US events, {lo} -> {hi}")
except Exception as ex:                                  # keep yesterday's calendar rather than wiping it
    print(f"feed failed ({ex.__class__.__name__}: {ex}); keeping the saved events", file=sys.stderr)
cutoff = (datetime.now(ET).date() - timedelta(days=14)).isoformat()
store["events"] = {k: v for k, v in store["events"].items() if datetime.fromtimestamp(v["ts"], ET).date().isoformat() >= cutoff}
store["covered"] = [d for d in store["covered"] if d >= cutoff]
STORE.write_text(json.dumps(store, indent=1, sort_keys=True), encoding="utf-8")

events = sorted(store["events"].values(), key=lambda e: e["ts"])
for e in events:
    e["ny"] = datetime.fromtimestamp(e["ts"], ET)
    e["day"] = e["ny"].date()
    e["min"] = e["ny"].hour * 60 + e["ny"].minute


# ------------------------------------------------------------------ 2. TJR's day verdict (same rules as can_i_trade.py)
def judge(day):
    iso = day.isoformat()
    if iso in NYSE_CLOSED:
        return "NO TRADE", "US stock market holiday", ["US stock market holiday: the NYSE is closed."]
    usd = [e for e in events if e["day"] == day]
    verdict, short, reasons = "OK", "no big US news", []
    if iso in NYSE_HALF:
        verdict, short = "CAUTION", "half day"
        reasons.append("Half day: the market closes at 1pm NY. Thin and odd, so reduce risk or skip.")
    if any(e["impact"] == "Holiday" for e in usd):
        return "NO TRADE", "US bank holiday", ["US bank holiday (gray folder): TJR leaves these days alone."]
    big = [e for e in usd if e["impact"] == "High" and BIG4.search(e["title"])]
    if big:
        names = ", ".join(dict.fromkeys(e["title"] for e in big))
        return "NO TRADE", "Big-4 news", [f"Big-4 news: {names} at {hm(big[0]['ny'])} NY. TJR: 'call it quits, live to trade another day'."]
    fed = [e for e in usd if e["impact"] in ("High", "Medium") and FED_CHAIR.search(canon(e["title"]))]
    if fed:
        return "NO TRADE", "Fed Chair speaks", [f"Fed Chair speaks at {hm(fed[0]['ny'])} NY. TJR sits these out."]
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    if nxt.isoformat() in NYSE_CLOSED or any(e["day"] == nxt and e["impact"] == "Holiday" for e in events):
        verdict, short = "CAUTION", "holiday next"
        reasons.append("US holiday next trading day: low volume, choppy. TJR uses half size, so half risk or skip.")
    wait_until = None
    for e in usd:
        if e["impact"] not in ("High", "Medium"):
            continue
        colour = "RED" if e["impact"] == "High" else "ORANGE"
        if e["min"] < OPEN:
            if verdict == "OK":
                verdict, short = "CAUTION", "news before the open"
            reasons.append(f"{colour} {e['title']} at {hm(e['ny'])} NY (before the open): look at the reaction first. A big spike or big wicks = no trade today.")
        elif e["min"] < CLOSE:
            until = e["ny"] + timedelta(minutes=30)
            wait_until = max(wait_until, until) if wait_until else until
            reasons.append(f"{colour} {e['title']} at {hm(e['ny'])} NY (inside your window): hands off for 30 minutes. If it spikes the market, you're done for the day.")
    if wait_until:
        verdict, short = "WAIT", f"wait till {hm(wait_until)} NY"
    reds = [e for e in usd if e["impact"] == "High"]
    if len(reds) >= 3 and verdict == "OK":
        verdict, short = "CAUTION", "lots of red news"
    if reds:
        reasons.append(f"{len(reds)} red folder{'s' if len(reds) > 1 else ''} today: lower-probability day, A+ setups only.")
    return verdict, short, reasons or ["No US red or orange news in your window."]


# ------------------------------------------------------------------ 3. where to watch
def watch(titles):
    s = " ".join(titles)
    if re.search(r"FOMC(?! Member)|Federal Funds|Fed Chair|Fed Announcement|Powell|Warsh", s):
        return [("Federal Reserve live on YouTube", "https://www.youtube.com/@federalreserve"),
                ("Federal Reserve live broadcast", "https://www.federalreserve.gov/live-broadcast.htm")]
    if re.search(r"President|Trump", s):
        return [("White House live", "https://www.whitehouse.gov/live/")]
    return [("The numbers as they come out: Forex Factory calendar", "https://www.forexfactory.com/calendar"),
            ("The market reaction: CNBC Television on YouTube", "https://www.youtube.com/@CNBCtelevision")]


# ------------------------------------------------------------------ 4. calendar file
def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """iCalendar lines max 75 bytes; continuation lines start with a space (never split a UTF-8 character)"""
    b, out, cur = line.encode("utf-8"), [], b""
    for ch in line:
        c = ch.encode("utf-8")
        if len(cur) + len(c) > (75 if not out else 74):
            out.append(cur); cur = b""
        cur += c
    out.append(cur)
    return "\r\n ".join(x.decode("utf-8") for x in out)


EMOJI = {"NO TRADE": "🚫", "WAIT": "⏳", "CAUTION": "⚠️", "OK": "✅"}
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Practice Pit//SPX News//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
     "X-WR-CALNAME:SPX News (TJR)", "X-WR-CALDESC:US news that moves the S&P 500\\, with forecasts\\, TJR's verdict and where to watch.",
     "X-WR-TIMEZONE:Australia/Perth", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]

days = sorted({date.fromisoformat(d) for d in store["covered"]} | {e["day"] for e in events})
verdicts = {}
for d in days:
    if d.weekday() >= 5:
        continue
    v, short, reasons = judge(d)
    verdicts[d] = (v, short, reasons)
    perth_open = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET).astimezone(PERTH)
    desc = (f"TJR verdict for {d:%A %d %B}: {v}\n" + "\n".join("- " + r for r in reasons)
            + f"\n\nYour window: 9:30-11:00am New York = {hm(perth_open)}-{hm(perth_open + timedelta(minutes=90))} Perth.\nMore: {SITE}")
    L += ["BEGIN:VEVENT", f"UID:day-{d.isoformat()}@liamanderson2306.github.io", f"DTSTAMP:{stamp}",
          f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
          f"SUMMARY:{esc(f'{EMOJI[v]} TJR: {v} ({short})')}", f"DESCRIPTION:{esc(desc)}", "TRANSP:TRANSPARENT", "END:VEVENT"]

groups = {}
for e in events:
    if e["impact"] in ("High", "Medium"):
        groups.setdefault(e["ts"], []).append(e)
for ts, g in sorted(groups.items()):
    g.sort(key=lambda e: e["impact"] != "High")
    titles = [e["title"] for e in g]
    high = any(e["impact"] == "High" for e in g)
    ny = g[0]["ny"]
    name = titles[0] + (f" + {len(titles) - 1} more" if len(titles) > 1 else "")
    mins = 45 if re.search(r"Press Conference|Speaks|Testifies", " ".join(titles)) else 30 if re.search(r"FOMC|Federal Funds", " ".join(titles)) else 15
    lines = [f"{'RED' if high else 'ORANGE'} news at {hm(ny)} New York.", ""]
    for e in g:
        nums = f": forecast {e['forecast'] or '-'}, previous {e['previous'] or '-'}" if (e["forecast"] or e["previous"]) else ""
        lines.append(f"- {e['title']}{nums}")
    best = max((HIST.get(canon(t)) or {} for t in titles), key=lambda h: h.get("times") or 0)
    if best.get("times"):
        lines += ["", f"History (S&P 2018-2026): the first 5 minutes usually swing {best['swing']}%, about {best['times']}x a normal 5 minutes."]
        lines += ["- " + x for x in best.get("lines", [])] or ["- No reliable direction: expect a big move, not a known direction."]
        lines.append("(PROVEN means more likely, not certain.)")
    v = verdicts.get(ny.date())
    if v:
        lines += ["", f"TJR today: {v[0]} ({v[1]})."]
    lines += ["", "Where to watch:"] + [f"- {n}: {u}" for n, u in watch(titles)]
    uid = hashlib.sha1(f"{ts}|{'|'.join(sorted(titles))}".encode()).hexdigest()[:16]
    start = datetime.fromtimestamp(ts, timezone.utc)
    L += ["BEGIN:VEVENT", f"UID:{uid}@liamanderson2306.github.io", f"DTSTAMP:{stamp}",
          f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{start + timedelta(minutes=mins):%Y%m%dT%H%M%SZ}",
          f"SUMMARY:{esc(f'{chr(0x1F534) if high else chr(0x1F7E0)} {name} ({hm(ny)} NY)')}",
          f"DESCRIPTION:{esc(chr(10).join(lines))}", f"URL:{watch(titles)[0][1]}", "TRANSP:TRANSPARENT"]
    if high:
        L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(name + ' in 15 minutes')}", "TRIGGER:-PT15M", "END:VALARM"]
    L.append("END:VEVENT")
L.append("END:VCALENDAR")
ICS.write_text("\r\n".join(fold(x) for x in L) + "\r\n", encoding="utf-8", newline="")
print(f"wrote {ICS.name}: {len(groups)} releases, {len(verdicts)} day verdicts")


# ------------------------------------------------------------------ 5. a simple web page with the subscribe button
today = datetime.now(ET).date()
rows = []
for d in [d for d in sorted(verdicts) if d >= today - timedelta(days=1)]:
    v, short, reasons = verdicts[d]
    items = "".join(
        f"<li><span class='t'>{hm(e['ny'])} NY · {hm(e['ny'].astimezone(PERTH))} Perth</span> "
        f"<span class='dot {'h' if e['impact'] == 'High' else 'm'}'></span>{html.escape(e['title'])}"
        f"{' · forecast <b>' + html.escape(e['forecast']) + '</b>' if e['forecast'] else ''}"
        f"{' · previous ' + html.escape(e['previous']) if e['previous'] else ''}</li>"
        for e in events if e["day"] == d and e["impact"] in ("High", "Medium"))
    rows.append(f"<section><h2>{d:%A %d %B} <span class='v v-{v.split()[0]}'>{v}</span></h2><p class='why'>{html.escape(reasons[0])}</p>"
                f"<ul>{items or '<li>No big US news.</li>'}</ul></section>")
PAGE.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>SPX News</title>
<style>
:root{{--bg:#f4f6fb;--card:#fff;--ink:#131722;--muted:#6a6d78;--line:#e0e3eb;--blue:#2962ff;--red:#f23645;--orange:#e67700;--green:#089981}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0e14;--card:#131722;--ink:#d1d4dc;--muted:#8a8f9c;--line:#2a2e39}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:16px max(16px,env(safe-area-inset-left))}}
main{{max-width:720px;margin:0 auto}} h1{{margin:8px 0 4px;font-size:26px}} .sub{{color:var(--muted);margin:0 0 14px}}
.btn{{display:inline-block;background:var(--blue);color:#fff;text-decoration:none;font-weight:700;padding:11px 16px;border-radius:8px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:10px}}
h2{{font-size:16px;margin:0;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}}
.v{{font-size:12px;font-weight:800;padding:2px 8px;border-radius:4px;color:#fff}} .v-NO{{background:var(--red)}} .v-WAIT,.v-CAUTION{{background:var(--orange)}} .v-OK{{background:var(--green)}}
.why{{color:var(--muted);margin:4px 0 6px;font-size:13.5px}} ul{{margin:0;padding-left:0;list-style:none}} li{{padding:3px 0}}
.t{{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:6px}} .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
.dot.h{{background:var(--red)}} .dot.m{{background:var(--orange)}} .note{{color:var(--muted);font-size:13px;margin-top:16px}}
</style></head><body><main>
<h1>SPX News</h1><p class="sub">US news that moves the S&amp;P 500, with TJR's verdict for each day. Updated {datetime.now(PERTH):%a %d %b, %I:%M%p} Perth.</p>
<a class="btn" href="webcal://liamanderson2306.github.io/news/spx-news.ics">Add to my iPhone calendar</a>
{''.join(rows) or '<section>No news loaded yet.</section>'}
<p class="note">News from the Forex Factory calendar. Forecasts can change during the week and next week's list appears on Sunday. Not financial advice.</p>
</main></body></html>""", encoding="utf-8")
print("wrote index.html")
