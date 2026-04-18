import os
import json
from datetime import date
from google import genai
from backend.app.db.database import get_db
from dotenv import load_dotenv
import logging

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Gemini Client
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")

def check_quota() -> bool:
    """
    Checks if the daily quota of 80 calls has been reached.
    """
    today = date.today().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT call_count FROM gemini_calls WHERE call_date = ?", (today,))
    row = cursor.fetchone()
    conn.close()
    
    count = row[0] if row else 0
    return count < 80

def increment_quota():
    """
    Increments the daily call counter.
    """
    today = date.today().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO gemini_calls (call_date, call_count) VALUES (?, 1) "
        "ON CONFLICT(call_date) DO UPDATE SET call_count = call_count + 1",
        (today,)
    )
    conn.commit()
    conn.close()

async def generate_digest(event_data: dict):
    """
    Generates a structured digest using Gemini 2.5 Flash.
    """
    if not client:
        logger.warning("Gemini client not initialized. Skipping.")
        return None

    if not check_quota():
        logger.warning("Gemini quota exceeded for today. Skipping.")
        return None

    prompt = f"""
    You are a disaster intelligence analyst. Generate a structured digest for the following event.

    Event: {event_data.get('title')}
    Category: {event_data.get('category')}
    Location entities: {', '.join([e[0] for e in event_data.get('ner_entities', []) if e[1] in ('GPE', 'LOC')])}
    Severity: {event_data.get('severity_label')} (score: {event_data.get('severity_score', 0):.2f})
    Key signals: {json.dumps(event_data.get('regex_signals', {}))}
    Key phrases: {', '.join([k[0] for k in event_data.get('keyphrases', [])])}
    Source excerpt (max 1500 chars): {event_data.get('raw_text', '')[:1500]}

    Return ONLY a valid JSON object with these exact keys:
    - what_happened
    - where
    - severity_rationale
    - agency_response
    - outlook

    No markdown. No preamble. JSON only.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        # Parse response
        text = response.text
        # Strip potential markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        digest = json.loads(text.strip())
        increment_quota()
        return digest
    except Exception as e:
        logger.error(f"Error generating Gemini digest: {e}")
        return None

if __name__ == "__main__":
    # Test stub
    import asyncio
    async def test():
        data = {
            "title": "Sawmill Fire",
            "category": "Wildfires",
            "severity_label": "HIGH",
            "severity_score": 0.87,
            "raw_text": "A large fire is burning in Arizona..."
        }
        res = await generate_digest(data)
        print(res)
    
    # asyncio.run(test())
