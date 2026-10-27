"""Character and word error rates. CER = (substitutions + deletions + insertions) / reference length."""
try:
    from rapidfuzz.distance import Levenshtein as _Lev
except Exception:  # rapidfuzz is optional; the slow path below gives the same numbers
    _Lev = None


def edit_distance(a, b):
    """Levenshtein distance between two sequences (strings or lists)."""
    if _Lev is not None:
        return _Lev.distance(a, b)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def char_errors(ref, hyp):
    """(errors, reference length) counted in characters, spaces included."""
    return edit_distance(ref, hyp), len(ref)


def word_errors(ref, hyp):
    """(errors, reference length) counted in words."""
    r, h = ref.split(), hyp.split()
    return edit_distance(r, h), len(r)


def grapheme_errors(ref, hyp):
    """(errors, reference length) counted in letters as a reader sees them (base letter plus marks)."""
    from .graphemes import graphemes
    return edit_distance(graphemes(ref), graphemes(hyp)), len(graphemes(ref))


def median(values):
    v = sorted(values)
    if not v:
        return 0.0
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


CATASTROPHIC = 0.5   # a page with more than this share of wrong characters counts as a failed read


def rate(errors, length):
    if length == 0:
        return 0.0 if errors == 0 else 1.0
    return errors / length


def corpus_rate(pairs):
    """Rate over many pages: total errors / total reference length (long pages count more, as they should)."""
    e = sum(p[0] for p in pairs)
    n = sum(p[1] for p in pairs)
    return rate(e, n)
