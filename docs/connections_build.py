"""Build web/connections/data.json from web/research/data.json (user, 2026-10-12: the Connection page shows how the
research entries are related; only relations that are in the data, never guessed).

Three kinds of link, each with the evidence the page shows:
  mention  an entry's text names another entry's id                     (the sentence)
  actor    an entry's text names a person or organisation (ACTORS)      (the sentence)
           a Media entry's speaker is one of them                       (the speaker line)
  subject  a Media entry belongs to a subject (our grouping)            (the subject)
  source   two entries cite the same source link                        (the source title; off by default on the page)

Rerun after changing the research data or ACTORS:
  python docs/connections_build.py            (writes the file, prints a review of every actor's matches)
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "research" / "data.json"
OUT = ROOT / "web" / "connections" / "data.json"

# People and organisations. Each pattern is matched (case-sensitive unless (?i) is given) in an entry's title,
# summary, details and, for Media, the speaker, role and quote; not in source titles or publication names, which say
# who reported, not who acted. Add an alias only after reading the entries it would match (the review below).
ACTORS = [
    # public bodies
    ("cra", "CRA", "org", "Community Redevelopment Agency of Los Angeles (to 2012)",
     r"\bCRA\b(?!/|'s successor| successor)|Community Redevelopment Agency"),   # "CRA successor agency" is CRA/LA
    ("crala", "CRA/LA", "org", "CRA/LA, the successor agency (Designated Local Authority)",
     r"CRA/LA|[Ss]uccessor agency|Designated Local Authority"),
    ("oversight", "Oversight Board", "org", "CRA/LA Oversight Board", r"(?i)oversight board"),
    ("city", "City of Los Angeles", "org", "The City (council, attorney, planning)",
     r"City of Los Angeles|\bthe City\b|\bCity's\b|City Council|Council File|City Attorney|City Planning|\bLADBS\b"),
    ("hcd", "HCD", "org", "California Department of Housing and Community Development", r"\bHCD\b"),
    ("recpark", "Recreation and Parks", "org", "LA Department / Board of Recreation and Parks", r"Recreation and Parks"),
    # developers, owners, operators
    ("alp", "Angels Landing Partners", "org", "Angels Landing Partners (Peebles, MacFarlane, Claridge)",
     r"Angels Landing Partners|\bALP\b"),
    ("bha", "Bunker Hill Associates", "org", "Bunker Hill Associates, California Plaza developer", r"Bunker Hill Associates"),
    ("metro", "Metropolitan Structures", "org", "Metropolitan Structures, California Plaza partner", r"Metropolitan Structures"),
    ("claridge", "Claridge Properties", "org", "Claridge Properties, ALP member", r"Claridge"),
    ("cim", "CIM Group", "org", "CIM Group, owner of Two California Plaza", r"CIM Group"),
    ("trigild", "Trigild", "org", "Trigild, receiver of One California Plaza", r"Trigild"),
    ("acs", "ACS Infrastructure", "org", "ACS, Angels Flight operator", r"ACS Infrastructure|ACS Group|\bACS agreement"),
    ("moca", "MOCA", "org", "Museum of Contemporary Art", r"\bMOCA\b|Museum of Contemporary Art"),
    ("dtla", "DTLA Alliance", "org", "Downtown Center BID, site upkeep", r"DTLA Alliance"),
    ("cca_assoc", "Central City Association", "org", "Downtown business group", r"Central City Association"),
    ("afrf", "Angels Flight Railway Foundation", "org", "Angels Flight Railway Foundation", r"Angels Flight Railway Foundation"),
    ("esotouric", "Esotouric", "org", "Esotouric (Kim Cooper, Richard Schave)", r"Esotouric|Kim Cooper|Richard Schave"),
    # people
    ("peebles", "Don Peebles", "person", "The Peebles Corporation, ALP lead", r"Peebles"),
    ("macfarlane", "Victor MacFarlane", "person", "MacFarlane Partners, ALP member", r"MacFarlane"),
    ("huizar", "José Huizar", "person", "Councilmember, District 14 (to 2020)", r"Huizar"),
    ("deleon", "Kevin de León", "person", "Councilmember, District 14 (2020-2024)", r"de Le[oó]n"),
    ("estolano", "Cecilia Estolano", "person", "CRA chief executive (2006-2010)", r"Estolano"),
    ("fruin", "Judge Fruin", "person", "LA Superior Court judge in 24STCV32173", r"(?i)\bfruin\b"),
    ("erickson", "Arthur Erickson", "person", "Architect, California Plaza master plan", r"Erickson"),
    ("isozaki", "Arata Isozaki", "person", "Architect, MOCA Grand Avenue", r"(?i)isozaki"),
    ("beaudry", "Prudent Beaudry", "person", "Developer of the hilltop, 1867", r"(?<!user )Beaudry"),   # not the SkyscraperPage user of that name
    ("burton", "Johanna Burton", "person", "MOCA director (2022-2025)", r"Johanna Burton|\bBurton\b"),
    ("goldstein", "Ann Goldstein", "person", "MOCA interim director (2025-2026)", r"Goldstein"),
    ("abbott", "Jonathan Abbott", "person", "MOCA director from Sept 24, 2026", r"Jonathan Abbott|\bAbbott\b"),
    ("powers", "Carolyn Clark Powers", "person", "MOCA board chair", r"Carolyn Clark Powers|\bPowers\b"),
]

# matches that are in the text but are not about the actor (checked by reading the entry)
EXCLUDE = {
    ("plaza-001", "city"): "names an unrelated court case, Bunker Hill Associates v. City of Los Angeles (1982)",
    ("park-001", "esotouric"): "lists Esotouric among the sites we searched",
}

ID_RE = re.compile(r"\b[a-z]+-[a-z]?\d{2,3}\b")
SENT = re.compile(r"(?<=[.!?;])\s+")


def texts(f):
    """(field, text) pairs an actor or id may be found in."""
    out = [("title", f.get("title", "")), ("summary", f.get("summary", ""))]
    out += [("details", d) for d in f.get("details") or []]
    m = f.get("media") or {}
    for k in ("speaker", "role", "quote", "translation"):
        if m.get(k):
            out.append((k, m[k]))
    return out


def sentence(text, span):
    """The sentence of text around span, shortened to about 200 characters."""
    a, b = span
    starts = [0] + [m.end() for m in SENT.finditer(text) if m.end() <= a]
    s = starts[-1]
    ends = [m.start() for m in SENT.finditer(text) if m.start() >= b]
    e = ends[0] + 1 if ends else len(text)
    out = text[s:e].strip()
    if len(out) > 220:
        lo = max(0, a - s - 90)
        out = ("…" if lo else "") + out[lo:lo + 200].strip() + "…"
    return out


def main():
    db = json.loads(SRC.read_text(encoding="utf-8"))
    F = db["findings"]
    ids = {f["id"] for f in F}
    nodes, links = [], []
    for f in F:
        t = f.get("timeline") or {}
        nodes.append({"id": f["id"], "type": "entry", "title": f["title"], "topic": f["topic"], "status": f["status"],
                      "start": t.get("start"), "end": t.get("end"), "nsrc": len(f.get("sources") or [])})
    for key, label, kind, note, _ in ACTORS:
        nodes.append({"id": "actor:" + key, "type": kind, "title": label, "note": note})

    review = defaultdict(list)
    # mention and actor links: the first sentence that shows each one
    for f in F:
        seen = set()
        for field, text in texts(f):
            for m in ID_RE.finditer(text):
                o = m.group()
                if o in ids and o != f["id"] and ("m", o) not in seen:
                    seen.add(("m", o))
                    links.append({"a": f["id"], "b": o, "kind": "mention", "why": sentence(text, m.span()), "field": field})
            for key, label, kind, note, pat in ACTORS:
                if ("a", key) in seen or (f["id"], key) in EXCLUDE:
                    continue
                m = re.search(pat, text)
                if m:
                    seen.add(("a", key))
                    said = field == "speaker"
                    why = f"Said by {text}" if said else sentence(text, m.span())
                    links.append({"a": f["id"], "b": "actor:" + key, "kind": "actor", "why": why, "field": field,
                                  "match": m.group()})
                    review[key].append((f["id"], field, m.group(), why))
    # subject links: each Media entry to its subject (our grouping, made while collecting; user, 2026-10-12: most
    # comments name no person or entry, so they hang on their subject instead of floating alone)
    subjects = []
    for f in F:
        sub = (f.get("media") or {}).get("subject")
        if sub:
            if sub not in subjects:
                subjects.append(sub)
                nodes.append({"id": "subject:" + sub, "type": "subject", "title": sub, "note": "Media subject (our grouping)"})
            links.append({"a": f["id"], "b": "subject:" + sub, "kind": "subject", "why": f"Grouped under '{sub}' (our grouping)"})
    # mentions both ways count once
    uniq, out = set(), []
    for l in links:
        k = (l["kind"], *sorted((l["a"], l["b"])))
        if k not in uniq:
            uniq.add(k)
            out.append(l)
    links = out

    # source links: one per pair of entries, with the shared sources' titles
    by_url = defaultdict(set)
    titles = {}
    for f in F:
        for s in f.get("sources") or []:
            u = (s.get("url") or "").split("#")[0].rstrip("/")
            if u:
                by_url[u].add(f["id"])
                titles.setdefault(u, s.get("title") or u)
    pair = defaultdict(list)
    for u, es in by_url.items():
        es = sorted(es)
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                pair[(es[i], es[j])].append(titles[u])
    for (a, b), ts in sorted(pair.items()):
        links.append({"a": a, "b": b, "kind": "source", "why": ts[:3], "n": len(ts)})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {"_comment": "Built by docs/connections_build.py from web/research/data.json; do not edit by hand.",
            "asOf": (db.get("current") or {}).get("asOf"), "nodes": nodes, "links": links}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    sys.stdout.reconfigure(encoding="utf-8")
    kinds = defaultdict(int)
    for l in links:
        kinds[l["kind"]] += 1
    print(f"{len(nodes)} nodes ({len(F)} entries, {len(ACTORS)} people and organisations, {len(subjects)} subjects);"
          f" links: {dict(kinds)}")
    for key, label, *_ in ACTORS:
        r = review[key]
        print(f"\n## {label} ({len(r)})")
        for i, field, match, why in r:
            print(f"  {i} [{field}] '{match}': {why[:150]}")


if __name__ == "__main__":
    main()
