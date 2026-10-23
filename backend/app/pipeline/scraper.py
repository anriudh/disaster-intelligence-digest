import httpx
import trafilatura
import asyncio
from random import uniform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(5)

# Text that JavaScript-only pages and bot walls leave behind instead of an article.
# trafilatura returns it as if it were content (99/100 committed rows, see docs/audit).
BOILERPLATE_PHRASES = (
    "you need to enable javascript to run this app",
    "please enable javascript",
    "javascript is disabled",
    "javascript is required",
    "enable javascript and cookies to continue",
    "checking your browser before accessing",
)
# Real articles that merely mention one of the phrases are longer than this
BOILERPLATE_MAX_CHARS = 300

def is_boilerplate(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return len(lowered) < BOILERPLATE_MAX_CHARS and any(p in lowered for p in BOILERPLATE_PHRASES)

async def fetch_source_text(url: str, fallback: str) -> str:
    """
    Extracts clean text from a URL using trafilatura.
    If extraction fails, returns the fallback string.
    """
    async with SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                # trafilatura.extract returns None if it fails to extract meaningful text
                text = trafilatura.extract(response.text)
                
                # Apply jitter to be polite to servers
                await asyncio.sleep(uniform(1.5, 3.5))
                
                if not text:
                    logger.warning(f"Trafilatura returned None for {url}. Using fallback.")
                    return fallback
                if is_boilerplate(text):
                    logger.warning(f"Rejected boilerplate text from {url}. Using fallback.")
                    return fallback
                return text
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}. Using fallback.")
            return fallback

async def scrape_event_sources(event: dict) -> dict:
    """
    Scrapes all sources for a given EONET event and returns the aggregated text.

    quality is "extracted" when the text came from a source page, "fallback"
    when it is the event's own title and description.
    """
    title = event.get("title") or ""
    description = event.get("description") or ""
    fallback = f"{title} {description}".strip()
    
    sources = event.get("sources") or []
    if not sources:
        return {"text": fallback, "source": "fallback", "quality": "fallback"}
    
    # Try the first source first, or we could try all and combine.
    # PRD says "extract article text from EONET source URLs".
    # Usually, one good source is enough, but some events have multiple.
    # Let's try the first successful one for now as a simple strategy.
    
    for source in sources:
        url = source.get("url")
        if url:
            text = await fetch_source_text(url, fallback)
            if text != fallback:
                return {"text": text, "source": url, "quality": "extracted"}
    
    return {"text": fallback, "source": "fallback", "quality": "fallback"}

if __name__ == "__main__":
    # Quick manual test
    async def main():
        url = "https://www.nasa.gov/" # Just a sample URL
        fallback = "NASA Fallback"
        text = await fetch_source_text(url, fallback)
        print(f"Scraped length: {len(text)}")
        
    asyncio.run(main())
