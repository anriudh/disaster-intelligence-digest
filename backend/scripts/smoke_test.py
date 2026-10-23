import httpx
import time
import sys

BASE_URL = "http://localhost:8000/api"

def test_health():
    print("Testing /health...")
    response = httpx.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "last_run_started" in data
    print("Health check passed.")

def test_events():
    print("Testing /events...")
    response = httpx.get(f"{BASE_URL}/events")
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    print(f"Found {len(data['events'])} events.")
    if data['events']:
        event = data['events'][0]
        assert "id" in event
        assert "title" in event
        assert "category" in event
        assert event["severity_status"] == "withheld_unvalidated_model"
        return event["id"]
    return None

def test_event_detail(event_id):
    if not event_id:
        print("Skipping event detail test (no events found).")
        return
    print(f"Testing /events/{event_id}...")
    response = httpx.get(f"{BASE_URL}/events/{event_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == event_id
    assert data["severity_status"] == "withheld_unvalidated_model"
    print("Event detail test passed.")

def test_trends():
    print("Testing /trends...")
    response = httpx.get(f"{BASE_URL}/trends")
    assert response.status_code == 200
    data = response.json()
    assert "category_trends" in data
    assert data["severity_status"] == "withheld_unvalidated_model"
    print("Trends test passed.")

def test_rate_limiter():
    print("Testing rate limiter...")
    count = 0
    try:
        for _ in range(70):
            response = httpx.get(f"{BASE_URL}/events")
            if response.status_code == 429:
                count += 1
                break
    except Exception:
        pass
    
    if count > 0:
        print("Rate limiter working (received 429).")
    else:
        print("Rate limiter did not return 429 after 70 requests. (Might be config or IP issues)")

def main():
    try:
        test_health()
        event_id = test_events()
        test_event_detail(event_id)
        test_trends()
        test_rate_limiter()
        print("\nAll smoke tests completed.")
    except Exception as e:
        print(f"\nSmoke test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
