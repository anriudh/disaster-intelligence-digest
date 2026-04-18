import spacy
import re
import json
from keybert import KeyBERT
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load spaCy model
try:
    nlp = spacy.load("en_core_web_md")
except Exception as e:
    logger.error(f"Failed to load spaCy model: {e}")
    nlp = None

# Initialize KeyBERT
try:
    kw_model = KeyBERT(model="all-MiniLM-L6-v2")
except Exception as e:
    logger.error(f"Failed to load KeyBERT model: {e}")
    kw_model = None

REGEX_PATTERNS = {
    "acres_burned": r"([\d,]+)\s*acres",
    "pct_contained": r"(\d+)\s*%?\s*contained",
    "wind_speed_mph": r"(\d+)\s*(mph|knots|km/h)",
    "storm_category": r"Category\s*([1-5])",
    "volcano_alert": r"Alert Level[:\s]*(Normal|Advisory|Watch|Warning)",
    "persons_affected": r"([\d,]+)\s*(displaced|evacuated|affected|homeless)",
    "casualties": r"(\d+)\s*(dead|killed|injured|casualties|fatalities)",
    "magnitude": r"M\s*(\d+\.?\d*)\s*earthquake",
}

def extract_entities(text: str):
    """
    Extracts GPE, LOC, ORG, DATE, CARDINAL, QUANTITY entities using spaCy.
    Returns a list of (text, label) tuples.
    """
    if not nlp or not text:
        return []
    
    doc = nlp(text)
    entities = []
    allowed_labels = {"GPE", "LOC", "ORG", "DATE", "CARDINAL", "QUANTITY"}
    
    for ent in doc.ents:
        if ent.label_ in allowed_labels:
            entities.append((ent.text, ent.label_))
    
    return entities

def extract_signals(text: str):
    """
    Extracts signals from text using regex patterns.
    Returns a dictionary of found signals.
    """
    signals = {}
    if not text:
        return signals

    for signal_name, pattern in REGEX_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Clean up the value (remove commas, handle numeric conversion if possible)
            val = match.group(1)
            # Try to convert to float/int if it's numeric
            clean_val = val.replace(",", "")
            try:
                if "." in clean_val:
                    signals[signal_name] = float(clean_val)
                else:
                    signals[signal_name] = int(clean_val)
            except ValueError:
                signals[signal_name] = val
        else:
            signals[signal_name] = None
            
    return signals

def extract_keyphrases(text: str, top_n=5):
    """
    Extracts top N keyphrases using KeyBERT.
    Returns a list of (phrase, score) tuples.
    """
    if not kw_model or not text or len(text.split()) < 5:
        return []
    
    try:
        keyphrases = kw_model.extract_keywords(text, keyphrase_ngram_range=(1, 2), stop_words='english', top_n=top_n)
        return keyphrases
    except Exception as e:
        logger.error(f"Error extracting keyphrases: {e}")
        return []

def run_nlp_pipeline(text: str):
    """
    Runs the full NLP pipeline on the given text.
    """
    return {
        "entities": extract_entities(text),
        "signals": extract_signals(text),
        "keyphrases": extract_keyphrases(text)
    }

if __name__ == "__main__":
    sample_text = """
    The Sawmill Fire in Arizona has burned 5000 acres and is 30% contained. 
    Responding agencies include the Arizona State Forestry. 
    The fire started on June 12, 2025. 
    Approximately 200 persons affected were evacuated.
    """
    results = run_nlp_pipeline(sample_text)
    print(json.dumps(results, indent=2))
