"""Tests for core/romanize.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.romanize import romanize, latinize, is_cyrillic, MK_CYRILLIC_TO_LATIN


def test_romanize_basic_words():
    assert romanize("добро") == "dobro"
    assert romanize("утро") == "utro"
    assert romanize("вода") == "voda"
    assert romanize("куче") == "kuche"


def test_romanize_special_characters():
    """Test uniquely Macedonian letters: ѓ, ќ, ѕ, џ, љ, њ, ј"""
    assert romanize("ѓубре") == "gjubre"
    assert romanize("ќерка") == "kjerka"
    assert romanize("ѕвезда") == "dzvezda"
    assert romanize("џамија") == "dzhamija"
    assert romanize("љубов") == "ljubov"
    assert romanize("коњ") == "konj"
    assert romanize("јас") == "jas"


def test_romanize_strips_punctuation():
    assert romanize("добро!") == "dobro"
    assert romanize("да,") == "da"
    assert romanize("(не)") == "ne"


def test_romanize_strips_spaces():
    """MMS tokenizer expects no spaces — they're removed."""
    assert romanize("добро утро") == "dobroutro"


def test_romanize_empty():
    assert romanize("") == ""
    assert romanize("123") == ""


def test_latinize_preserves_spaces():
    assert latinize("добро утро") == "dobro utro"


def test_latinize_preserves_case():
    assert latinize("Добро") == "Dobro"
    assert latinize("ДОБРО") == "DOBRO"  # all-caps preserved


def test_latinize_preserves_punctuation():
    assert latinize("Здраво!") == "Zdravo!"
    assert latinize("Како си?") == "Kako si?"


def test_is_cyrillic():
    assert is_cyrillic("добро") is True
    assert is_cyrillic("dobro") is False
    assert is_cyrillic("") is False
    assert is_cyrillic("добро utro") is True  # mixed but majority Cyrillic


def test_mapping_completeness():
    """All 31 Macedonian letters should be in the mapping."""
    mk_alphabet = "абвгдѓежзѕијклљмнњопрстќуфхцчџш"
    for char in mk_alphabet:
        assert char in MK_CYRILLIC_TO_LATIN, f"Missing: {char}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
