"""List what is inside the dataset zips without extracting them.
Run:  python3 handwriting/inspect_datasets.py ~/Downloads
Writes inspect_report.txt next to where you run it; send me that file."""
import sys, os, zipfile, collections, glob, io

root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/Downloads")
pats = ["Page_Level_Hindi_*.zip", "Word_Level_Hindi_*.zip", "National_Manuscript_Mission*.zip"]
out = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)

for pat in pats:
    for zp in sorted(glob.glob(os.path.join(root, pat))):
        p("=" * 70); p(os.path.basename(zp), f"{os.path.getsize(zp)/1e6:.0f} MB")
        try:
            z = zipfile.ZipFile(zp)
        except Exception as e:
            p("  cannot open:", e); continue
        names = [n for n in z.namelist() if not n.endswith("/")]
        p("  files:", len(names))
        ext = collections.Counter(os.path.splitext(n)[1].lower() for n in names)
        p("  by type:", dict(ext))
        dirs = collections.Counter("/".join(n.split("/")[:2]) for n in names)
        p("  top folders:", dict(dirs.most_common(8)))
        p("  first names:", names[:6])
        for n in names:
            if n.lower().endswith((".txt", ".json", ".csv")) and z.getinfo(n).file_size < 5_000_000:
                txt = z.read(n)[:400].decode("utf8", "replace").replace("\n", " | ")
                p("  sample text file:", n, "->", txt); break
        for n in names:
            if n.lower().endswith((".png", ".jpg", ".jpeg")):
                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(z.read(n))); p("  sample image:", n, im.size)
                except Exception as e:
                    p("  sample image:", n, "(size check skipped:", e, ")")
                break
open("inspect_report.txt", "w", encoding="utf8").write("\n".join(out))
p("\nwrote inspect_report.txt")
