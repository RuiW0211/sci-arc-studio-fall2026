"""Who walks past here? The Free view's first question (user, 2026-10-18), its data: web/data/q_passing.json.

TODAY (G): how many walking trips of the modeled typical day pass along Angels Knoll's fence, by hour and by kind
of person. "Along the fence": the path runs inside a band BAND_M wide outside the fence (the sidewalks of Hill,
4th and Olive Streets and the Angels Flight stairs; inside the fence nobody walks today). Counted as the street
counts are checked (site-model/population/check_walk_counts.py): everyone before thinning (data/raw/
population_full.npz), a trip counted once, at the middle of the trip, office attendance as the viewer has it. The
model's error on the nine counted LADOT blocks (web/data/walk_check.json, model / count from 0.47 to 2.4; none of
them near Y-1) gives the range: the count divided by the largest and by the smallest ratio.

THE FENCE: OpenStreetMap's fences round Angels Knoll Park (data/barriers.json, fetch_barriers.py); the point cloud
has almost no points of it (a chain-link and a metal fence, too thin for airborne LiDAR), so the viewer draws it
from these lines, 6 ft high (LA Downtown News, 19 Aug 2013: the benches behind "a six-foot fence"; Street View,
Hill St May 2025 and 4th St June 2024, looks the same).

  python q_passing.py     -> ../../web/data/q_passing.json (+ a printed summary)
"""
import json
from pathlib import Path

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

import network

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
POP = HERE.parent / "population"
OUT = ROOT / "web" / "data" / "q_passing.json"
BAND_M = 15.0                     # the band outside the fence: about a sidewalk and a half (sensitivity: WIDTHS)
WIDTHS = (10.0, 15.0, 25.0)       # 25 m = check_walk_counts.py's half width (the street and both sidewalks)
FENCE_FT = 6
FENCE_SRC = ("LA Downtown News editorial, 19 Aug 2013 (the benches and the Angels Flight information stand behind "
             "'a six-foot fence'; research database); Google Street View, Hill St May 2025 and 4th St June 2024")

OX, OY = json.loads((HERE.parent / "houdini" / "handoff" / "buildings.json").read_text(encoding="utf-8"))["origin_utm"]
to_utm = Transformer.from_crs(4326, 26911, always_xy=True)


def ll2loc(lat, lon):
    x, y = to_utm.transform(lon, lat)
    return x - OX, y - OY


# ---------------------------------------------------------------- the fence (OSM)
osm = json.loads((HERE / "data" / "barriers.json").read_text(encoding="utf-8"))
park = next(e for e in osm["elements"] if e["type"] == "way" and e.get("tags", {}).get("leisure") == "park"
            and "Angels Knoll" in e["tags"].get("name", ""))
PARK = Polygon([ll2loc(g["lat"], g["lon"]) for g in park["geometry"]])
fences = []
for e in osm["elements"]:
    if e["type"] == "way" and e.get("tags", {}).get("barrier") == "fence" and "geometry" in e:
        line = LineString([ll2loc(g["lat"], g["lon"]) for g in e["geometry"]])
        if line.distance(PARK.exterior) < 3.0:                       # the knoll's own fences, not the neighbours'
            fences.append((e["id"], line))
FENCE = unary_union([l for _, l in fences])
gates = [(e["id"], e["tags"].get("access")) for e in osm["elements"] if e["type"] == "node"
         and e.get("tags", {}).get("barrier") == "gate" and PARK.exterior.distance(shapely.Point(ll2loc(e["lat"], e["lon"]))) < 3.0]
print(f"Angels Knoll Park {PARK.area:.0f} m2, perimeter {PARK.exterior.length:.0f} m; fences {[i for i, _ in fences]}, "
      f"{FENCE.length:.0f} m; gates on its edge {gates}")


def band(w):
    """Outside the fence, within w m of it."""
    return FENCE.buffer(w).difference(PARK)


# ---------------------------------------------------------------- the model, everyone (before thinning)
Z = np.load(POP / "data" / "raw" / "population_full.npz")
NX, poff, pn = Z["nodes"].astype(float), Z["pathOffsets"].astype(np.int64), Z["pathNodes"].astype(np.int64)
TYPE, present, weight = Z["type"], Z["present"], Z["weight"].astype(float)
meta = json.loads((ROOT / "web" / "data" / "population.json").read_text(encoding="utf-8"))
TYPES = meta["types"]
N = len(NX)

# every segment of every path once: does it run in the band?
seg_a, seg_b = pn[:-1], pn[1:]
is_seg = np.ones(len(pn) - 1, bool)
is_seg[poff[1:-1] - 1] = False                                        # no segment across two paths
key = np.minimum(seg_a, seg_b) * N + np.maximum(seg_a, seg_b)
ukey, inv = np.unique(key[is_seg], return_inverse=True)
ua, ub = ukey // N, ukey % N
lines = shapely.linestrings(np.stack([NX[ua], NX[ub]], axis=1))


def paths_in(b):
    """For band b: which paths have a segment in it."""
    hit_u = shapely.intersects(lines, b)
    hit = np.zeros(len(pn) - 1, bool)
    hit[np.flatnonzero(is_seg)] = hit_u[inv]
    # each path's own segments: [poff[p], poff[p+1] - 1) (the segment that starts at a path's last node is not one)
    per_path = np.add.reduceat(np.r_[hit, False].astype(np.int64), poff[:-1])
    per_path[np.diff(poff) < 2] = 0                                   # a one-node path has no segment
    return per_path > 0


def count(b, P=None, extra=None):
    """The trips whose path is in band b (or, given P, whose path index is marked in P), by day: total (people
    weighted), by hour (at the middle of the trip), by kind of person; extra: a per-path value averaged over them."""
    P = paths_in(b) if P is None else P
    out = {}
    for d in ("weekday", "weekend"):
        off, path = Z[f"{d}.offsets"].astype(np.int64), Z[f"{d}.path"].astype(np.int64)
        t_mid = (Z[f"{d}.t0"] + Z[f"{d}.t1"]) / 2                    # seconds
        person = np.repeat(np.arange(len(off) - 1), np.diff(off))
        live = ~Z[f"{d}.attend"] | present[person]                    # office attendance as in the viewer
        hit = P[path] & live
        w = weight[person[hit]]
        hours = np.clip((t_mid[hit] // 3600).astype(int), 0, 23)
        by_type = {TYPES[t]: round(float(w[TYPE[person[hit]] == t].sum())) for t in range(len(TYPES))}
        out[d] = {"total": round(float(w.sum())), "by_hour": np.bincount(hours, weights=w, minlength=24).round().astype(int).tolist(),
                  "by_type": {k: v for k, v in by_type.items() if v}, "people": int(len(np.unique(person[hit])))}
        if extra is not None:
            out[d]["extra_mean"] = round(float((w * extra[path[hit]]).sum() / max(w.sum(), 1)), 2)
    return out


widths = {str(int(w)): count(band(w)) for w in WIDTHS}
today = widths[str(int(BAND_M))]
wc = json.loads((ROOT / "web" / "data" / "walk_check.json").read_text(encoding="utf-8"))
ratios = [b["weekday"]["ratio"] for b in wc["blocks"]]
lo_r, hi_r = min(ratios), max(ratios)


# ---------------------------------------------------------------- if the fence opened (one sentence on the page)
# (user, 2026-10-18: no Opened / Closed switch, it showed no difference; "加上那句结论": the finding, in words) The
# same trips (people, ends, times) with their routes found again on a network with Angels Knoll's two private paths
# open: the path across the knoll (OSM way 322957601, joined at both ends as OSM draws it) and the one inside the Hill
# Street fence (322959879, which OSM draws joined to nothing: its gate joined to the street at the Angels Flight
# stairs' foot, 8 m, and its other end to the 4th Street sidewalk, 5 m; an assumption). Not a new run of the model,
# which would also change where people go and when.
from scipy.sparse.csgraph import dijkstra

base = network.build()
assert len(base["XYZ"]) == N and np.abs(base["XYZ"][:, :2] - NX).max() < 0.01, "the rebuilt network is not the model's"
OPEN_WAYS, LINK_ENDS = (322957601, 322959879), (3297577617, 3297577582)
WALK_MS = json.loads((POP / "data" / "assumptions.json").read_text(encoding="utf-8"))["walkSpeed"]["value"][0]   # m/s, mean


def path_len(XY, seq):
    return float(np.hypot(*np.diff(XY[seq, :2], axis=0).T).sum()) if len(seq) > 1 else 0.0


def reroute(net):
    """Every path (src = its first node, an anchor; dst = its last) whose route on net is cheaper than on the model's
    network: {path index: new node list (net indices)}. Checks on the way that the model's own paths are the shortest
    on the rebuilt network."""
    by_osm = {int(o): k for k, o in enumerate(net["osm"])}
    to_net = np.array([by_osm[int(o)] for o in base["osm"]])
    src, dst = pn[poff[:-1]], pn[poff[1:] - 1]
    out, check, US = {}, [], np.unique(src)
    for s0 in range(0, len(US), 256):
        S = US[s0:s0 + 256]
        Db = dijkstra(base["G"], directed=False, indices=S)
        Dn, Pn = dijkstra(net["G"], directed=False, indices=to_net[S], return_predecessors=True)
        row = {int(s): k for k, s in enumerate(S)}
        for p in np.flatnonzero(np.isin(src, S)):
            r = row[int(src[p])]
            old, new = Db[r, dst[p]], Dn[r, to_net[dst[p]]]
            if len(check) < 3000:
                seq = pn[poff[p]:poff[p + 1]]
                check.append(abs((float(np.asarray(base["G"][seq[:-1], seq[1:]]).sum()) if len(seq) > 1 else 0.0) - old))
            if new < old - 0.01:
                seq, t = [int(to_net[dst[p]])], int(to_net[src[p]])
                while seq[-1] != t:
                    seq.append(int(Pn[r, seq[-1]]))
                out[int(p)] = seq[::-1]
    assert max(check) < 0.05, f"a model path is not the shortest on the rebuilt network (off by {max(check):.2f})"
    return out


net = network.build(open_ways=OPEN_WAYS, link_ends=LINK_ENDS)
new = reroute(net)
P_open = np.zeros(len(poff) - 1, bool); P_open[list(new)] = True
saved_s = np.zeros(len(poff) - 1)
for p, seq in new.items():
    saved_s[p] = (path_len(NX, pn[poff[p]:poff[p + 1]]) - path_len(net["XYZ"], seq)) / WALK_MS
opened = count(None, P=P_open, extra=saved_s)
for d in opened:
    opened[d]["seconds_saved_mean"] = opened[d].pop("extra_mean")

# scene coordinates for the viewer: x east, z south (= -north)
sc = lambda g: [[round(x, 2), round(-y, 2)] for x, y in g.coords]
# the fence for drawing: every metre along its lines, with the ground under it ([x east, y up, z south])
ground = network.ground_fn()


def fence_pts(line, step=1.0):
    n = max(int(line.length / step), 1)
    return [[round(p.x, 2), round(ground(p.x, p.y), 2), round(-p.y, 2)] for p in (line.interpolate(k / n, normalized=True) for k in range(n + 1))]
B = band(BAND_M)
OUT.write_text(json.dumps({
    "_comment": "Free view question 'Who walks past here?' (site-model/questions/q_passing.py). Scene metres: [x east, z south]. today: modeled walking trips along Angels Knoll's fence (a band band.width_m wide outside it) on a typical weekday / weekend day, everyone before thinning, a trip counted once at its middle; range = total / the largest and / the smallest model-to-count ratio of the nine LADOT blocks (walk_check.json; none near Y-1). widths: the same with other band widths. A model, not a count.",
    "fence": {"lines": [fence_pts(l) for _, l in fences], "osm_ways": [i for i, _ in fences], "length_m": round(FENCE.length),
              "height_m": round(FENCE_FT * 0.3048, 2), "height_ft": FENCE_FT, "height_source": FENCE_SRC,
              "gates": [{"osm_node": i, "access": a} for i, a in gates],
              "source": osm["source"] + f", fetched {osm['fetched'][:10]}"},
    "park": {"ring": sc(PARK.exterior), "area_m2": round(PARK.area), "osm_way": park["id"]},
    "band": {"width_m": BAND_M, "rings": [sc(g.exterior) for g in getattr(B, "geoms", [B])]},
    "today": today, "widths": {k: {d: v[d]["total"] for d in v} for k, v in widths.items()},
    "range": {"ratios": [lo_r, hi_r], "note": "model / LADOT count on the nine blocks counted in 2023 and 2025 (walk_check.json); the nearest is about 450 m from Y-1",
              "weekday": [round(today["weekday"]["total"] / hi_r), round(today["weekday"]["total"] / lo_r)],
              "weekend": [round(today["weekend"]["total"] / hi_r), round(today["weekend"]["total"] / lo_r)]},
    "opened": {**opened, "paths_changed": len(new), "open_ways": list(OPEN_WAYS), "links": net["links"], "walk_speed_ms": WALK_MS,
               "note": "The same trips routed again with Angels Knoll's two private paths open (the Hill Street one joined to the street: an assumption); counted as today. seconds_saved_mean: the shorter route at the model's mean walking speed. The model's people take the shortest way and do not stop: people who would cross the park, not use it."},
}, separators=(",", ":")), encoding="utf-8")

for d in ("weekday", "weekend"):
    t = today[d]
    peak = int(np.argmax(t["by_hour"]))
    print(f"{d}: {t['total']:,} trips past the fence ({t['people']:,} modeled people), range "
          f"{round(t['total'] / hi_r):,}-{round(t['total'] / lo_r):,}; peak {peak}:00-{peak + 1}:00 ({t['by_hour'][peak]:,}); by type {t['by_type']}")
for d in ("weekday", "weekend"):
    print(f"if it opened, {d}: {opened[d]['total']:,} of these would cut across, each {opened[d]['seconds_saved_mean']} s shorter")
print("band width sensitivity:", {k: v for k, v in json.loads(OUT.read_text(encoding='utf-8'))["widths"].items()})
print("->", OUT.relative_to(ROOT))
