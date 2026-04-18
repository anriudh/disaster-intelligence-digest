import pytest
import asyncio
from backend.app.pipeline.ingest import haversine, fetch_eonet_events, match_events, ALLOWED_CATEGORIES

def test_haversine():
    # NYC to London is approx 5570 km
    nyc = (40.7128, -74.0060)
    london = (51.5074, -0.1278)
    dist = haversine(nyc[0], nyc[1], london[0], london[1])
    assert 5500 < dist < 5650

@pytest.mark.asyncio
async def test_fetch_eonet_events():
    events = await fetch_eonet_events(limit=10)
    assert isinstance(events, list)
    if events:
        event = events[0]
        assert "id" in event
        assert "title" in event
        assert "categories" in event
        assert "sources" in event
        
        # Check filtering
        for e in events:
            cat = e["categories"][0]["title"]
            assert cat in ALLOWED_CATEGORIES
            assert cat not in ["Sea and Lake Ice", "Icebergs", "Dust and Haze"]

class MockGDACSEvent:
    def __init__(self, eventtype, lat, lon, fromdate):
        self.eventtype = eventtype
        self.totallat = lat
        self.totallon = lon
        self.fromdate = fromdate

def test_match_events():
    # Mock EONET event (Wildfire in Arizona)
    eonet_event = {
        "id": "EONET_1",
        "title": "Arizona Fire",
        "categories": [{"title": "Wildfires"}],
        "geometry": [{"date": "2024-06-01T12:00:00Z", "coordinates": [-110.0, 32.0]}],
        "sources": []
    }
    
    # Mock GDACS events
    # 1. Correct match
    g1 = MockGDACSEvent("WF", "32.1", "-110.1", "2024-06-01T10:00:00Z")
    # 2. Wrong type
    g2 = MockGDACSEvent("EQ", "32.1", "-110.1", "2024-06-01T10:00:00Z")
    # 3. Too far
    g3 = MockGDACSEvent("WF", "35.0", "-115.0", "2024-06-01T10:00:00Z")
    # 4. Too late
    g4 = MockGDACSEvent("WF", "32.1", "-110.1", "2024-06-10T10:00:00Z")
    
    match = match_events(eonet_event, [g1, g2, g3, g4])
    assert match == g1
    
    no_match = match_events(eonet_event, [g2, g3, g4])
    assert no_match is None
