"""Check the modeled street flows against LADOT Walk & Bike Counts (user, 2026-10-09). A check, and the fit of the two calibrated groups (Little Tokyo visitors, passers-by) on the blocks not held out.

LADOT counts people walking across one street block (both sidewalks, both directions) on one weekday, 7-10 am and
3-6 pm, and one weekend day, 11 am-1 pm (fetch_walk_counts.py, 2023 and 2025). Each counted block is found in
OpenStreetMap (data/osm.json) as the stretch of the street between its two cross streets; the model is counted on a
line across the street at the middle of that block, 2 x HALF_W wide, so it catches the street and its sidewalks.
A modeled walker is counted when their path crosses that line inside the count hours (time taken at the middle of
the trip), weighted like the viewer (population.json / .bin: weights, office attendance by rank).

  python site-model/population/check_walk_counts.py   -> site-model/population/data/walk_check.json (+ printed table)
"""
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import argparse

import numpy as np
from pyproj import Transformer

_ap = argparse.ArgumentParser()
_ap.add_argument("--dir", help="a sample run's folder (prep_population.py --sample / --smoke), e.g. data/raw/sample")
ARGS = _ap.parse_args()

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA, RAW = HERE / "data", HERE / "data" / "raw"
HALF_W = 25.0          # m each side of the street centre line
EDGE = 1150.0          # blocks this close to the site edge (1250 m) are skipped: paths are cut there
WINDOWS = {"weekday": [(7, 10), (15, 18)], "weekend": [(11, 13)]}
YEARS = (2023, 2025)
HOLD_OUT = {"5th St bw Main St & Spring St", "Grand Ave bw 7th St & 8th St", "Los Angeles St bw Arcadia St & Aliso St"}

OX, OY = json.loads((HERE.parent / "houdini" / "handoff" / "buildings.json").read_text(encoding="utf-8"))["origin_utm"]
to_utm = Transformer.from_crs(4326, 26911, always_xy=True)


def ll2loc(lat, lon):
    x, y = to_utm.transform(lon, lat)
    return x - OX, y - OY


ABBR = {"st": "street", "ave": "avenue", "av": "avenue", "blvd": "boulevard", "bl": "boulevard", "pl": "place",
        "dr": "drive", "rd": "road"}


def norm(name):
    w = re.sub(r"[.,]", "", name.lower()).split()
    while w and w[0] in ("north", "south", "east", "west", "n", "s", "e", "w"):
        w = w[1:]
    return " ".join(ABBR.get(x, x) for x in w)


# ---------------------------------------------------------------- street blocks from OSM
osm = json.loads((DATA / "osm.json").read_text(encoding="utf-8"))
ways_by_name = defaultdict(list)
node_xy = {}
for e in osm["elements"]:
    if e["type"] == "way" and "geometry" in e and "highway" in e.get("tags", {}) and "name" in e["tags"]:
        ways_by_name[norm(e["tags"]["name"])].append(e)
        for n, g in zip(e["nodes"], e["geometry"]):
            node_xy[n] = ll2loc(g["lat"], g["lon"])


def crossings(a, b):
    na = {n for w in ways_by_name.get(norm(a), []) for n in w["nodes"]}
    nb = {n for w in ways_by_name.get(norm(b), []) for n in w["nodes"]}
    return [node_xy[n] for n in na & nb]


def locate(street, l1, l2):
    """Middle of the block of `street` between cross streets l1 and l2, and the street's direction there."""
    c1, c2 = crossings(street, l1), crossings(street, l2)
    if not c1 or not c2:
        return None
    p, q = min(((p, q) for p in c1 for q in c2), key=lambda pq: math.dist(*pq))
    if math.dist(p, q) > 400:
        return None
    m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    d = np.subtract(q, p)
    return m, d / np.linalg.norm(d), math.dist(p, q)


counts = {}
for y in YEARS:
    for r in json.loads((RAW / f"walk_bike_count_{y}.json").read_text(encoding="utf-8"))["rows"]:
        key = (r["street_name"], r["limit_1"], r["limit_2"])
        c = counts.setdefault(key, {"index": r.get("index")})
        c[y] = {"weekday": int(r["ped_weekday_total"]) if r.get("ped_weekday_total") else None,
                "weekend": int(r["ped_weekend"]) if r.get("ped_weekend") else None}

sites = []
for (st, l1, l2), c in counts.items():
    loc = locate(st, l1, l2)
    if loc and abs(loc[0][0]) < EDGE and abs(loc[0][1]) < EDGE:
        (mx, my), u, blk = loc
        n = np.array([-u[1], u[0]])
        a, b = np.array([mx, my]) - HALF_W * n, np.array([mx, my]) + HALF_W * n
        sites.append({"name": f"{st} bw {l1} & {l2}", "index": c["index"], "xy": [round(mx, 1), round(my, 1)],
                      "block_m": round(blk), "line": (a, b), "counts": {y: c.get(y) for y in YEARS}})
print(f"{len(sites)} counted blocks inside the site")

# ---------------------------------------------------------------- the model: everyone, before thinning
# prep_population.py writes data/raw/population_full.npz (every person, weight 1). Without it, the viewer's thinned
# file is used, whose large weights far from Y-1 make the counts there noisy.
SRC = Path(ARGS.dir).resolve() if ARGS.dir else ROOT / "web" / "data"
meta = json.loads((SRC / "population.json").read_text(encoding="utf-8"))
FULL = (SRC if ARGS.dir else RAW) / "population_full.npz"
if FULL.exists():
    Z = np.load(FULL)
    NX, poff, pn = Z["nodes"].astype(float), Z["pathOffsets"], Z["pathNodes"]
    TYPE, present = Z["type"], Z["present"]
    weight = Z["weight"].astype(float) if "weight" in Z else np.ones(len(TYPE))   # a sample: each counts 1/share
    LT_A = int(Z["littletokyo_anchor"])
    DAYS = {d: (Z[f"{d}.offsets"], Z[f"{d}.path"], (Z[f"{d}.t0"] + Z[f"{d}.t1"]) / 2 / 3600, Z[f"{d}.attend"],
                Z[f"{d}.orig"], Z[f"{d}.dest"]) for d in WINDOWS}
    print("model: everyone, before thinning (data/raw/population_full.npz)")
else:
    buf = (SRC / "population.bin").read_bytes()
    T = {"float32": np.float32, "uint32": np.uint32, "uint16": np.uint16, "int16": np.int16, "uint8": np.uint8}
    sec = lambda k: np.frombuffer(buf, T[meta["sections"][k]["type"]], meta["sections"][k]["count"], meta["sections"][k]["offset"])
    nodes = sec("nodes").reshape(-1, 3)
    NX = np.c_[nodes[:, 0], -nodes[:, 2]]  # viewer (x, y up, z = -north) -> (east, north)
    poff, pn = sec("pathOffsets"), sec("pathNodes")
    weight, TYPE = sec("weight"), sec("type")
    present = sec("rank") < np.array(meta["sectorAttendance"])[sec("sector")] * 256
    LT_A = next((k for k, n in enumerate(meta["anchors"]) if n.startswith("Little Tokyo")), -2)
    TU, FA = meta["time_unit_s"], meta["flags"]["attendance"]
    DAYS = {d: (sec(f"{d}.offsets"), sec(f"{d}.path"), (sec(f"{d}.t0").astype(float) + sec(f"{d}.t1")) / 2 * TU / 3600,
                (sec(f"{d}.flags") & FA) > 0, sec(f"{d}.orig"), sec(f"{d}.dest")) for d in WINDOWS}
    print("model: the viewer's thinned file (weights)")


def seg_cross(P, Q, a, b):
    """Which segments P[k]-Q[k] cross the line a-b."""
    r, s = Q - P, b - a
    den = r[:, 0] * s[1] - r[:, 1] * s[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = ((a[0] - P[:, 0]) * s[1] - (a[1] - P[:, 1]) * s[0]) / den
        v = ((a[0] - P[:, 0]) * r[:, 1] - (a[1] - P[:, 1]) * r[:, 0]) / den
    return np.count_nonzero((den != 0) & (t >= 0) & (t <= 1) & (v >= 0) & (v <= 1))


# how many times each path crosses each counted line
cross = np.zeros((len(poff) - 1, len(sites)), np.uint8)
for p in range(len(poff) - 1):
    seg = NX[pn[poff[p]:poff[p + 1]]]
    if len(seg) < 2:
        continue
    lo, hi = seg.min(0) - HALF_W, seg.max(0) + HALF_W
    for j, s in enumerate(sites):
        a, b = s["line"]
        if lo[0] <= max(a[0], b[0]) and hi[0] >= min(a[0], b[0]) and lo[1] <= max(a[1], b[1]) and hi[1] >= min(a[1], b[1]):
            cross[p, j] = seg_cross(seg[:-1], seg[1:], a, b)

model = {d: np.zeros(len(sites)) for d in WINDOWS}
by_group = {d: {} for d in WINDOWS}   # the same counts split by group (Little Tokyo visitors apart)
GROUPS = meta["types"] + ["littletokyo"]
for d, win in WINDOWS.items():
    off, path, tm, attend, orig, dest = DAYS[d]
    person = np.repeat(np.arange(len(off) - 1), np.diff(off))
    keep = np.zeros(len(path), bool)
    for h0, h1 in win:
        keep |= (tm >= h0) & (tm < h1)
    keep &= ~(attend & ~present[person])
    contrib = cross[path[keep]].astype(float) * weight[person[keep]][:, None]
    model[d] = contrib.sum(0)
    grp = TYPE[person[keep]].astype(int)
    grp = np.where((orig[keep] == LT_A) | (dest[keep] == LT_A), len(GROUPS) - 1, grp)
    by_group[d] = {GROUPS[g]: contrib[grp == g].sum(0) for g in range(len(GROUPS))}

# ---------------------------------------------------------------- compare
out = []
print(f"\n{'counted block':52s} {'weekday 7-10 + 15-18':>28s}   {'weekend 11-13':>24s}")
print(f"{'':52s} {'model':>8s} {'2023':>6s} {'2025':>6s} {'ratio':>6s}   {'model':>7s} {'2023':>6s} {'2025':>6s} {'ratio':>6s}")
for j, s in sorted(enumerate(sites), key=lambda js: -js[1]["xy"][1]):
    row = {"name": s["name"], "index": s["index"], "xy": s["xy"], "block_m": s["block_m"], "held_out": s["name"] in HOLD_OUT}
    cells = []
    for d in WINDOWS:
        obs = [s["counts"][y][d] for y in YEARS if s["counts"].get(y) and s["counts"][y][d] is not None]
        mean = sum(obs) / len(obs) if obs else None
        row[d] = {"model": round(float(model[d][j])), "by_group": {g: round(float(v[j])) for g, v in by_group[d].items() if v[j] >= 0.5}, **{str(y): (s["counts"][y] or {}).get(d) if s["counts"].get(y) else None for y in YEARS},
                  "observed_mean": round(mean) if mean else None, "ratio": round(float(model[d][j]) / mean, 2) if mean else None}
        cells.append(row[d])
    out.append(row)
    f = lambda v: f"{v:>6}" if v is not None else f"{'-':>6}"
    print(f"{s['name'][:52]:52s} {cells[0]['model']:>8} {f(cells[0]['2023'])} {f(cells[0]['2025'])} {f(cells[0]['ratio'])}"
          f"   {cells[1]['model']:>7} {f(cells[1]['2023'])} {f(cells[1]['2025'])} {f(cells[1]['ratio'])}")
for d in WINDOWS:
    m = sum(r[d]["model"] for r in out if r[d]["observed_mean"])
    o = sum(r[d]["observed_mean"] for r in out if r[d]["observed_mean"])
    print(f"all blocks, {d}: model {m:,} / counted {o:,} = {m / o:.2f}")
    for tag, sel in (("fitted blocks", lambda r: not r["held_out"]), ("held-out blocks", lambda r: r["held_out"])):
        m = sum(r[d]["model"] for r in out if r[d]["observed_mean"] and sel(r))
        o = sum(r[d]["observed_mean"] for r in out if r[d]["observed_mean"] and sel(r))
        print(f"  {tag}: {m / o:.2f}" if o else f"  {tag}: -")

# ---------------------------------------------------------------- the two calibrated groups (user, 2026-10-09)
# Little Tokyo visitors: scale so the 1st St block matches on the weekend. Passers-by: least squares, per day type, on
# the blocks that are not held out (and not 1st St); the held-out blocks stay an independent check.
AS = json.loads((DATA / "assumptions.json").read_text(encoding="utf-8"))
fit = {}
lt = next(r for r in out if r["name"].startswith("1st St bw Central"))
g = lt["weekend"]["by_group"].get("littletokyo", 0)
if g:
    k = (lt["weekend"]["observed_mean"] - (lt["weekend"]["model"] - g)) / g
    fit["littleTokyo.annual"] = round(AS["littleTokyo"]["value"]["annual"] * max(k, 0), -3)
for d in WINDOWS:
    rows = [r for r in out if not r["held_out"] and r is not lt and r[d]["observed_mean"]]
    pb = np.array([r[d]["by_group"].get("passerby", 0) for r in rows], float)
    rest = np.array([r[d]["model"] - r[d]["by_group"].get("passerby", 0) for r in rows], float)
    obs = np.array([r[d]["observed_mean"] for r in rows], float)
    if pb.sum():
        k = max(float(pb @ (obs - rest) / (pb @ pb)), 0)
        fit[f"passersBy.{d}"] = round(AS["passersBy"]["value"][d] * k, -2)
print("fitted values (to put in assumptions.json):", fit)

# ---------------------------------------------------------------- Angels Flight (user, 2026-10-09)
# Trips whose path runs along the funicular (OSM railway=funicular), everyone counted; against the last published
# ridership: 1,200-1,500 trips a day (2010-13), about 2,200 a day (1996-2001).
from scipy.spatial import cKDTree
fun_xy = np.array([ll2loc(g["lat"], g["lon"]) for e in osm["elements"]
                   if e["type"] == "way" and e.get("tags", {}).get("railway") == "funicular" for g in e["geometry"]])
dist, idx = cKDTree(NX).query(fun_xy)
FUN = set(int(i) for d, i in zip(dist, idx) if d < 0.5)
on_fun = np.zeros(len(poff) - 1, bool)
for p in range(len(poff) - 1):
    seq = pn[poff[p]:poff[p + 1]]
    on_fun[p] = any(int(a) in FUN and int(b) in FUN for a, b in zip(seq[:-1], seq[1:]))
angels = {}
for d in WINDOWS:
    off, path, tm, attend, orig, dest = DAYS[d]
    person = np.repeat(np.arange(len(off) - 1), np.diff(off))
    k = on_fun[path] & ~(attend & ~present[person])
    angels[d] = round(float(weight[person[k]].sum()))
print(f"Angels Flight trips a day: weekday {angels['weekday']:,}, weekend {angels['weekend']:,} (last published: 1,200-1,500 a day, 2010-13)")

OUT = (SRC / "walk_check.json") if ARGS.dir else (DATA / "walk_check.json")   # a sample never overwrites the real check
OUT.write_text(json.dumps({
    "note": "Modeled walkers crossing each LADOT count block (both sidewalks, both directions) in the count hours, against "
            "LADOT Walk & Bike Count 2023 and 2025 (one day each; observed_mean = their mean). A check only.",
    "sources": {str(y): f"LADOT Walk & Bike Count {y}, data.lacity.org" for y in YEARS},
    "hours": WINDOWS, "half_width_m": HALF_W, "held_out": sorted(HOLD_OUT), "fit": fit,
    "angels_flight": {**angels, "published": "1,200-1,500 trips a day (2010-13), about 2,200 (1996-2001)"}, "blocks": out}, indent=1), encoding="utf-8")
print("wrote", OUT)
if not ARGS.dir:   # the Methods page (web/methods/) shows the full run's check
    (ROOT / "web" / "data" / "walk_check.json").write_text(OUT.read_text(encoding="utf-8"), encoding="utf-8")
    print("copied to web/data/walk_check.json")
