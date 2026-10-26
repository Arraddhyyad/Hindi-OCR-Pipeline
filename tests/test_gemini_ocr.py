import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import sys, asyncio, tempfile; sys.path.insert(0, ".")
from pipeline.step8_evaluate import GeminiOCR
class R: text = " नमस्ते "
class M:
    n = 0
    async def generate_content(self, **kw):
        M.n += 1
        if M.n <= 2: raise RuntimeError("429 RESOURCE_EXHAUSTED retry in 0.1s")
        assert kw["contents"][0].inline_data.data == b"img"; return R()
class C:
    class aio: models = M()
d = tempfile.mkdtemp(); o = GeminiOCR(client=C(), cache_dir=d)
print(asyncio.run(o.read(b"img")), "calls:", M.n); print(asyncio.run(o.read(b"img")), "calls after cache hit:", M.n)
