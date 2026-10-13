"""Health check for web/research/data.json (rules and format: docs/RESEARCH.md).

Reports: entries missing required or new fields, bad dates, sources without a link, links that do not open, possible
duplicates (similar titles or summaries), and the entries still unverified or open. It changes nothing.

  python docs/research_check.py              (fields, dates, duplicates, statuses)
  python docs/research_check.py --links      (also opens every source link; needs the network)
  python docs/research_check.py --out report.md
"""
import argparse
import difflib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "web" / "research" / "data.json"
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
REQUIRED = ["id", "title", "summary", "topic", "status", "confidence", "sources"]
NEW = ["kind", "lastVerified", "place", "timeline"]
STATUS = {"verified", "unverified", "analysis", "open-question"}
KIND = {"fact", "claim", "analysis"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def open_link(url):
    """(status code or error text, final URL) for one link; GET, as some sites refuse HEAD."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()) as r:
            r.read(2048)
            return r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception as e:  # DNS, timeout, TLS
        return type(e).__name__, url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--links", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    db = json.loads(DATA.read_text(encoding="utf-8"))
    findings = db["findings"]
    out = [f"# Research database check: {len(findings)} entries", ""]
    sec = lambda t: out.extend(["", f"## {t}", ""])

    sec("Fields")
    ids = [f.get("id") for f in findings]
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        out.append(f"- duplicate id {i}")
    for f in findings:
        miss = [k for k in REQUIRED if not f.get(k)]
        if miss:
            out.append(f"- {f.get('id')}: missing {', '.join(miss)}")
        if f.get("status") not in STATUS:
            out.append(f"- {f['id']}: status {f.get('status')!r}")
        if "kind" in f and f["kind"] not in KIND:
            out.append(f"- {f['id']}: kind {f['kind']!r}")
        if f.get("date") and not DATE.match(f["date"]):
            out.append(f"- {f['id']}: date {f['date']!r}")
        if f.get("date") and f["date"][5:] == "01-01":
            out.append(f"- {f['id']}: date {f['date']} (1 January: probably only the year or month is known)")
    cur = db.get("current") or {}
    for it in cur.get("items", []):
        for i in it.get("ids", []):
            if i not in ids:
                out.append(f"- current status '{it.get('label')}' points to a missing entry {i}")
    if cur:
        out.append(f"- current status box: {len(cur.get('items', []))} items, as of {cur.get('asOf')} (re-check them with their entries)")
    no_new = [f["id"] for f in findings if any(k not in f for k in NEW)]
    out.append(f"- without the new fields ({', '.join(NEW)}): {len(no_new)} of {len(findings)}")
    no_date = [f["id"] for f in findings if not f.get("date") and f.get("status") == "verified"]
    out.append(f"- verified but no date: {len(no_date)}: {', '.join(no_date)}")

    sec("Sources")
    srcs = [(f["id"], k, s) for f in findings for k, s in enumerate(f.get("sources") or [])]
    no_url = [(i, s) for i, _, s in srcs if not s.get("url")]
    out.append(f"- {len(srcs)} sources, {len(no_url)} without a link:")
    out += [f"  - {i}: [{s.get('type')}] {s.get('title')}" for i, s in no_url]
    only_ours = [f["id"] for f in findings if f.get("status") == "verified"
                 and all(s.get("type") == "analysis" for s in f.get("sources") or [])]
    if only_ours:
        out.append(f"- verified, but only our own files as sources: {', '.join(only_ours)}")

    if a.links:
        sec("Links")
        urls = sorted({s["url"] for _, _, s in srcs if s.get("url")})
        with ThreadPoolExecutor(8) as ex:
            res = dict(zip(urls, ex.map(open_link, urls)))
        bad = {u: r for u, r in res.items() if r[0] != 200}
        out.append(f"- {len(urls)} distinct links, {len(urls) - len(bad)} open (200), {len(bad)} not:")
        for u, (code, final) in sorted(bad.items(), key=lambda x: str(x[1][0])):
            used = sorted({i for i, _, s in srcs if s.get("url") == u})
            out.append(f"  - {code}: {u} ({', '.join(used)})")
        moved = {u: r[1] for u, r in res.items() if r[0] == 200 and r[1].rstrip("/") != u.rstrip("/")}
        for u, final in moved.items():
            out.append(f"  - redirected: {u} -> {final}")

    sec("Possible duplicates")
    norm = lambda t: re.sub(r"[^a-z0-9 ]", "", (t or "").lower())
    for i in range(len(findings)):
        for j in range(i + 1, len(findings)):
            a1, b1 = findings[i], findings[j]
            r1 = difflib.SequenceMatcher(None, norm(a1["title"]), norm(b1["title"])).ratio()
            r2 = difflib.SequenceMatcher(None, norm(a1["summary"]), norm(b1["summary"])).ratio()
            if r1 > 0.6 or r2 > 0.55:
                out.append(f"- {a1['id']} / {b1['id']} (title {r1:.2f}, summary {r2:.2f}): {a1['title']} | {b1['title']}")

    sec("Still unverified or open")
    for st in ("unverified", "open-question"):
        rows = [f for f in findings if f.get("status") == st]
        out.append(f"- {st} ({len(rows)}):")
        out += [f"  - {f['id']}: {f['title']}" for f in rows]

    text = "\n".join(out) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
