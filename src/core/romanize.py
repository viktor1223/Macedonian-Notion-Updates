"""
Macedonian Cyrillic ↔ Latin transliteration.

Single source of truth for romanization used by the MMS alignment model,
audio validation, and dictionary lookups.
"""

# Standard Macedonian Cyrillic → Latin mapping
# Based on official Macedonian romanization (ISO 9:1995 simplified)
MK_CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'ѓ': 'gj', 'е': 'e',
    'ж': 'zh', 'з': 'z', 'ѕ': 'dz', 'и': 'i', 'ј': 'j', 'к': 'k', 'л': 'l',
    'љ': 'lj', 'м': 'm', 'н': 'n', 'њ': 'nj', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'ќ': 'kj', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c',
    'ч': 'ch', 'џ': 'dzh', 'ш': 'sh',
}

# Reverse mapping (Latin → Cyrillic) for transliteration
# Note: multi-char Latin sequences must be checked longest-first
MK_LATIN_TO_CYRILLIC = {v: k for k, v in sorted(
    MK_CYRILLIC_TO_LATIN.items(), key=lambda x: -len(x[1])
)}


def romanize(text: str) -> str:
    """Transliterate Macedonian Cyrillic to Latin for MMS alignment model.

    Only emits characters the MMS tokenizer can handle (a-z).
    Non-Cyrillic, non-ASCII-alpha characters are dropped.

    >>> romanize("добро утро")
    'dobroutro'
    >>> romanize("ѕвезда")
    'dzvezda'
    """
    return ''.join(
        MK_CYRILLIC_TO_LATIN.get(c, c if c.isascii() and c.isalpha() else '')
        for c in text.lower()
    )


def latinize(text: str) -> str:
    """Transliterate Macedonian Cyrillic to standard Latin script.

    Preserves spaces and punctuation (unlike romanize which strips them).

    >>> latinize("Добро утро!")
    'Dobro utro!'
    """
    result = []
    for c in text:
        lower = c.lower()
        if lower in MK_CYRILLIC_TO_LATIN:
            latin = MK_CYRILLIC_TO_LATIN[lower]
            # Preserve capitalization
            if c.isupper():
                latin = latin.capitalize()
            result.append(latin)
        else:
            result.append(c)
    return ''.join(result)


def is_cyrillic(text: str) -> bool:
    """Check if text is predominantly Macedonian Cyrillic.

    >>> is_cyrillic("добро")
    True
    >>> is_cyrillic("dobro")
    False
    """
    if not text:
        return False
    cyrillic_count = sum(1 for c in text if c.lower() in MK_CYRILLIC_TO_LATIN)
    alpha_count = sum(1 for c in text if c.isalpha())
    return alpha_count > 0 and cyrillic_count / alpha_count > 0.5
