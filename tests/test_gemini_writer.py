import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
"""Exercises GeminiWriter's JSON parsing, fact check, retry and cache with a fake client (no network)."""
import sys, json, random, asyncio, tempfile; sys.path.insert(0, ".")
from pipeline.step1_entities import generate_entity_graph; from pipeline.step2_text import *
rng = random.Random(9); g = generate_entity_graph(rng, {"numerals": ["devanagari"]})
good = json.dumps({"paragraphs": TemplateWriter().write(g, random.Random(1), 250).paragraphs}, ensure_ascii=False)
bad = json.dumps({"paragraphs": [{"kind": "title", "text": "बैनामा"}, {"kind": "body", "text": "कुछ भी"}]}, ensure_ascii=False)
class R:  # response
    def __init__(s, t): s.text = t
class Models:
    def __init__(s, seq): s.seq, s.calls, s.prompts = seq, 0, []
    async def generate_content(s, model, contents, config):
        s.prompts.append(contents); t = s.seq[min(s.calls, len(s.seq) - 1)]; s.calls += 1
        if t == "429": raise RuntimeError("429 RESOURCE_EXHAUSTED retry in 0.1s")
        return R(t)
class Client:
    def __init__(s, seq): s.m = Models(seq); s.aio = type("A", (), {"models": s.m})()
for name, seq, expect in [("ok first try", [good], 1), ("retry after missing facts", [bad, good], 2), ("rate limit then ok", ["429", good], 1)]:
    c = Client(seq); w = GeminiWriter("fake", client=c, cache_dir=tempfile.mkdtemp())
    d = asyncio.run(w.awrite(g, 1, 250)); assert d.attempts == expect and not missing_facts(g, d), name
    print("PASS", name, "| api calls:", c.m.calls, "| retry prompt names missing facts:", any("missing these exact" in p for p in c.m.prompts))
c = Client([bad]); w = GeminiWriter("fake", client=c, max_attempts=2)
try: asyncio.run(w.awrite(g, 1, 250)); print("FAIL")
except RuntimeError as e: print("PASS gives up cleanly:", str(e)[:60])
