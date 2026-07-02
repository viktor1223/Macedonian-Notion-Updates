"""Tests for dictionary lookup from enrich_csv.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_dict_lookup_basic(tmp_path):
    """Test dictionary lookup with a minimal dictionary."""
    import json
    # Create a minimal test dictionary
    test_dict = {
        "вода": {"pos": "Noun", "gender": "feminine", "english": "water", "roman": "voda"},
        "добро": {"pos": "Adverb", "english": "well"},
        "оди": {"pos": "Verb", "english": ["to go, walk", "to suit, fit"],
                "forms": {"1sg_present": "одам"}},
    }
    dict_path = tmp_path / "test_dict.json"
    dict_path.write_text(json.dumps(test_dict, ensure_ascii=False))

    # Monkeypatch the dictionary path
    import enrich_csv
    original_path = enrich_csv.DICTIONARY_PATH
    enrich_csv.DICTIONARY_PATH = dict_path
    enrich_csv._dictionary_cache = None  # Reset cache

    try:
        entry = enrich_csv.dict_lookup("вода")
        assert entry is not None
        assert entry["pos"] == "Noun"
        assert entry["gender"] == "feminine"
        assert entry["english"] == "water"

        entry2 = enrich_csv.dict_lookup("оди")
        assert entry2 is not None
        assert entry2["pos"] == "Verb"

        # Not found
        assert enrich_csv.dict_lookup("непостои") is None
    finally:
        enrich_csv.DICTIONARY_PATH = original_path
        enrich_csv._dictionary_cache = None


def test_phrase_lookup_stop_words(tmp_path):
    """Test that stop words are stripped from phrases."""
    import json
    test_dict = {
        "маса": {"pos": "Noun", "english": "table"},
        "година": {"pos": "Noun", "english": "year"},
    }
    dict_path = tmp_path / "test_dict.json"
    dict_path.write_text(json.dumps(test_dict, ensure_ascii=False))

    import enrich_csv
    original_path = enrich_csv.DICTIONARY_PATH
    enrich_csv.DICTIONARY_PATH = dict_path
    enrich_csv._dictionary_cache = None

    try:
        # "на маса" → strip "на" (preposition) → lookup "маса"
        entry, head = enrich_csv.phrase_lookup("на маса")
        assert entry is not None
        assert head == "маса"
        assert entry["pos"] == "Noun"

        # "следната година" → strip nothing, lookup "година" (rightmost content word)
        entry2, head2 = enrich_csv.phrase_lookup("следната година")
        assert entry2 is not None
        assert head2 == "година"
    finally:
        enrich_csv.DICTIONARY_PATH = original_path
        enrich_csv._dictionary_cache = None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
