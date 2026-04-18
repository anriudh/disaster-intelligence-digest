import httpx
import trafilatura
import asyncio
from random import uniform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(5)

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
                
                if text:
                    return text
                else:
                    logger.warning(f"Trafilatura returned None for {url}. Using fallback.")
                    return fallback
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}. Using fallback.")
            return fallback

async def scrape_event_sources(event: dict) -> dict:
    """
    Scrapes all sources for a given EONET event and returns the aggregated text.
    """
    title = event.get("title", "")
    description = event.get("description", "")
    fallback = f"{title} {description}".strip()
    
    sources = event.get("sources", [])
    if not sources:
        return {"text": fallback, "source": "fallback"}
    
    # Try the first source first, or we could try all and combine.
    # PRD says "extract article text from EONET source URLs".
    # Usually, one good source is enough, but some events have multiple.
    # Let's try the first successful one for now as a simple strategy.
    
    for source in sources:
        url = source.get("url")
        if url:
            text = await fetch_source_text(url, fallback)
            if text != fallback:
                return {"text": text, "source": url}
    
    return {"text": fallback, "source": "fallback"}

if __name__ == "__main__":
    # Quick manual test
    async def main():
        url = "https://www.nasa.gov/" # Just a sample URL
        fallback = "NASA Fallback"
        text = await fetch_source_text(url, fallback)
        print(f"Scraped length: {len(text)}")
        
    asyncio.run(main())
