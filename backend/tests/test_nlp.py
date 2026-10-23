import pytest

pytest.importorskip("spacy")
pytest.importorskip("keybert")
pytest.importorskip("sentence_transformers")

from backend.app.pipeline.nlp import extract_entities, extract_signals, extract_keyphrases
from backend.app.pipeline.embeddings import get_embeddings

pytestmark = pytest.mark.model

def test_spacy_ner():
    text = "A large wildfire is burning near Flagstaff, Arizona, managed by the US Forest Service."
    entities = extract_entities(text)
    # Flagstaff and Arizona should be GPE/LOC
    labels = [ent[1] for ent in entities]
    assert "GPE" in labels or "LOC" in labels
    
def test_regex_signals_success():
    text = "The fire has consumed 12,500 acres and is 45% contained."
    signals = extract_signals(text)
    assert signals["acres_burned"] == 12500
    assert signals["pct_contained"] == 45

def test_regex_signals_absent():
    text = "There is a flood in the valley."
    signals = extract_signals(text)
    assert signals["acres_burned"] is None
    assert signals["wind_speed_mph"] is None

def test_keybert_keyphrases():
    text = """
    Wildfires are unplanned fires that burn in natural areas like forests, grasslands, or prairies. 
    These fires are often caused by human activity or a natural phenomenon such as lightning, 
    and they can happen at any time or anywhere. In 4 out of 5 wildfires, people are the cause. 
    """
    keyphrases = extract_keyphrases(text, top_n=5)
    assert len(keyphrases) == 5
    for phrase, score in keyphrases:
        assert isinstance(phrase, str)
        assert isinstance(score, float)

def test_embeddings_output():
    text = "The Sawmill Fire in Arizona is growing rapidly."
    vector = get_embeddings(text)
    assert isinstance(vector, list)
    assert len(vector) == 384
    for val in vector:
        assert isinstance(val, float)
