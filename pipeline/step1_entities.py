"""STEP 1 - entity graph: every fact (names, ages, plot, boundaries, amount in digits and words, dates) is decided in code before any text exists.
"""
import random
from .hindi_numbers import MONTHS, indian_group, amount_words, fmt

MALE = ["रामेश्वर", "सुरेश", "अशोक", "विजय", "महेश", "राजेंद्र", "हरिओम", "देवेंद्र", "ओमप्रकाश", "सत्यनारायण",
        "मोहन", "गोपाल", "रमाकांत", "बृजेश", "अनिल", "संजय", "प्रदीप", "दिनेश", "कमलेश", "जगदीश", "रामप्रकाश",
        "शिवकुमार", "छोटेलाल", "मुन्नालाल", "भगवानदीन", "रामआसरे", "बाबूराम", "कालीचरण", "नंदलाल", "हरिशंकर",
        "रघुवीर", "लक्ष्मण", "श्यामलाल", "चंद्रभान", "बलराम", "मनोज", "रमेश", "सुभाष", "वीरेंद्र", "उमाशंकर"]
FEMALE = ["सुनीता", "अनीता", "मीना", "कमला", "शांति", "गीता", "रेखा", "पूजा", "सरोजनी", "उर्मिला", "कुसुम",
          "सावित्री", "विमला", "ममता", "रामदुलारी", "शकुंतला", "कौशल्या", "सीमा", "आशा", "प्रेमलता"]
SURNAMES = ["यादव", "वर्मा", "शर्मा", "गुप्ता", "सिंह", "मिश्रा", "पांडेय", "तिवारी", "चौहान", "कुशवाहा", "मौर्य",
            "पटेल", "अग्रवाल", "श्रीवास्तव", "दुबे", "शुक्ला", "राठौर", "प्रजापति", "निषाद", "जायसवाल", "त्रिपाठी", "सक्सेना"]
DISTRICTS = ["लखनऊ", "कानपुर नगर", "वाराणसी", "आगरा", "मेरठ", "गाजियाबाद", "प्रयागराज", "बरेली", "अलीगढ़",
             "मुरादाबाद", "सहारनपुर", "गोरखपुर", "उन्नाव", "सीतापुर", "रायबरेली", "बाराबंकी", "हरदोई", "झाँसी", "मथुरा", "बलिया"]
TEHSILS = ["सदर", "सरोजनीनगर", "मोहनलालगंज", "बक्शी का तालाब", "सदर तहसील", "पश्चिम", "पूर्व", "कोतवाली", "सलोन", "मिल्कीपुर"]
VILLAGES = ["रसूलपुर", "शिवपुर", "भगवंतनगर", "नगरिया", "बहादुरपुर", "हसनपुर", "गोपालपुर", "रामनगर", "सराय माधो",
            "दौलतपुर", "मोहम्मदपुर", "चंदौली", "बरौली", "पिपरी", "कमालपुर", "नौगाँव", "अमरपुर", "तिलकपुर", "लालपुर", "मदारपुर"]
PAYMENT = ["नकद", "बैंक ड्राफ्ट", "चेक", "नकद एवं चेक"]
BANKS = ["भारतीय स्टेट बैंक", "पंजाब नेशनल बैंक", "बैंक ऑफ बड़ौदा", "इलाहाबाद बैंक", "यूनियन बैंक ऑफ इंडिया"]


def _person(rng, female=False, used=None):
    used = used if used is not None else set()
    while True:
        first = rng.choice(FEMALE if female else MALE)
        last = rng.choice(SURNAMES)
        full = f"{first} {last}"
        if full not in used:
            used.add(full)
            return full


def _party(rng, used, numerals):
    female = rng.random() < 0.2
    name = _person(rng, female, used)
    if female:
        rel_word = rng.choice(["पत्नी", "पुत्री"])
        rel_name = _person(rng, False, used)
        title = "श्रीमती"
    else:
        rel_word, rel_name, title = "पुत्र", _person(rng, False, used), "श्री"
    return {"name": name, "title": title, "female": female, "relation": rel_word, "relative": rel_name,
            "age": fmt(rng.randint(24, 78), numerals)}


def generate_entity_graph(rng: random.Random, cfg: dict) -> dict:
    numerals = rng.choice(cfg.get("numerals", ["latin"]))
    used = set()
    district, tehsil, village = rng.choice(DISTRICTS), rng.choice(TEHSILS), rng.choice(VILLAGES)
    seller, buyer = _party(rng, used, numerals), _party(rng, used, numerals)
    w1, w2 = _person(rng, False, used), _person(rng, False, used)
    neighbours = [_person(rng, False, used) for _ in range(4)]

    d, m, y = rng.randint(1, 28), rng.randrange(12), rng.randint(1975, 2010)
    date_text = f"{fmt(d, numerals)} {MONTHS[m]} {fmt(y, numerals)}"

    if rng.random() < 0.6:
        ptype = "agricultural"
        khasra = fmt(rng.randint(12, 989), numerals)
        area = f"{fmt(rng.randint(1, 9), numerals)} बीघा {fmt(rng.randint(1, 19), numerals)} बिस्वा"
        prop_label = f"खसरा संख्या {khasra}"
    else:
        ptype = "plot"
        khasra = fmt(rng.randint(3, 480), numerals)
        area = f"{fmt(rng.choice([60, 75, 90, 100, 120, 150, 200, 250]), numerals)} वर्ग मीटर"
        prop_label = f"प्लॉट संख्या {khasra}"

    amount = rng.choice([85000, 120000, 185000, 240000, 310000, 450000, 575000, 820000, 1200000, 1850000])
    amount_text = f"{fmt(indian_group(amount), numerals)}/-"
    words_text = amount_words(amount)
    pay = rng.choice(PAYMENT)
    if pay in ("चेक", "नकद एवं चेक"):
        pay_text = f"{pay} संख्या {fmt(rng.randint(100000, 999999), numerals)} ({rng.choice(BANKS)})"
    elif pay == "बैंक ड्राफ्ट":
        pay_text = f"बैंक ड्राफ्ट संख्या {fmt(rng.randint(100000, 999999), numerals)} ({rng.choice(BANKS)})"
    else:
        pay_text = "नकद"
    stamp = int(amount * rng.choice([0.05, 0.07]))
    stamp_text = f"{fmt(indian_group(stamp), numerals)}/-"

    graph = {
        "doc_type": "sale_deed", "language": "hi", "numerals": numerals,
        "date": date_text, "place": district, "district": district, "tehsil": tehsil, "village": village,
        "seller": seller, "buyer": buyer, "property_type": ptype, "property_label": prop_label,
        "khasra": khasra, "area": area,
        "boundaries": dict(zip(["पूर्व", "पश्चिम", "उत्तर", "दक्षिण"], neighbours)),
        "amount": amount, "amount_text": amount_text, "amount_words": words_text,
        "payment": pay_text, "stamp_duty": stamp_text,
        "witnesses": [{"name": w1, "village": rng.choice(VILLAGES)}, {"name": w2, "village": village}],
        "registration": {"no": fmt(rng.randint(1, 9999), numerals), "year": fmt(y, numerals),
                         "book": fmt(rng.randint(1, 4), numerals), "volume": fmt(rng.randint(1, 80), numerals),
                         "page": fmt(rng.randint(1, 420), numerals), "office": f"उप-निबंधक कार्यालय, {district}"},
    }
    return graph


def required_facts(g: dict) -> list:
    """Exact strings that must appear verbatim in the written document body."""
    f = [g["date"], g["village"], g["tehsil"], g["district"], g["khasra"], g["area"], g["amount_text"],
         g["amount_words"], g["payment"], g["stamp_duty"], g["seller"]["name"], g["buyer"]["name"],
         g["seller"]["relative"], g["buyer"]["relative"]]
    f += list(g["boundaries"].values())
    f += [w["name"] for w in g["witnesses"]]
    return f
