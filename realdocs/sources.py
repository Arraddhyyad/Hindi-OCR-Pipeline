"""Find and download Hindi documents that are legal to reuse.

Two sources: Internet Archive (scanned books, gazettes, court and land papers) and Wikimedia Commons (single scans).
Every download is recorded in sources.csv with its URL and licence. Items whose licence is not clearly open are skipped."""
import csv
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

UA = {"User-Agent": "HindiOCR-research/1.0 (https://github.com/Arraddhyyad/Hindi-OCR-Pipeline; university research, low rate)"}
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_META = "https://archive.org/metadata/{}"
IA_FILE = "https://archive.org/download/{}/{}"
COMMONS = "https://commons.wikimedia.org/w/api.php"
FIELDS = ["id", "source", "source_url", "file_url", "title", "license", "license_url", "local_path", "sha256", "fetched_at"]

# Wikimedia licence names we accept. Anything else is skipped.
OPEN_COMMONS = ("public domain", "pd", "cc0", "cc by", "cc-by")


def open_license(license_url="", status="", short_name=""):
    """True only when the item is clearly public domain or openly licensed."""
    u, s, n = (license_url or "").lower(), (status or "").upper(), (short_name or "").lower()
    if "publicdomain" in u or "/zero/" in u or "/by/" in u or "/by-sa/" in u:
        return True
    if s == "NOT_IN_COPYRIGHT":
        return True
    return bool(n) and any(n.startswith(p) for p in OPEN_COMMONS)


def _get(url, params=None, retries=3, wait=2.0, stream=False):
    last = "no response"
    for k in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60, stream=stream)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (429, 503):
                time.sleep(wait * (k + 2))
                continue
            break   # 403, 404 and the like will not get better by retrying
        except requests.RequestException as e:
            last = type(e).__name__
            time.sleep(wait * (k + 1))
    raise RuntimeError(f"{last} for {url}")


def ia_search(query, rows=50):
    """Internet Archive items matching `query`, Hindi texts only."""
    q = f"({query}) AND mediatype:texts AND (language:hin OR language:Hindi OR language:hi)"
    r = _get(IA_SEARCH, {"q": q, "fl[]": ["identifier", "title"], "rows": rows, "output": "json"})
    return r.json()["response"]["docs"]


def ia_pick_pdf(files, max_mb=60):
    """Smallest sensible PDF in an item's file list (page scans, not the full-size originals)."""
    pdfs = [f for f in files if f.get("name", "").lower().endswith(".pdf")]
    pdfs = [f for f in pdfs if int(f.get("size") or 0) <= max_mb * 1_000_000]
    return sorted(pdfs, key=lambda f: int(f.get("size") or 0))[-1]["name"] if pdfs else None


def ia_item(identifier):
    """Metadata for one item: (title, licence_url, copyright status, pdf file name, free-text rights)."""
    m = _get(IA_META.format(identifier)).json()
    md = m.get("metadata", {})
    return (md.get("title", identifier), md.get("licenseurl", ""),
            md.get("possible-copyright-status", ""), ia_pick_pdf(m.get("files", [])),
            str(md.get("rights", ""))[:200])


def looks_hindi(text):
    """Commons search has no language filter, so keep a file only if its title, description or categories
    contain Devanagari or name Hindi / Devanagari."""
    t = (text or "").lower()
    return any("\u0900" <= ch <= "\u097f" for ch in t) or "hindi" in t or "devanagari" in t


def commons_search(query, limit=30):
    """Wikimedia Commons scans matching `query`, with licence info."""
    r = _get(COMMONS, {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                       "gsrsearch": query, "gsrlimit": limit, "prop": "imageinfo",
                       "iiprop": "url|extmetadata|mime", "iiurlwidth": 2400})
    out = []
    for p in (r.json().get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if not ii.get("mime", "").startswith("image/"):
            continue
        em = ii.get("extmetadata", {})
        text = p.get("title", "") + " " + (em.get("ImageDescription") or {}).get("value", "") + " " + (em.get("Categories") or {}).get("value", "")
        if not looks_hindi(text):
            continue
        out.append({"title": p.get("title", ""), "url": ii.get("thumburl") or ii.get("url"),
                    "page": ii.get("descriptionurl", ""),
                    "license": (em.get("LicenseShortName") or {}).get("value", ""),
                    "license_url": (em.get("LicenseUrl") or {}).get("value", "")})
    return out


def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True) as r, open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
            h.update(chunk)
    tmp.replace(dest)
    return h.hexdigest()


def load_sources(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_sources(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def fetch(queries, out_dir, max_items=40, pause=1.5, log=print):
    """Search both sources for each query and download open-licensed items. Safe to re-run: known items are skipped."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = out_dir / "sources.csv"
    rows = load_sources(sp)
    have = {r["source_url"] for r in rows}
    stats = {"downloaded": 0, "skipped_licence": 0, "skipped_known": 0}
    skipped = []
    for q in queries:
        for d in ia_search(q):
            ident = d["identifier"]
            url = f"https://archive.org/details/{ident}"
            if url in have:
                stats["skipped_known"] += 1
                continue
            if len(rows) >= max_items:
                break
            title, lic_url, status, pdf, rights = ia_item(ident)
            time.sleep(pause)
            if not open_license(lic_url, status) or not pdf:
                stats["skipped_licence"] += 1
                why = "no pdf under size limit" if open_license(lic_url, status) else "licence not clearly open"
                skipped.append({"id": ident, "title": title, "why": why, "license_url": lic_url,
                                "copyright_status": status, "rights": rights, "has_pdf": bool(pdf), "url": url})
                log(f"skip ({why}): {ident}")
                continue
            dest = out_dir / "raw" / f"ia_{ident}.pdf"
            try:
                sha = _download(IA_FILE.format(ident, pdf), dest)
            except Exception as e:
                stats["failed"] = stats.get("failed", 0) + 1
                log(f"download failed, skipping {ident}: {e}")
                continue
            rows.append({"id": f"ia_{ident}", "source": "internet_archive", "source_url": url,
                         "file_url": IA_FILE.format(ident, pdf), "title": title,
                         "license": status or "open", "license_url": lic_url, "local_path": str(dest),
                         "sha256": sha, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            have.add(url)
            stats["downloaded"] += 1
            log(f"got {ident}")
            time.sleep(pause)
        for c in commons_search(q):
            if c["page"] in have:
                stats["skipped_known"] += 1
                continue
            if len(rows) >= max_items:
                break
            if not open_license(c["license_url"], short_name=c["license"]):
                stats["skipped_licence"] += 1
                continue
            ext = Path(c["url"].split("?")[0]).suffix.lower() or ".jpg"
            cid = "wc_" + hashlib.sha1(c["page"].encode()).hexdigest()[:10]
            dest = out_dir / "raw" / (cid + ext)
            try:
                sha = _download(c["url"], dest)
            except Exception as e:
                stats["failed"] = stats.get("failed", 0) + 1
                log(f"download failed, skipping {cid}: {e}")
                continue
            rows.append({"id": cid, "source": "wikimedia_commons", "source_url": c["page"], "file_url": c["url"],
                         "title": c["title"], "license": c["license"], "license_url": c["license_url"],
                         "local_path": str(dest), "sha256": sha,
                         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            have.add(c["page"])
            stats["downloaded"] += 1
            log(f"got {cid}")
            time.sleep(pause)
        save_sources(sp, rows)
    save_sources(sp, rows)
    if skipped:   # so you can see WHY items were left out and decide for yourself
        with open(out_dir / "skipped.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(skipped[0]))
            w.writeheader()
            w.writerows(skipped)
    return stats
