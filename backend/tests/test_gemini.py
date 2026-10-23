from datetime import date

from backend.app.pipeline.gemini import check_quota
from backend.app.db.database import get_db


def test_gemini_quota_guard():
    today = date.today().isoformat()

    # Fresh temporary DB from conftest: no calls recorded yet
    assert check_quota() is True

    # Simulate 80 calls
    conn = get_db()
    conn.execute("INSERT INTO gemini_calls (call_date, call_count) VALUES (?, 80)", (today,))
    conn.commit()
    conn.close()

    assert check_quota() is False
