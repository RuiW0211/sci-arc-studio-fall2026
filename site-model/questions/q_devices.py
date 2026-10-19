"""What keeps people out? The Free view's second question (user, 2026-10-18), its data: web/data/q_devices.json.

Every device OpenStreetMap maps within RADIUS_M of Y-1 that decides who gets where, sorted by what it does, not by
what it is (Latour 2004, the reading for this question: describe what the things do):

  keep    keeps everyone out: fences, walls, hedges, retaining walls, locked or private gates, private paths and
          private driveways (data/barriers.json for the barriers, population/data/osm.json for the ways)
  sort    lets some in: who pays (Angels Flight, Metro turnstiles), who comes in its hours, customers only, and gates
          OSM gives neither hours nor access for (open or shut: not known)
  climb   lets in only those who climb: steps that rise CLIMB_M or more, where the way round without steps is EXTRA_M
          longer or there is none (the model's walking network, network.py, with every step, escalator and Angels
          Flight taken out)
  let     lets people in or up: entrances, open gates, lifts, escalators, foot bridges

Left out: kerbs (130 in the fetch, mapped where mappers drew crossings, not everywhere there is one) and car barriers
(lift gates: people walk round them). Heights: only Angels Knoll's fence has one (6 ft, q_passing.py); the viewer
draws the others on the ground.

  python q_devices.py     -> ../../web/data/q_devices.json (+ a printed summary)
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from shapely.geometry import LineString, Point, Polygon

import network

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "web" / "data" / "q_devices.json"
RADIUS_M = 300.0
Y1 = Point(-1.9, -4.2)              # Y-1's centre, scene-local metres east / north (population.json y1)
CLIMB_M = 1.0                       # steps rising less are a kerb or a landing; OSM's short dead-end steps rise 0.1-1 m
EXTRA_M = 200.0                     # the way round without steps: about two and a half minutes longer at walking pace
ANGELS_FLIGHT = {"fare": "$1.50 each way, $0.75 with a Metro TAP card", "hours": "6:45 am to 10:00 pm, every day",
                 "source": "angelsflight.org, read 2026-10-18"}

OX, OY = json.loads((HERE.parent / "houdini" / "handoff" / "buildings.json").read_text(encoding="utf-8"))["origin_utm"]
to_utm = Transformer.from_crs(4326, 26911, always_xy=True)
ground = network.ground_fn()


def loc(g):
    x, y = to_utm.transform(g["lon"], g["lat"])
    return x - OX, y - OY


def scene(x, y, z=None):
    """[x east, y up, z south], the viewer's frame."""
    return [round(x, 2), round(ground(x, y) if z is None else z, 2), round(-y, 2)]


def along(line, step=1.0):
    n = max(int(line.length / step), 1)
    return [scene(p.x, p.y) for p in (line.interpolate(k / n, normalized=True) for k in range(n + 1))]


lines, pins, lifts = [], [], []


def add_line(kind, does, osm_ref, g, **kw):
    lines.append({"kind": kind, "does": does, "osm": osm_ref, "length_m": round(g.length, 1), "pts": along(g), **kw})


def add_pin(kind, does, osm_ref, p, **kw):
    pins.append({"kind": kind, "does": does, "osm": osm_ref, "at": scene(p.x, p.y), **kw})


# ---------------------------------------------------------------- barriers, entrances, lifts (data/barriers.json)
bar = json.loads((HERE / "data" / "barriers.json").read_text(encoding="utf-8"))
knoll = json.loads((ROOT / "web" / "data" / "q_passing.json").read_text(encoding="utf-8"))["fence"]
LINE_KIND = {"fence": "fence", "wall": "wall", "retaining_wall": "retaining wall", "hedge": "hedge"}
for e in bar["elements"]:
    t = e.get("tags", {})
    b = t.get("barrier")
    ref = f"{e['type']}/{e['id']}"
    if e["type"] == "way" and b in LINE_KIND and "geometry" in e:
        g = LineString([loc(p) for p in e["geometry"]])
        if g.distance(Y1) <= RADIUS_M:
            kw = {"height_m": knoll["height_m"], "height_source": knoll["height_source"]} if e["id"] in knoll["osm_ways"] else {}
            add_line(LINE_KIND[b], "keep", ref, g, **kw)
    elif e["type"] == "node":
        p = Point(loc(e))
        if p.distance(Y1) > RADIUS_M:
            continue
        if b == "gate":
            if t.get("access") in ("private", "no") or t.get("locked") == "yes":
                add_pin("gate", "keep", ref, p, note="locked" if t.get("locked") == "yes" else "private")
            elif t.get("foot") in ("yes", "designated") or t.get("access") in ("yes", "permissive"):
                add_pin("gate", "let", ref, p, note="open to people on foot")
            else:
                add_pin("gate", "sort", ref, p, note="OSM gives no hours or access: open or shut, not known")
        elif b == "turnstile":
            add_pin("turnstile", "sort", ref, p, note="fare gate")
        elif t.get("highway") == "elevator":
            lifts.append((e["id"], p, ref))
        elif "entrance" in t or t.get("railway") == "subway_entrance":
            kw = {"wheelchair": t["wheelchair"]} if "wheelchair" in t else {}
            add_pin("Metro entrance" if t.get("railway") == "subway_entrance" else "entrance", "let", ref, p,
                    **({"name": t["name"]} if "name" in t else {}), **kw)

# ---------------------------------------------------------------- the ways (population/data/osm.json)
osm = json.loads((HERE.parent / "population" / "data" / "osm.json").read_text(encoding="utf-8"))
WAY = {e["id"]: e for e in osm["elements"] if e["type"] == "way" and "geometry" in e}
PEOPLE_WAYS = {"footway", "pedestrian", "steps", "path", "corridor", "living_street"}
for w, e in WAY.items():
    t = e.get("tags", {})
    hw = t.get("highway")
    g = LineString([loc(p) for p in e["geometry"]])
    if g.distance(Y1) > RADIUS_M:
        continue
    ref = f"way/{w}"
    if t.get("railway") == "funicular":
        add_line("Angels Flight", "sort", ref, g, note=f"fare {ANGELS_FLIGHT['fare']}; open {ANGELS_FLIGHT['hours']}")
    elif hw and t.get("access") in ("private", "no") and t.get("foot") not in ("yes", "designated", "permissive"):
        add_line("private path" if hw in PEOPLE_WAYS else "private driveway", "keep", ref, g)
    elif hw and t.get("access") == "customers":
        add_line("customers only", "sort", ref, g)
    elif hw and t.get("opening_hours") and t.get("conveying") is None:
        add_line("open in hours", "sort", ref, g, note=t["opening_hours"])
    elif hw and t.get("conveying"):
        add_line("escalator", "let", ref, g)
    elif hw in PEOPLE_WAYS and t.get("bridge") in ("yes", "viaduct"):
        add_line("foot bridge", "let", ref, g)

# ---------------------------------------------------------------- steps: who can only climb (the model's network)
net = network.build()
XYZ, E = net["XYZ"], net["E"]
N = len(XYZ)
tags = lambda w: WAY[w].get("tags", {}) if w in WAY else {}
is_step = np.array([tags(w).get("highway") == "steps" and not tags(w).get("conveying") for *_, w in E])
is_conv = np.array([bool(tags(w).get("conveying")) for *_, w in E])
fun = set(net["funicular"])
is_fun = np.array([a in fun and b in fun for a, b, *_ in E])
ea = np.array([[a, b] for a, b, *_ in E]); eL = np.array([L for _, _, L, *_ in E])
free = ~(is_step | is_conv | is_fun)                                  # what a wheelchair or a pram can use
Gfree = csr_matrix((np.r_[eL[free], eL[free]], (np.r_[ea[free, 0], ea[free, 1]], np.r_[ea[free, 1], ea[free, 0]])), shape=(N, N))
Gsteps = csr_matrix((np.ones(2 * is_step.sum()), (np.r_[ea[is_step, 0], ea[is_step, 1]], np.r_[ea[is_step, 1], ea[is_step, 0]])), shape=(N, N))
deg_free = np.diff(Gfree.indptr)
EW = {(min(a, b), max(a, b)): w for a, b, _, _, w in E}
_, comp = connected_components(Gsteps, directed=False)

stairs = []
for c in np.unique(comp[ea[is_step].ravel()]):
    k = np.flatnonzero(is_step & (comp[ea[:, 0]] == c))                # this staircase's edges (flights joined by landings)
    nodes = np.unique(ea[k].ravel())
    if np.hypot(XYZ[nodes, 0] - Y1.x, XYZ[nodes, 1] - Y1.y).min() > RADIUS_M:
        continue
    ends = nodes[deg_free[nodes] > 0]                                  # where it meets a way without steps
    z = XYZ[ends, 2] if len(ends) else XYZ[nodes, 2]
    rise = float(z.max() - z.min()) if len(ends) >= 2 else 0.0
    st = {"osm_ways": sorted({int(E[i][4]) for i in k}), "name": tags(int(E[k[0]][4])).get("name"),
          "length_m": round(float(eL[k].sum()), 1), "rise_m": round(rise, 1),
          "joined_at_both_ends": bool(len(ends) >= 2),
          "pts": [[scene(*XYZ[E[i][0], :2], XYZ[E[i][0], 2]), scene(*XYZ[E[i][1], :2], XYZ[E[i][1], 2])] for i in k]}
    if len(ends) >= 2:
        lo, hi = ends[np.argmin(z)], ends[np.argmax(z)]
        D, P = dijkstra(Gfree, directed=False, indices=lo, return_predecessors=True)
        if np.isfinite(D[hi]):
            seq = [hi]
            while seq[-1] != lo:
                seq.append(int(P[seq[-1]]))
            dz = np.abs(np.diff(XYZ[seq, 2])); dl = np.hypot(*np.diff(XYZ[seq, :2], axis=0).T)
            # a tunnel's nodes have the ground above them (the model's heights), so its stretches are left out
            open_air = np.array([not tags(EW[(min(a, b), max(a, b))]).get("tunnel") for a, b in zip(seq[:-1], seq[1:])])
            st["way_round_m"] = round(float(D[hi]), 0)
            st["way_round_steepest"] = round(float((dz / np.maximum(dl, 1e-6))[(dl > 5) & open_air].max(initial=0)), 3)   # rise / run, stretches over 5 m
            st["way_round_via"] = sorted({tags(EW[(min(a, b), max(a, b))]).get("name") for a, b in zip(seq[:-1], seq[1:])} - {None})
        else:
            st["way_round_m"] = None
        own = float(D[hi]) if np.isfinite(D[hi]) else np.inf
        st["extra_m"] = None if not np.isfinite(own) else round(own - st["length_m"], 0)
    st["does"] = "climb" if (rise >= CLIMB_M and (st.get("extra_m") is None or st["extra_m"] >= EXTRA_M)) else "let"
    stairs.append(st)
stairs.sort(key=lambda s: -s["rise_m"])

# lifts: on a mapped path (so in the network) or not, and the building they stand at (the hand-off's LiDAR outlines,
# within 5 m: Two California Plaza's lifts stand half a metre outside its outline)
on_net = set(int(o) for o in net["osm"])
hand = json.loads((HERE.parent / "houdini" / "handoff" / "buildings.json").read_text(encoding="utf-8"))["buildings"]
outlines = [(b.get("name"), Polygon(t["outer"])) for b in hand for t in b["tiers"] if len(t["outer"]) >= 3]
for osm_id, p, ref in lifts:
    d, at = min(((poly.distance(p), n) for n, poly in outlines), default=(np.inf, None))
    add_pin("lift", "let", ref, p, on_path=osm_id in on_net, **({"building": at} if d <= 5.0 and at else {}))

# ---------------------------------------------------------------- summary + file
def tally(items, key="kind"):
    out = defaultdict(lambda: {"count": 0, "length_m": 0.0})
    for it in items:
        o = out[(it["does"], it[key])]
        o["count"] += 1; o["length_m"] += it.get("length_m", 0.0)
    return [{"does": d, "kind": k, "count": v["count"], **({"length_m": round(v["length_m"])} if v["length_m"] else {})}
            for (d, k), v in sorted(out.items())]


climb = [s for s in stairs if s["does"] == "climb"]
summary = tally(lines + pins) + [{"does": "climb", "kind": "steps", "count": len(climb), "length_m": round(sum(s["length_m"] for s in climb))}]
OUT.write_text(json.dumps({
    "_comment": "Free view question 'What keeps people out?' (site-model/questions/q_devices.py). Every device OpenStreetMap maps within radius_m of Y-1, by what it does: keep (everyone out), sort (lets some in: fare, hours, customers, gates OSM says nothing about), climb (steps with no way round without steps under extra_m longer), let (lets people in or up). Scene metres [x east, y up, z south]; pts every metre on the ground (heights only where height_m). What OSM maps, not a survey.",
    "radius_m": RADIUS_M, "centre": [Y1.x, -Y1.y], "climb_m": CLIMB_M, "extra_m": EXTRA_M,
    "summary": summary, "lines": lines, "pins": pins, "stairs": stairs, "angels_flight": ANGELS_FLIGHT,
    "source": bar["source"] + f", fetched {bar['fetched'][:10]} (barriers, entrances, lifts) and with the population model's ways (site-model/population/data/osm.json)",
}, separators=(",", ":")), encoding="utf-8")

for s in summary:
    print(f"{s['does']:6s} {s['kind']:18s} {s['count']:3d}" + (f"  {s['length_m']:5d} m" if "length_m" in s else ""))
print(f"staircases within {RADIUS_M:.0f} m: {len(stairs)}; rise >= {CLIMB_M} m: {sum(s['rise_m'] >= CLIMB_M for s in stairs)}; "
      f"climb only (no way round, or {EXTRA_M:.0f} m longer): {len(climb)}")
for s in stairs[:12]:
    c = np.mean([p for seg in s["pts"] for p in seg], axis=0)
    print(f"  rise {s['rise_m']:5.1f} m, {s['length_m']:5.1f} m of steps at ({c[0]:.0f}, {-c[2]:.0f}), way round {s.get('way_round_m')} m "
          f"(steepest {s.get('way_round_steepest')}, via {s.get('way_round_via')}), extra {s.get('extra_m')} -> {s['does']}  "
          f"{s['name'] or ''} ways {s['osm_ways'][:4]}")
print("lifts:", [(q["osm"], q["on_path"], q.get("building")) for q in pins if q["kind"] == "lift"])
print("->", OUT.relative_to(ROOT), f"{OUT.stat().st_size / 1e3:.0f} kB")
