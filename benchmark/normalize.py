"""Clean text the same way on both sides before comparing, so we only count real mistakes."""
import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF], None)
_DEV_DIGITS = {ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")}
_SPACES = re.compile(r"\s+")


def normalize(text, digits="latin", strip_zero_width=True):
    """NFC form, no zero-width marks, one space between words.
    digits="latin" turns Devanagari digits into 0-9 (pages use both styles and OCR tools pick either).
    Use digits="keep" to leave them alone."""
    t = unicodedata.normalize("NFC", text or "")
    if strip_zero_width:
        t = t.translate(_ZERO_WIDTH)
    if digits == "latin":
        t = t.translate(_DEV_DIGITS)
    return _SPACES.sub(" ", t).strip()
