"""Split text into what a reader sees as one letter in Devanagari (a base letter plus its marks, and conjuncts joined by a virama).
Own rules, not the `regex` module, so the numbers are the same on every machine."""
import unicodedata

_VIRAMA = "्"
_JOINERS = {"‌", "‍"}


def graphemes(text):
    clusters = []
    prev = ""
    for ch in text:
        attach = bool(clusters) and (
            unicodedata.category(ch) in ("Mn", "Mc", "Me") or ch in _JOINERS or prev == _VIRAMA
        )
        if attach:
            clusters[-1] += ch
        else:
            clusters.append(ch)
        prev = ch
    return clusters
