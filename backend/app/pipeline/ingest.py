import math
import httpx
import asyncio
from datetime import datetime, timedelta, timezone
from gdacs.api import GDACSAPIReader

# EONET Category to GDACS Type Mapping
CATEGORY_MAP = {
    "Wildfires": "WF",
    "Severe Storms": "TC",
    "Volcanoes": "VO",
    "Floods": "FL",
    "Earthquakes": "EQ"
}

ALLOWED_CATEGORIES = list(CATEGORY_MAP.keys())

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians 
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Radius of earth in kilometers. Use 3956 for miles
    return c * r

def parse_date(value: str) -> datetime:
    """Parses an ISO date; dates without a timezone are taken as UTC."""
    value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def point_of(geometry: dict):
    """
    Returns (lat, lon) for a GeoJSON Point, or the mean of the outer ring's
    vertices for a Polygon.
    """
    coords = geometry["coordinates"]
    if geometry.get("type") == "Polygon":
        ring = coords[0]
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)
    return coords[1], coords[0]

def event_timeline(eonet_event: dict):
    """
    Returns (first_seen, last_updated, latest_geometry) for an EONET event,
    independent of the order its geometry points are listed in.
    """
    points = [g for g in eonet_event.get("geometry") or [] if g.get("date")]
    if not points:
        raise ValueError(f"Event {eonet_event.get('id')} has no dated geometry")
    ordered = sorted(points, key=lambda g: parse_date(g["date"]))
    return ordered[0]["date"], ordered[-1]["date"], ordered[-1]

async def fetch_eonet_events(limit=100):
    url = f"https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit={limit}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        events = data.get("events", [])
        
        filtered_events = []
        for event in events:
            category = event["categories"][0]["title"]
            if category in ALLOWED_CATEGORIES:
                filtered_events.append(event)
        
        return filtered_events

def get_gdacs_events():
    client = GDACSAPIReader()
    try:
        events = client.latest_events()
        # gdacs-api 2.0.0 returns a GeoJSON object with a .features list of dicts
        return events.features if hasattr(events, 'features') else []
    except Exception as e:
        print(f"Error fetching GDACS events: {e}")
        return []

def match_events(eonet_event, gdacs_events):
    eonet_cat = eonet_event["categories"][0]["title"]
    gdacs_type = CATEGORY_MAP.get(eonet_cat)
    
    if not gdacs_type:
        return None
    
    # Compare against the event's latest observation; polygons use their centre
    _, eonet_date_str, latest = event_timeline(eonet_event)
    eonet_lat, eonet_lon = point_of(latest)
    eonet_date = parse_date(eonet_date_str)
    
    for g_event in gdacs_events:
        props = g_event.get("properties", {})
        # Check type
        if props.get("eventtype") != gdacs_type:
            continue
            
        try:
            # Check distance
            geom = g_event.get("geometry") or {}
            g_lat, g_lon = point_of(geom)
            distance = haversine(eonet_lat, eonet_lon, g_lat, g_lon)

            if distance > 100:
                continue

            # Check date overlap (within 3 days); dates without a timezone are UTC
            g_date_str = props.get("fromdate") or ""
            if not g_date_str:
                continue
            g_date = parse_date(g_date_str)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            print(f"Skipping malformed GDACS event {props.get('eventid')}: {e}")
            continue
            
        if abs((eonet_date - g_date).days) <= 3:
            return g_event
            
    return None

async def run_ingestion():
    eonet_events = await fetch_eonet_events()
    gdacs_events = get_gdacs_events()
    
    results = []
    for e_event in eonet_events:
        try:
            matched = match_events(e_event, gdacs_events)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            # Left for the orchestrator to process (and report) on its own
            print(f"Could not match {e_event.get('id')} against GDACS: {e}")
            matched = None
        results.append({
            "eonet": e_event,
            "gdacs": matched
        })
    return results

if __name__ == "__main__":
    import json
    res = asyncio.run(run_ingestion())
    print(f"Ingested {len(res)} events.")
    # TODO: Save to DB
