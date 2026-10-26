"""Hindi number, date and amount formatting. Pure functions, no I/O."""
_W = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
      "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस "
      "इकतालीस बयालीस तैंतालीस चौंतालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास "
      "इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
      "इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर "
      "इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी "
      "इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे "
      "इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
assert len(_W) == 100, len(_W)

MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
_DEV = str.maketrans("0123456789", "०१२३४५६७८९")


def to_devanagari_digits(s: str) -> str:
    return str(s).translate(_DEV)


def indian_group(n: int) -> str:
    """450000 -> '4,50,000'."""
    s = str(int(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def number_words(n: int) -> str:
    """Indian-system Hindi words for 0 <= n < 100 crore."""
    if n < 100:
        return _W[n]
    out = []
    for unit, name in ((10_000_000, "करोड़"), (100_000, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        q, n = divmod(n, unit)
        if q:
            out.append(f"{_W[q]} {name}")
    if n:
        out.append(_W[n])
    return " ".join(out)


def amount_words(n: int) -> str:
    return f"{number_words(n)} रुपये मात्र"


def fmt(n, numerals: str) -> str:
    """Format any digit string in the document's numeral style ('latin' | 'devanagari')."""
    return to_devanagari_digits(n) if numerals == "devanagari" else str(n)
