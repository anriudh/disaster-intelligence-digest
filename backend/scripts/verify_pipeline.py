import sqlite3
import os
import sys

DB_PATH = "backend/data/disaster_intel.db"

def verify():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("Verifying database content...")
    
    # 1. Check events
    cursor.execute("SELECT COUNT(*) FROM events")
    event_count = cursor.fetchone()[0]
    print(f"Total events: {event_count}")
    assert event_count > 0
    
    # 2. Check analysis
    cursor.execute("SELECT * FROM event_analysis LIMIT 1")
    analysis = cursor.fetchone()
    if analysis:
        print("Analysis verification:")
        print(f" - Severity Label: {analysis['severity_label']}")
        assert analysis['severity_label'] in ["LOW", "MODERATE", "HIGH"]
        assert analysis['ner_entities'] is not None
        assert analysis['embedding'] is not None
    else:
        print("Error: No analysis records found.")
        sys.exit(1)
        
    # 3. Check Gemini digests (for MODERATE/HIGH)
    cursor.execute("SELECT COUNT(*) FROM event_analysis WHERE gemini_digest IS NOT NULL")
    digest_count = cursor.fetchone()[0]
    print(f"Events with Gemini digests: {digest_count}")
    
    conn.close()
    print("\nPipeline verification successful.")

if __name__ == "__main__":
    verify()
