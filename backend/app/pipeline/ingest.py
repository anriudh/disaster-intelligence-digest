import math
import httpx
import asyncio
from datetime import datetime, timedelta
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
    # Pull last 30 days for live enrichment
    # Note: gdacs-api might have different methods, let's assume a generic fetch for now
    # based on the GEMINI.md hint "Use gdacs-api library for structured access"
    # Actual implementation might need to check the library docs.
    # Looking at common patterns for this library:
    try:
        events = client.latest_events()
        return events
    except Exception as e:
        print(f"Error fetching GDACS events: {e}")
        return []

def match_events(eonet_event, gdacs_events):
    eonet_cat = eonet_event["categories"][0]["title"]
    gdacs_type = CATEGORY_MAP.get(eonet_cat)
    
    if not gdacs_type:
        return None
    
    eonet_geo = eonet_event["geometry"][0]
    eonet_lat = eonet_geo["coordinates"][1]
    eonet_lon = eonet_geo["coordinates"][0]
    eonet_date = datetime.fromisoformat(eonet_geo["date"].replace("Z", "+00:00"))
    
    for g_event in gdacs_events:
        # Check type
        if g_event.eventtype != gdacs_type:
            continue
            
        # Check distance
        g_lat = float(g_event.totallat)
        g_lon = float(g_event.totallon)
        distance = haversine(eonet_lat, eonet_lon, g_lat, g_lon)
        
        if distance > 100:
            continue
            
        # Check date overlap (within 3 days)
        g_date = datetime.fromisoformat(g_event.fromdate.replace("Z", "+00:00"))
        if abs((eonet_date - g_date).days) <= 3:
            return g_event
            
    return None

async def run_ingestion():
    eonet_events = await fetch_eonet_events()
    gdacs_events = get_gdacs_events()
    
    results = []
    for e_event in eonet_events:
        matched = match_events(e_event, gdacs_events)
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
