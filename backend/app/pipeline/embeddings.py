from sentence_transformers import SentenceTransformer
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load model
try:
    # all-MiniLM-L6-v2 produces 384-dimensional embeddings
    model = SentenceTransformer("all-MiniLM-L6-v2")
except Exception as e:
    logger.error(f"Failed to load sentence-transformer model: {e}")
    model = None

def get_embeddings(text: str):
    """
    Encodes text into a 384-dimensional vector.
    Returns a list of floats.
    """
    if not model or not text:
        return []
    
    try:
        # result is a numpy array, convert to list
        embeddings = model.encode(text)
        return embeddings.tolist()
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        return []

if __name__ == "__main__":
    sample_text = "The Sawmill Fire in Arizona is growing rapidly."
    vector = get_embeddings(sample_text)
    print(f"Vector length: {len(vector)}")
    print(f"First 5 values: {vector[:5]}")
