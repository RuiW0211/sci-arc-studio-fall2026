"""Fetch an IRS 990 'visual render' from ProPublica and flatten it to text.

ProPublica's full_text URL 302s to a signed S3 object; curl follows it fine
with --compressed, which the handoff assumed needed a browser.
"""
import html, re, subprocess, sys, os

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

def fetch(object_id, form="IRS990", cache=True):
    path = f"{object_id}_{form}.html"
    if not (cache and os.path.exists(path) and os.path.getsize(path) > 2000):
        url = f"https://projects.propublica.org/nonprofits/full_text/{object_id}/{form}"
        subprocess.run(["curl", "-sL", "--compressed", "-m", "60", "-A", UA, "-o", path, url],
                       check=True)
    return open(path, encoding="utf-8", errors="ignore").read()

def flatten(raw):
    t = re.sub(r"(?s)<(script|style).*?</\1>", " ", raw)
    t = re.sub(r"(?i)</(td|th|tr|div|p|table)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in t.split("\n")]
    return [l for l in lines if l]

def section(lines, start_pat, end_pat, pad=0):
    s = e = None
    for i, l in enumerate(lines):
        if s is None and re.search(start_pat, l, re.I):
            s = max(0, i - pad)
        elif s is not None and re.search(end_pat, l, re.I):
            e = i
            break
    return lines[s:e] if s is not None else []

if __name__ == "__main__":
    oid = sys.argv[1]
    form = sys.argv[2] if len(sys.argv) > 2 else "IRS990"
    L = flatten(fetch(oid, form))
    print(f"[{len(L)} lines]")
    if len(sys.argv) > 3:
        a, b = sys.argv[3], sys.argv[4]
        for l in section(L, a, b):
            print(l)
    else:
        print("\n".join(L))
