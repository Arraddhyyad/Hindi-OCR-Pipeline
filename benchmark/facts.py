"""Fact recall: how many of the page's key facts (names, dates, amounts, plot numbers) the OCR text contains.
The generator stores each page's facts in its label, so no one has to mark them by hand.
exact = the fact is found word for word (after the usual cleaning). close = found with at most small slips (needs rapidfuzz)."""
from .normalize import normalize

try:
    from rapidfuzz import fuzz as _fuzz
except Exception:
    _fuzz = None

CLOSE_THRESHOLD = 85     # out of 100
MIN_LEN_FOR_CLOSE = 4    # very short facts must match exactly


def is_numeric(fact):
    return any(c.isdigit() for c in fact)


def fact_hits(facts, hyp, digits="latin"):
    """Return {"n","exact","close","num_n","num_exact","num_close"} counts for one page."""
    h = normalize(hyp, digits)
    out = dict(n=0, exact=0, close=0, num_n=0, num_exact=0, num_close=0)
    for f in facts or []:
        nf = normalize(f, digits)
        if not nf:
            continue
        exact = nf in h
        close = exact or (_fuzz is not None and len(nf) >= MIN_LEN_FOR_CLOSE
                          and _fuzz.partial_ratio(nf, h) >= CLOSE_THRESHOLD)
        out["n"] += 1
        out["exact"] += exact
        out["close"] += close
        if is_numeric(f):
            out["num_n"] += 1
            out["num_exact"] += exact
            out["num_close"] += close
    return out
