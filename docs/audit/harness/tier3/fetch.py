"""Tier 3 fetch phase. Calls (fixed): 1 EONET open GET (limit=100), 1 category-filtered
EONET GET, <=10 source URLs, 1 GDACS latest_events(). Saves raw responses to OUT only."""
import json, os, sys, time, hashlib
from collections import OrderedDict
import httpx

OUT = sys.argv[1]
os.makedirs(f"{OUT}/html", exist_ok=True)
log = []
calls = 0

def get(url, **kw):
    global calls
    calls += 1
    t = time.time()
    try:
        r = httpx.get(url, timeout=20.0, follow_redirects=True, **kw)
        log.append({"url": url, "final_url": str(r.url), "status": r.status_code, "secs": round(time.time() - t, 2)})
        return r
    except Exception as e:
        log.append({"url": url, "error": repr(e)})
        return None

# T3-1: one open-events GET, exactly as the pipeline requests it
r = get("https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100")
r.raise_for_status()
open(f"{OUT}/eonet_open_limit100.json", "w").write(r.text)
events = r.json()["events"]

# T3-3: one category-filtered GET of all open allowed-category events (no limit)
cats = "wildfires,severeStorms,volcanoes,floods,earthquakes"
r2 = get(f"https://eonet.gsfc.nasa.gov/api/v3/events?status=open&category={cats}")
if r2 is not None:
    open(f"{OUT}/eonet_open_allowed_categories.json", "w").write(r2.text)

# T3-1 sources: <=10, one per event, round-robin over categories, distinct domains first
ALLOWED = ["Wildfires", "Severe Storms", "Volcanoes", "Floods", "Earthquakes"]
by_cat = OrderedDict((c, []) for c in ALLOWED)
for e in events:
    c = e["categories"][0]["title"]
    if c in by_cat and e.get("sources"):
        by_cat[c].append(e)
picked, domains = [], set()
for pass_ in (0, 1):
    while len(picked) < 10 and any(by_cat.values()):
        progressed = False
        for c, lst in by_cat.items():
            while lst:
                e = lst.pop(0)
                url = e["sources"][0]["url"]
                dom = httpx.URL(url).host
                if pass_ == 0 and dom in domains:
                    continue
                picked.append({"event_id": e["id"], "category": c, "source_id": e["sources"][0]["id"], "url": url})
                domains.add(dom)
                progressed = True
                break
            if len(picked) >= 10:
                break
        if not progressed:
            break
    if len(picked) >= 10:
        break
    # second pass allows repeated domains
    by_cat = OrderedDict((c, []) for c in ALLOWED)
    chosen = {p["event_id"] for p in picked}
    for e in events:
        c = e["categories"][0]["title"]
        if c in by_cat and e.get("sources") and e["id"] not in chosen:
            by_cat[c].append(e)

headers = {"User-Agent": "Mozilla/5.0 (compatible; disaster-intel-tier3-check)"}
for p in picked[:10]:
    r = get(p["url"], headers=headers)
    p["status"] = None if r is None else r.status_code
    p["content_type"] = None if r is None else r.headers.get("content-type")
    if r is not None:
        name = hashlib.sha1(p["url"].encode()).hexdigest()[:12] + ".html"
        open(f"{OUT}/html/{name}", "w", encoding="utf-8").write(r.text)
        p["file"] = name
    time.sleep(2)
json.dump(picked[:10], open(f"{OUT}/sources.json", "w"), indent=1)

# T3-2: one GDACS call through the same client the pipeline uses
global_calls_before = calls
from gdacs.api import GDACSAPIReader
calls += 1
try:
    g = GDACSAPIReader().latest_events()
    feats = g.features if hasattr(g, "features") else None
    json.dump({"type": type(g).__name__, "features": feats}, open(f"{OUT}/gdacs_latest.json", "w"), default=str)
    log.append({"url": "GDACSAPIReader.latest_events()", "features": None if feats is None else len(feats)})
except Exception as e:
    log.append({"url": "GDACSAPIReader.latest_events()", "error": repr(e)})

json.dump({"calls": calls, "log": log}, open(f"{OUT}/fetch_log.json", "w"), indent=1)
print(json.dumps({"calls": calls, "log": log}, indent=1))
