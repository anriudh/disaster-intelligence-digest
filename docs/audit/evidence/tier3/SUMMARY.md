# Tier 3 evidence summary (2026-10-24)

Fetch phase: `docs/audit/harness/tier3/fetch.py`, 13 external calls (cap 13): 1 EONET open GET (`limit=100`),
1 category-filtered EONET GET, 10 source URLs, 1 GDACS `latest_events()`. Analysis run offline (sockets
disabled) against the saved responses, calling the branch's own `ingest` and `scraper` functions.
Raw responses and HTML are kept outside the repository; only this summary and `summary.json` are committed.

## T3-1 Source extraction (Q3)

| Domain | Sampled | Outcome |
|---|---|---|
| irwin.doi.gov (Wildfires) | 5 | all 200 HTML; trafilatura returns 46 chars, rejected by `is_boilerplate` (JavaScript app shell) |
| www.metoc.navy.mil/jtwc (Severe Storms) | 5 | 3 × 200 `binary/octet-stream` `.tcw` files, trafilatura returns None; 2 × 403 |

Unextractable share: **10/10**. Every event in the sample falls back to its title and description.
Limitation: the `limit=100` response held only two categories with sources, so the sample covers two
domains. It says these two sources never yield text; it does not measure sources in general.

The A4 gate works as intended on live data: without it the five IRWIN pages would be stored as "extracted".

## T3-1 Geometry order (Q1)

Open `limit=100`: 95 single-point events, 5 multi-point (all Severe Storms), all 5 ascending.
Category GET: 7,189 single-point, 5 multi-point, all ascending. All geometries are `Point`.
No descending or unordered records were observed; `event_timeline` sorts regardless.

## T3-3 Filter-after-limit truncation (F15)

| | Wildfires | Severe Storms | Volcanoes | Total |
|---|---|---|---|---|
| Allowed events in `limit=100` | 94 | 5 | 0 | 99 |
| Open events, category GET | 7,157 | 5 | 32 | 7,194 |
| Missing from `limit=100` | 7,063 | 0 | 32 | 7,095 |

Floods and Earthquakes had no open events. EONET accepts the comma-separated `category` filter.

Last-update age of the open events (category GET):

| | ≤7d | 8–30d | 31–90d | 91–365d | >365d |
|---|---|---|---|---|---|
| Wildfires | 6 | 31 | 216 | 1,327 | 5,577 |
| Severe Storms | 5 | | | | |
| Volcanoes | | | | 13 | 19 |

The `limit=100` response spans last-update ages 0–57 days, and **none of the missing events was updated in
the last 30 days**. So the truncation drops only events older than the app's 30-day listing window
(`backend/app/api/routes.py:35`); today it loses nothing the API would show. The ordering suggests EONET
returns the most recently updated events first, but that is inferred from one response. Headroom: 42 allowed events updated within 30 days against a limit of 100.
All 32 open volcanoes are missed, but none was updated within 91 days.

## T3-2 GDACS matching (Q2)

- 100 features: 85 WF, 14 EQ, 1 TC; no VO or FL.
- `fromdate` is a naive ISO timestamp (`2026-10-23T17:06:25`) in all 100; `parse_date` reads it as UTC.
  GDACS does not state the zone; with a 3-day window the hour offset does not change any result.
- `match_events` on the 99 allowed `limit=100` events: **1 match**, 0 errors, 98 with the nearest
  same-type GDACS event over 100 km.
- On all 7,194 category-GET events: 1 match; 6,921 nearest over 100 km; 240 within 100 km but more than
  3 days apart; 32 volcanoes with no GDACS event of that type.
- 66 of the 85 GDACS wildfires lie within 100 km of some open EONET wildfire, but mostly of old EONET
  records, which fail the 3-day check.

Why matches are near zero: the two feeds describe different fires.
- The recent EONET window is entirely US and ocean sources: the `limit=100` events come from IRWIN (94),
  JTWC (5) and NATICE (1).
- GDACS's latest wildfires (`fromdate` 2026-10-09 to 2026-10-23) are in Australia (20), Mozambique (13),
  Botswana, South Sudan and elsewhere in Africa.
- EONET does carry 3,855 open wildfires sourced from GDACS (`report.aspx?eventid=…`), but all were last
  updated more than 30 days ago and none links to an event in the fetched GDACS payload. EONET appears to
  have stopped refreshing its GDACS-sourced wildfires; this run cannot say why.

So the low match rate is a coverage gap between the sources, not a parsing or timezone defect.
