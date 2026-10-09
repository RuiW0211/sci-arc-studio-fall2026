"""Modeled day/night population of the site: one point per person, with a full day of trips.

Ported from the population layer Clark Amenudo wrote for the Blender version of the project (PR #9 in the archived
RuiW0211/sci-arc-studio-fall2026-blender), 2026-10-08: the buildings and the ground now come from the Houdini
hand-off (site-model/houdini/handoff/, building entities with names and addresses), commute modes and arrival times
from CTPP 2017-2021 for the tracts where people WORK (data/ctpp.json, fetch_ctpp.py) instead of City of LA averages.

A SIMULATED TYPICAL DAY, not real-time or observed data. Every person is drawn from public counts and
given a schedule sampled from public survey distributions; everything else is an assumption written
in data/assumptions.json. Run fetch_population.py and fetch_ctpp.py first.

Inputs (data/, see fetch_population.py and fetch_ctpp.py for sources):
  blocks.geojson  2020 Census blocks: residents (POP100)
  lodes.json      LEHD LODES8 2022: jobs by block and sector (WAC), resident workers (RAC), home tract of
                  each block's workers (OD)
  parcels.geojson LA County Assessor: building use, floor area, units (stands in for real-estate listings)
  ctpp.json       CTPP 2017-2021, place of work: means of transport (B202105, C214208 by industry) and arrival
                  time (C202216) for the site's tracts; B202216 (City of LA) only splits the C202216 periods
  acs.json        ACS 2019-23: departure time (B08302) and means (B08301) for the site's residents
  nhts.json       NHTS 2022: trip start and dwell times by purpose (lunch, errands, meals)
  osm.json        OpenStreetMap (ODbL): walking network, food, Metro entrances, bus stops, parking
  ../houdini/handoff/buildings.json, terrain.npy   building entities as stepped prisms from the labelled LiDAR
                  (name, address, use) and the ground (site-model/houdini/tools/export_handoff.py)

People are placed inside the LiDAR building volumes, floor by floor; they walk on the OSM network,
including stairs, bridges and Angels Flight. Census block counts that straddle the site edge are scaled
by the share of the block's area inside the site.

Outputs (../../web/data/):
  population.json  metadata: sources, assumptions, labels, buildings, places, binary layout, checks
  population.bin   nodes, paths, people and their weekday / weekend trips (layout in population.json)
"""
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from shapely import STRtree
from shapely.geometry import Point, Polygon, box, shape
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
POP = HERE / "data"
HANDOFF = HERE.parent / "houdini" / "handoff"
WEB = HERE.parent.parent / "web" / "data"

AS = {k: v["value"] for k, v in json.loads((POP / "assumptions.json").read_text()).items()
      if isinstance(v, dict) and "value" in v}
rng = np.random.default_rng(json.loads((POP / "assumptions.json").read_text())["seed"])
hand = json.loads((HANDOFF / "buildings.json").read_text(encoding="utf-8"))
OX, OY = hand["origin_utm"]
HALF = hand["extent_m"][1]
EXT = box(-HALF, -HALF, HALF, HALF)
DAY = 86400.0
SECTORS = ["", "CNS01", "CNS02", "CNS03", "CNS04", "CNS05", "CNS06", "CNS07", "CNS08", "CNS09", "CNS10",
           "CNS11", "CNS12", "CNS13", "CNS14", "CNS15", "CNS16", "CNS17", "CNS18", "CNS19", "CNS20"]
SECTOR_LABELS = ["", "Agriculture", "Mining, oil & gas", "Utilities", "Construction", "Manufacturing",
                 "Wholesale trade", "Retail trade", "Transportation & warehousing", "Information",
                 "Finance & insurance", "Real estate", "Professional, scientific & technical services",
                 "Management of companies", "Administrative, support & waste services", "Educational services",
                 "Health care & social assistance", "Arts, entertainment & recreation",
                 "Accommodation & food services", "Other services", "Public administration"]
TYPES = ["resident", "worker", "hotel", "visitor"]
MODES = ["stays", "walk", "bike", "bus", "rail", "drive", "taxi / other"]
OFFICE = set(AS["officeSectors"])   # office schedule: hours, lunch out
# weekday presence by sector (audit 2026-10-09): w x office attendance (Kastle) + (1 - w) x the in-person rate, with
# w = officeAttendanceWeight (share of the sector's jobs that work like offices; 0 if absent)
OAW, OTH = AS["officeAttendanceWeight"], AS["otherAttendance"]
SECTOR_ATT = [OAW.get(s, 0) * AS["officeAttendance"] + (1 - OAW.get(s, 0)) * OTH.get(s, OTH["default"]) for s in SECTORS]
load = lambda name: json.loads((POP / name).read_text())


# ---------------------------------------------------------------- terrain
TER = np.load(HANDOFF / "terrain.npy")
tg = hand["terrain"]


def ground(x, y):
    c = min(max((x - tg["x0"]) / tg["step"], 0), tg["cols"] - 1.001)
    r = min(max((tg["y0"] - y) / tg["step"], 0), tg["rows"] - 1.001)
    c0, r0 = int(c), int(r)
    fc, fr = c - c0, r - r0
    t = TER[r0:r0 + 2, c0:c0 + 2]
    return float((t[0, 0] * (1 - fc) + t[0, 1] * fc) * (1 - fr) + (t[1, 0] * (1 - fc) + t[1, 1] * fc) * fr)


def local(geom):
    """Shift an EPSG:26911 shapely geometry to the scene origin."""
    from shapely.affinity import translate
    return translate(geom, -OX, -OY)


# ---------------------------------------------------------------- buildings (entities as LiDAR prisms)
prisms = defaultdict(list)
ENT = {}   # entity id -> its record in the hand-off (name, address, use, parcel)
for e in hand["buildings"]:
    ENT[e["id"]] = e
    for t in e["tiers"]:
        p = Polygon(t["outer"], t["holes"] or None)
        if not p.is_valid:
            p = p.buffer(0)
        if p.area > 1:
            prisms[e["id"]].append((p, t["base"], t["top"]))
BIDS = sorted(prisms)
FOOT = {i: unary_union([p for p, _, _ in prisms[i]]) for i in BIDS}
HEIGHT = {i: max(t for _, _, t in prisms[i]) - min(b for _, b, _ in prisms[i]) for i in BIDS}
foot_tree = STRtree([FOOT[i] for i in BIDS])

# ---------------------------------------------------------------- parcels -> building use and floor area


def use_cat(ut, ud):
    ud = (ud or "").lower()
    if "parking" in ud:
        return "parking"
    if "hotel" in ud:
        return "hotel"
    if "office" in ud or "professional" in ud:
        return "office"
    if ut == "Residential":
        return "residential"
    if ut == "Government" or "government" in ud:
        return "government"
    if ut == "Institutional" or "school" in ud or "college" in ud:
        return "institutional"
    if ut == "Recreational" or "theater" in ud:
        return "recreational"
    if ut == "Commercial" and any(k in ud for k in ("store", "restaurant", "department", "market")):
        return "retail"
    if ut == "Commercial":
        return "office"
    return "unknown"


use_sqft = defaultdict(Counter)   # building -> use -> assessor sqft
use_hint = defaultdict(Counter)   # building -> use -> overlapping parcel area (for parcels with no sqft)
units = Counter()
addr = defaultdict(list)
for f in load("parcels.geojson")["features"]:
    pr = f["properties"]
    try:
        pg = local(shape(f["geometry"])).buffer(0)
    except Exception:
        continue
    cat = use_cat(pr.get("UseType"), pr.get("UseDescription"))
    sq = sum(pr.get(f"SQFTmain{i}") or 0 for i in range(1, 6))
    un = sum(pr.get(f"Units{i}") or 0 for i in range(1, 6))
    hits = []
    for k in foot_tree.query(pg):
        a = FOOT[BIDS[k]].intersection(pg).area
        if a > 1:
            hits.append((BIDS[k], a, a * HEIGHT[BIDS[k]]))
    tot = sum(h[2] for h in hits)
    for bid, a, w in hits:
        use_sqft[bid][cat] += sq * w / tot
        units[bid] += un * w / tot
        use_hint[bid][cat] += a
        if pr.get("SitusFullAddress") and a > 0.3 * FOOT[bid].area and len(addr[bid]) < 3:
            s = " ".join(pr["SitusFullAddress"].split())
            if s not in addr[bid]:
                addr[bid].append(s)

FH = AS["floorHeight"]
_union_cache = {}


def floors_of(bid, fh):
    """[(z, polygon, area)] for each storey of the LiDAR volume, footprint = prisms that reach it."""
    pr = prisms[bid]
    z0 = min(b for _, b, _ in pr)
    top = max(t for _, _, t in pr)
    out = []
    z = z0
    while z + 2.5 <= top:
        idx = tuple(k for k, (_, b, t) in enumerate(pr) if b <= z + 1.0 and t >= z + 2.5)
        if idx:
            key = (bid, idx)
            if key not in _union_cache:
                _union_cache[key] = unary_union([pr[k][0] for k in idx])
            g = _union_cache[key]
            out.append((z, g, g.area))
        z += fh
    return out


B = {}  # building metadata
for bid in BIDS:
    s = use_sqft[bid]
    if sum(s.values()) > 0:
        use = s.most_common(1)[0][0]
    elif use_hint[bid]:
        use = use_hint[bid].most_common(1)[0][0]
    else:
        use = "unknown"
    fh = FH.get(use, FH["default"])
    fl = floors_of(bid, fh)
    modeled = sum(a for _, _, a in fl) * 0.85  # gross -> usable-ish; walls, cores, voids
    sq = sum(s.values())
    B[bid] = {"id": bid, "use": use, "floors": fl, "fh": fh, "modeled_m2": modeled,
              "assessor_sqft": round(sq), "area_m2": sq * 0.0929 if sq > 0 else modeled,
              "area_src": "assessor" if sq > 0 else "LiDAR volume", "units": round(units[bid]),
              "addr": [ENT[bid]["address"]] if ENT[bid].get("address") else addr[bid],
              "name": ENT[bid].get("name") or bid,
              "use_sqft": s, "jobs": 0, "residents": 0, "rooms": 0, "guests": 0}

# ---------------------------------------------------------------- walking network (OSM)
osm = load("osm.json")
WALK = {"footway": 1.0, "pedestrian": 1.0, "steps": 1.05, "path": 1.0, "corridor": 1.0, "living_street": 1.0,
        "cycleway": 1.1, "service": 1.25, "residential": 1.3, "unclassified": 1.3, "tertiary": 1.4,
        "secondary": 1.6, "primary": 1.6, "secondary_link": 2.0, "primary_link": 2.0, "tertiary_link": 2.0,
        "elevator": 1.0}
to_utm = Transformer.from_crs(4326, 26911, always_xy=True)


def ll2loc(lat, lon):
    x, y = to_utm.transform(lon, lat)
    return x - OX, y - OY


nid = {}
NXY = []
edges = {}
cut = set()  # nodes whose way continues outside the site: entry points from beyond the edge


def node(osm_id, x, y):
    if osm_id not in nid:
        nid[osm_id] = len(NXY)
        NXY.append([x, y, None])
    return nid[osm_id]


funicular_nodes = []
for e in osm["elements"]:
    if e["type"] != "way" or "geometry" not in e:
        continue
    t = e.get("tags", {})
    hw = t.get("highway")
    fun = t.get("railway") == "funicular"
    if not fun and (hw not in WALK or t.get("access") in ("no", "private") or t.get("foot") == "no"):
        continue
    if t.get("tunnel") in ("yes", "building_passage") and hw not in ("footway", "pedestrian", "corridor"):
        continue  # the 2nd and 3rd Street tunnels: not for walking
    factor = 0.6 if fun else WALK[hw]
    pts = [ll2loc(g["lat"], g["lon"]) for g in e["geometry"]]
    inside = [abs(x) <= HALF and abs(y) <= HALF for x, y in pts]
    ids = [node(n, x, y) if ins else None for n, (x, y), ins in zip(e["nodes"], pts, inside)]
    elevated = fun or t.get("bridge") in ("yes", "viaduct") or (t.get("layer", "0").lstrip("-").isdigit() and int(t.get("layer", "0")) >= 1)
    if elevated:
        # interior nodes of a bridge / the funicular follow a straight grade between its ends
        run = [k for k, i in enumerate(ids) if i is not None]
        if len(run) >= 2:
            a, b = run[0], run[-1]
            za, zb = ground(*pts[a]), ground(*pts[b])
            d = np.cumsum([0] + [math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1)])
            for k in run[1:-1]:
                if NXY[ids[k]][2] is None:
                    NXY[ids[k]][2] = za + (zb - za) * (d[k] - d[a]) / max(d[b] - d[a], 1e-6)
    if fun:
        funicular_nodes += [i for i in ids if i is not None]
    for k in range(len(ids) - 1):
        i, j = ids[k], ids[k + 1]
        if i is None and j is not None:
            cut.add(j)
        elif j is None and i is not None:
            cut.add(i)
        elif i is not None and i != j:
            L = math.dist(NXY[i][:2], NXY[j][:2])
            key = (min(i, j), max(i, j))
            if key not in edges or edges[key][1] > L * factor:
                edges[key] = (L, L * factor)
for p in NXY:
    if p[2] is None:
        p[2] = ground(p[0], p[1])

n0 = len(NXY)
ei = np.array(list(edges), dtype=np.int64)
ew = np.array([c for _, c in edges.values()])
G = csr_matrix((np.r_[ew, ew], (np.r_[ei[:, 0], ei[:, 1]], np.r_[ei[:, 1], ei[:, 0]])), shape=(n0, n0))
ncomp, lab = connected_components(G, directed=False)
big = np.bincount(lab).argmax()
keep = np.flatnonzero(lab == big)
remap = -np.ones(n0, dtype=np.int64)
remap[keep] = np.arange(len(keep))
XYZ = np.array([NXY[i] for i in keep])  # x east, y north, z up (scene-local)
N = len(XYZ)
E = [(remap[i], remap[j], L, c) for (i, j), (L, c) in edges.items() if remap[i] >= 0 and remap[j] >= 0]
ea = np.array([[a, b] for a, b, _, _ in E])
ec = np.array([c for *_, c in E])
G = csr_matrix((np.r_[ec, ec], (np.r_[ea[:, 0], ea[:, 1]], np.r_[ea[:, 1], ea[:, 0]])), shape=(N, N))
node_tree = STRtree([Point(x, y) for x, y, _ in XYZ])
print(f"network: {N} nodes, {len(E)} edges (largest of {ncomp} components)")


def nearest_node(geom):
    return int(node_tree.nearest(geom))


# ---------------------------------------------------------------- anchors: doors, places, portals
for bid in BIDS:
    B[bid]["door"] = nearest_node(FOOT[bid].exterior if FOOT[bid].geom_type == "Polygon" else FOOT[bid])

places = []   # destinations on site: {name, kind, node, w}
portals = []  # where people enter or leave the site: {name, kind, node}
WFOOD = {"marketplace": 10, "food_court": 4, "restaurant": 1.5, "fast_food": 1.0, "cafe": 0.8, "bar": 1.0, "pub": 1.0}


def elem_point(e):
    if e["type"] == "node":
        return Point(*ll2loc(e["lat"], e["lon"]))
    if "geometry" in e:
        pts = [ll2loc(g["lat"], g["lon"]) for g in e["geometry"]]
        return Polygon(pts).centroid if len(pts) >= 3 else Point(pts[0])
    if "bounds" in e:
        bd = e["bounds"]
        return Point(*ll2loc((bd["minlat"] + bd["maxlat"]) / 2, (bd["minlon"] + bd["maxlon"]) / 2))
    return None


for e in osm["elements"]:
    t = e.get("tags", {})
    p = elem_point(e)
    if p is None or not EXT.contains(p):
        continue
    name = t.get("name")
    am, tour = t.get("amenity"), t.get("tourism")
    if am in WFOOD:
        places.append({"name": name or am.replace("_", " ").title(), "kind": "bar" if am in ("bar", "pub") else "food",
                       "node": nearest_node(p), "w": WFOOD[am]})
    elif tour == "museum" or am in ("arts_centre", "theatre"):
        places.append({"name": name or "Museum", "kind": "culture", "node": nearest_node(p), "w": 1.0})
    elif t.get("railway") == "subway_entrance":
        portals.append({"name": f"Metro · {name}" if name else "Metro entrance", "kind": "rail", "node": nearest_node(p)})
    elif t.get("highway") == "bus_stop":
        portals.append({"name": f"Bus stop · {name}" if name else "Bus stop", "kind": "bus", "node": nearest_node(p)})
    elif am == "parking":
        portals.append({"name": name or "Parking", "kind": "parking", "node": nearest_node(p)})
# the Regional Connector portal from the site model (Grand Av Arts / Bunker Hill), if OSM lacks it
mp = hand["landmarks"]["Metro_Canopy_Glass"]["center"]   # the 4th & Hill portal canopy, from the point cloud
mpn = nearest_node(Point(*mp))
if not any(q["kind"] == "rail" and math.dist(XYZ[q["node"]][:2], mp) < 15 for q in portals):
    portals.append({"name": "Metro · Grand Av Arts/Bunker Hill", "kind": "rail", "node": mpn})
for bid in BIDS:  # Assessor parking structures
    if B[bid]["use"] == "parking":
        street = B[bid]["addr"][0].split(",")[0].split(" LOS ANGELES")[0] if B[bid]["addr"] else ""
        portals.append({"name": f"Parking structure {street}".strip(), "kind": "parking", "node": B[bid]["door"]})
# site edge: where a walkable way leaves the 800 m square (merged within 15 m)
edge_nodes = []
for i in sorted(int(remap[c]) for c in cut if remap[c] >= 0):
    if all(math.dist(XYZ[i][:2], XYZ[j][:2]) > 15 for j in edge_nodes):
        edge_nodes.append(i)
for i in edge_nodes:
    x, y = XYZ[i][:2]
    side = "north" if y > HALF - 25 else "south" if y < -HALF + 25 else "east" if x > 0 else "west"
    portals.append({"name": f"Site edge ({side})", "kind": "edge", "node": i})
# Angels Flight stations: the two ends of the funicular
fn = sorted({int(remap[i]) for i in funicular_nodes if remap[i] >= 0}, key=lambda i: XYZ[i][2])
AF_LOW, AF_UP = (fn[0], fn[-1]) if fn else (None, None)
if fn:
    places.append({"name": "Angels Flight (upper station, California Plaza)", "kind": "culture", "node": AF_UP, "w": 1.0})
gcm = next((p for p in places if "grand central market" in p["name"].lower()), None)
moca = next((p for p in places if p["name"] == "Museum of Contemporary Art"), None)


def find_place(v, name):
    """A visitor destination: the OSM place whose name matches v['match'], else a place at v['latlon']."""
    if "match" in v:
        f = next((p for p in places if re.search(v["match"], p["name"], re.I)), None)
        if f:
            return f
    if "latlon" in v:
        pt = Point(*ll2loc(*v["latlon"]))
        if EXT.contains(pt):
            places.append({"name": name, "kind": "culture", "node": nearest_node(pt), "w": 1.0})
            return places[-1]
    return None


DEST = {name: find_place(v, name) for name, v in AS["visitors"].items() if "annual" in v}
print("visitor destinations:", {k: (v["name"] if v else None) for k, v in DEST.items()})
print(f"{len(places)} places, {len(portals)} portals ({Counter(p['kind'] for p in portals)}), GCM={bool(gcm)}, MOCA={bool(moca)}")

# shortest paths from every anchor
anchor_nodes = sorted({B[b]["door"] for b in BIDS} | {p["node"] for p in places} | {p["node"] for p in portals})
arow = {n: k for k, n in enumerate(anchor_nodes)}
D, PRED = dijkstra(G, directed=False, indices=anchor_nodes, return_predecessors=True)
print(f"dijkstra from {len(anchor_nodes)} anchors")

paths, path_id = [], {}


def path_between(a, b):
    """(path index, reversed) for the shortest path a -> b; a or b must be an anchor."""
    if (a, b) in path_id:
        return path_id[(a, b)], False
    if (b, a) in path_id:
        return path_id[(b, a)], True
    src, dst, rev = (a, b, False) if a in arow else (b, a, True)
    pr = PRED[arow[src]]
    seq = [dst]
    while seq[-1] != src:
        p = pr[seq[-1]]
        if p < 0:
            raise ValueError("unreachable")
        seq.append(int(p))
    seq.reverse()
    path_id[(src, dst)] = len(paths)
    paths.append(seq)
    return path_id[(src, dst)], rev


def path_len(a, b):
    pid, _ = path_between(a, b)
    s = paths[pid]
    return sum(math.dist(XYZ[s[k]], XYZ[s[k + 1]]) for k in range(len(s) - 1))


def netdist(a, b):
    return D[arow[a], b] if a in arow else D[arow[b], a]


# ---------------------------------------------------------------- distributions
acs, nhts = load("acs.json"), load("nhts.json")
ARR_EDGES = [0, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 10, 11, 12, 16, 24]  # B08602 / B08302 bins (hours)


def bins_sampler(row, table):
    w = np.array([row[f"{table}_E{k:03d}"] or 0 for k in range(2, 16)], float)
    w /= w.sum()
    return lambda: (lambda k: rng.uniform(ARR_EDGES[k], ARR_EDGES[k + 1]))(rng.choice(14, p=w)) * 3600


# CTPP 2017-2021, place of work (data/ctpp.json): the site's tracts give the Downtown totals; the City of LA table
# B202216 only splits each of the four C202216 periods into the finer ARR_EDGES bins.
CT = load("ctpp.json")["tables"]


def ct_sum(t):
    """Estimates of table t summed over the site's tracts (or its one row, for the City of LA tables): {label: workers}.
    The LA County row of B202105 is only there for comparison."""
    tot = defaultdict(float)
    rows = [r for r in CT[t]["rows"].values() if "Census Tract" in r["name"]] or list(CT[t]["rows"].values())
    for r in rows:
        for lab, v in zip(CT[t]["labels"], r["estimate"]):
            tot[lab] += v or 0
    return tot


def is_drive(mode_label):
    return mode_label.startswith("Car, truck, or van") or mode_label.startswith("Drive alone or carpool")


ARR_BINS = ["12:00 a.m. to 4:59 a.m.", "5:00 a.m. to 5:29 a.m.", "5:30 a.m. to 5:59 a.m.", "6:00 a.m. to 6:29 a.m.",
            "6:30 a.m. to 6:59 a.m.", "7:00 a.m. to 7:29 a.m.", "7:30 a.m. to 7:59 a.m.", "8:00 a.m. to 8:29 a.m.",
            "8:30 a.m. to 8:59 a.m.", "9:00 a.m. to 9:59 a.m.", "10:00 a.m. to 10:59 a.m.", "11:00 a.m. to 11:59 a.m.",
            "12:00 p.m. to 3:59 p.m.", "4:00 p.m. to 11:59 p.m."]                      # = the ARR_EDGES bins
PERIODS = ["5:00 a.m. to 8:59 a.m.", "9:00 a.m. to 11:59 a.m.", "12:00 p.m. to 3:59 p.m.", "4:00 p.m. to 4:59 a.m."]
BIN_PERIOD = [3, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 3]
city = ct_sum("B202216")
site_arr = ct_sum("C202216")


def arrival_sampler(drive):
    w_city = np.array([sum(v for k, v in city.items() if k.startswith(b + "!!") and "Total" not in k
                           and k.split("!!")[1].strip() != "Worked from home" and is_drive(k.split("!!")[1]) == drive)
                       for b in ARR_BINS])
    cls = "Drive alone or carpool" if drive else "Other"
    w_site = np.array([sum(v for k, v in site_arr.items() if k.startswith(pd + "!!" + cls)) for pd in PERIODS])
    w = np.zeros(len(ARR_BINS))
    for k in range(len(ARR_BINS)):
        same = [j for j in range(len(ARR_BINS)) if BIN_PERIOD[j] == BIN_PERIOD[k]]
        w[k] = w_site[BIN_PERIOD[k]] * w_city[k] / max(w_city[same].sum(), 1)
    w /= w.sum()
    return lambda: (lambda k: rng.uniform(ARR_EDGES[k], ARR_EDGES[k + 1]))(rng.choice(len(w), p=w)) * 3600


arrival = {True: arrival_sampler(True), False: arrival_sampler(False)}
departure_by_tract = {g[-11:]: bins_sampler(v, "B08302") for g, v in acs["B08302_departure_time_residence"].items()
                      if g.startswith("1400000US") and (v["B08302_E001"] or 0) > 0}


def means_shares(v, t):
    g = lambda k: v[f"{t}_E{k:03d}"] or 0
    return {"drive": g(2), "bus": g(11), "rail": g(12) + g(13) + g(14), "taxi / other": g(15) + g(16) + g(17) + g(20),
            "bike": g(18), "walk": g(19)}


# means of transport of the people who work in the site's tracts (B202105), commuters only (working from home is a
# place of work at home, so it hardly occurs here); C214208 gives the drive share per industry group
b105 = ct_sum("B202105")
g105 = lambda *ks: sum(v for k, v in b105.items() if any(k.startswith(x) for x in ks))
work_modes = {"drive": g105("Car, truck, or van"), "bus": g105("Bus"),
              "rail": g105("Subway or elevated rail", "Long-distance train", "Light rail"),
              "walk": g105("Walked"), "bike": g105("Bicycle"),
              "taxi / other": g105("Ferryboat", "Taxicab", "Motorcycle", "Other means")}
WFH_SHARE = b105["Worked from home"] / b105["Total, means of transportation"]
COMMUTERS = sum(work_modes.values())
SHARE = {k: v / COMMUTERS for k, v in work_modes.items()}
c208 = ct_sum("C214208")
IND_GROUP = {"Basic": ["CNS01", "CNS02", "CNS03", "CNS04", "CNS05", "CNS06", "CNS08"], "Retail trade": ["CNS07"],
             "Government": ["CNS20"]}
IND_GROUP["Service"] = [x for x in SECTORS[1:] if x not in sum(IND_GROUP.values(), [])]
DRIVE_BY_SECTOR = {}
for lab, tot in c208.items():
    if not lab.startswith("Total, means of transportation!!") or "Total, all industries" in lab:
        continue
    grp = lab.split("!!", 1)[1]
    drive = next(v for k, v in c208.items() if k.startswith("Drive alone or carpool") and k.endswith("!!" + grp))
    key = next(g for g in IND_GROUP if grp.startswith(g))
    for sec in IND_GROUP[key]:
        DRIVE_BY_SECTOR[sec] = min(drive / max(tot * (1 - WFH_SHARE), 1), 0.98)
print("CTPP commuters", round(COMMUTERS), {k: f"{v:.0%}" for k, v in SHARE.items()}, "drive by industry",
      {g: f"{DRIVE_BY_SECTOR[IND_GROUP[g][0]]:.0%}" for g in IND_GROUP})
res_modes = {g[-11:]: means_shares(v, "B08301") for g, v in acs["B08301_means_residence"].items() if g.startswith("1400000US")}
hh_size = {g[-11:]: v["B25010_E001"] for g, v in acs["B25010_household_size"].items()}


def pick(d):
    k = list(d)
    w = np.array([d[x] for x in k], float)
    return k[rng.choice(len(k), p=w / w.sum())]


def smooth(h, width=2):
    h = np.array(h, float)
    k = np.exp(-0.5 * (np.arange(-3 * width, 3 * width + 1) / width) ** 2)
    return np.convolve(np.r_[h[-3 * width:], h, h[:3 * width]], k / k.sum(), "valid")


def time_sampler(keys, lo_h, hi_h, day):
    h = sum(np.array(nhts["start"].get(f"{day}|{k}", [0] * 96), float) for k in keys)
    h = smooth(h)
    b = np.arange(96)
    h[(b < lo_h * 4) | (b >= hi_h * 4)] = 0
    if h.sum() == 0:
        return lambda: rng.uniform(lo_h, hi_h) * 3600
    p = h / h.sum()
    return lambda: (rng.choice(96, p=p) + rng.random()) * 900


def dwell_sampler(keys, lo_min, hi_min, day):
    h = sum(np.array(nhts["dwell"].get(f"{day}|{k}", [0] * 48), float) for k in keys)
    b = np.arange(48) * 10
    h[(b + 10 <= lo_min) | (b >= hi_min)] = 0
    if h.sum() == 0:
        return lambda: rng.uniform(lo_min, hi_min) * 60
    p = h / h.sum()
    return lambda: min(max((rng.choice(48, p=p) + rng.random()) * 10, lo_min), hi_min) * 60


# ---------------------------------------------------------------- people: spots, choices, trips
SPEED_M, SPEED_SD = AS["walkSpeed"]


def floor_spot(bid, residential=False):
    """A random spot on a random storey of the building, weighted by floor area (scene-local x, y, z)."""
    fl = B[bid]["floors"]
    if not fl:
        c = FOOT[bid].representative_point()
        return (c.x, c.y, ground(c.x, c.y))
    w = np.array([a for _, _, a in fl])
    z, poly, _ = fl[rng.choice(len(fl), p=w / w.sum())]
    minx, miny, maxx, maxy = poly.bounds
    inner = poly.buffer(-1.5) if poly.area > 60 else poly
    if inner.is_empty:
        inner = poly
    for _ in range(40):
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if inner.contains(Point(x, y)):
            return (x, y, z)
    c = poly.representative_point()
    return (c.x, c.y, z)


# trip record: [t0, t1, a, b, from_kind, to_kind, flags, purpose, orig_anchor, dest_anchor]
SPOT_HIDDEN, SPOT_HOME, SPOT_WORK, SPOT_PLACE = 0, 1, 2, 3
F_ATTEND, F_EVENT = 1, 2
PURPOSES = ["arrive for work", "leave work", "lunch", "back from lunch", "outing", "back home", "visit",
            "leave the site", "after-work stop", "head out", "come home", "event", "ride Angels Flight"]
P = {k: i for i, k in enumerate(PURPOSES)}
anchor_names = [p["name"] for p in places] + [p["name"] for p in portals]
place_idx = {id(p): k for k, p in enumerate(places)}
portal_idx = {id(p): len(places) + k for k, p in enumerate(portals)}

people = []  # dicts: type, mode, sector, home(bid, spot), work(bid, spot), dist_km, bearing, tract, trips{day:[]}


def spot_xyz(person, kind, node):
    if kind == SPOT_HOME:
        return person["home_spot"]
    if kind == SPOT_WORK:
        return person["work_spot"]
    x, y, z = XYZ[node]
    return (x, y, z)


def leg_seconds(person, a, b, fk, tk, speed):
    """Duration of a trip: spot -> node a -> network -> node b -> spot, elevators included."""
    t = path_len(a, b) / speed
    for kind, n in ((fk, a), (tk, b)):
        if kind in (SPOT_HOME, SPOT_WORK):
            sx, sy, sz = spot_xyz(person, kind, n)
            nx, ny, nz = XYZ[n]
            dz = abs(sz - nz)
            t += math.hypot(sx - nx, sy - ny) / speed + (dz / 2.5 + AS["elevatorWait"] if dz > 3 else dz / speed)
    return t


def add_trip(person, day, t_start, a, b, fk, tk, purpose, flags=0, orig=-1, dest=-1, backwards=False):
    """Append a trip starting at t_start (or ending at t_start if backwards); returns its end time."""
    dur = leg_seconds(person, a, b, fk, tk, person["speed"])
    t0 = t_start - dur if backwards else t_start
    t0 %= DAY
    t1 = t0 + dur
    if t1 >= DAY:  # never straddle midnight: nudge the trip back into the day
        t0, t1 = DAY - 1 - dur, DAY - 1
    person["trips"][day].append([t0, t1, a, b, fk, tk, flags, P[purpose], orig, dest])
    return t1


def softmin(cands, cost, temp):
    c = np.array([cost(x) for x in cands], float)
    w = np.exp(-(c - c.min()) / temp)
    return cands[rng.choice(len(cands), p=w / w.sum())]


by_kind = defaultdict(list)
for p in portals:
    by_kind[p["kind"]].append(p)

# Metro lines (user, 2026-10-09: option B). A rider can only use the stations of the line they ride: B/D (Civic
# Center, Pershing Square) or A/E (Little Tokyo, Historic Broadway, Grand Av Arts); 7th St/Metro Center serves all
# four. Each entrance belongs to its nearest station. The line is chosen by the direction of home: each line branch
# (metroLines) pulls riders whose home bearing from Y-1 is close to its own, with a von Mises weight exp(kappa (cos d - 1)).
# People with no known home direction (residents going out, hotel guests, visitors) get a random bearing.
# lineWeight (calibrated, user 2026-10-09) scales B/D against A/E so the two groups' shares of the five compared
# stations match Metro's counts; the per-station split is then left to the model.
MB, ML = AS["metroBoardings"], AS["metroLines"]
st_xy = {k: ll2loc(*v["latlon"]) for k, v in MB.items()}
station_of = {id(q): min(st_xy, key=lambda k: math.dist(XYZ[q["node"]][:2], st_xy[k])) for q in by_kind["rail"]}
branches = [(b["line"], math.degrees(math.atan2(*ll2loc(*b["latlon"]))) % 360) for b in ML["branches"]]


def pick_line(bearing=None):
    if bearing is None:
        bearing = rng.uniform(0, 360)
    w = np.array([ML["lineWeight"].get(l, 1.0) * math.exp(ML["kappa"] * (math.cos(math.radians(bearing - b)) - 1))
                  for l, b in branches])
    return branches[rng.choice(len(w), p=w / w.sum())][0]


# stationWeight (calibrated, user 2026-10-09): how strongly each station draws riders of its lines, on top of the
# walking distance (probability x weight). Fitted so each station's boardings match Metro's; Little Tokyo is held at
# 1 (most of its riders live outside the site), 7th St/Metro Center is not compared (transfer hub).
SW = AS["stationWeight"]


def rail_for(door, line):
    c = [q for q in by_kind["rail"] if line in MB[station_of[id(q)]]["lines"]]
    T = AS["stationChoiceTemp"]
    return softmin(c, lambda q: netdist(q["node"], door) - T * math.log(SW.get(station_of[id(q)], 1.0)), T)



def portal_for(mode, door, bearing=None, bid=None, line=None):
    """Where a person of this mode enters/leaves the site, for a building door."""
    if mode == "rail":
        p = rail_for(door, line or pick_line(bearing))
    elif mode == "bus":
        p = softmin(by_kind["bus"], lambda q: netdist(q["node"], door), 90)
    elif mode in ("drive", "taxi / other"):
        if mode != "drive" or (bid and B[bid]["modeled_m2"] >= AS["ownGarageMinArea"]):
            return None  # own garage / curbside: appears at the building door
        p = softmin(by_kind["parking"], lambda q: netdist(q["node"], door), 120)
    else:  # walk / bike: the site edge that faces home
        if bearing is None:
            p = by_kind["edge"][rng.integers(len(by_kind["edge"]))]
        else:
            def miss(q):
                x, y = XYZ[q["node"]][:2]
                d = (math.degrees(math.atan2(x, y)) - bearing + 540) % 360 - 180
                return abs(d)
            p = softmin(by_kind["edge"], miss, 25)
    return p


def food_near(door, kinds=("food",), radius=650, temp=220):
    c = [p for p in places if p["kind"] in kinds and netdist(p["node"], door) <= radius]
    if not c:
        c = [p for p in places if p["kind"] in kinds]
    w = np.array([p["w"] * math.exp(-netdist(p["node"], door) / temp) for p in c])
    return c[rng.choice(len(c), p=w / w.sum())]


def new_person(kind, **kw):
    p = {"type": TYPES.index(kind), "mode": 0, "sector": 0, "rank": int(rng.integers(256)), "home_bid": None,
         "work_bid": None, "home_spot": None, "work_spot": None, "dist_km": 0.0, "bearing": 0.0, "tract": "",
         "speed": float(np.clip(rng.normal(SPEED_M, SPEED_SD), 0.6, 2.0)), "trips": {"weekday": [], "weekend": []}}
    p.update(kw)
    people.append(p)
    return p


# ---------------------------------------------------------------- Census blocks -> buildings
blocks = {}
for f in load("blocks.geojson")["features"]:
    g = local(shape(f["geometry"])).buffer(0)
    blocks[f["properties"]["GEOID"]] = {"geom": g, "frac": g.intersection(EXT).area / g.area,
                                        "pop": f["properties"]["POP100"] or 0, "hu": f["properties"]["HU100"] or 0}
bld_block = {}
for bid in BIDS:
    c = FOOT[bid].representative_point()
    for g, b in blocks.items():
        if b["geom"].contains(c):
            bld_block[bid] = g
            break
block_blds = defaultdict(list)
for bid, g in bld_block.items():
    block_blds[g].append(bid)


def near_blds(g, n=3):
    c = blocks[g]["geom"].centroid
    return sorted(BIDS, key=lambda b: FOOT[b].distance(c))[:n]


def scaled(counts, total):
    """Integer counts proportional to `counts`, summing to total (largest remainder)."""
    k = list(counts)
    v = np.array([counts[x] for x in k], float)
    if v.sum() == 0 or total <= 0:
        return {}
    q = v / v.sum() * total
    n = np.floor(q).astype(int)
    for i in np.argsort(-(q - n))[: total - n.sum()]:
        n[i] += 1
    return {x: int(c) for x, c in zip(k, n) if c > 0}


lodes = load("lodes.json")
JW, AFF = AS["jobWeightByUse"], AS["sectorUseAffinity"]
jobs_by_block = {}
dropped = Counter()
for g, wac in lodes["wac"].items():
    if g not in blocks:
        continue
    total = int(round(wac["C000"] * blocks[g]["frac"]))
    cand = block_blds.get(g) or near_blds(g)
    jobs = []
    for sec, n in scaled({s: wac.get(s, 0) for s in SECTORS[1:]}, total).items():
        w = np.array([B[b]["area_m2"] * JW.get(B[b]["use"], JW["unknown"]) * AFF.get(sec, {}).get(B[b]["use"], 1.0)
                      for b in cand])
        if w.sum() == 0:
            dropped[g] += n
            continue
        for b, m in zip(cand, rng.multinomial(n, w / w.sum())):
            jobs += [(b, sec)] * int(m)
    rng.shuffle(jobs)
    jobs_by_block[g] = jobs
print("jobs placed", sum(len(j) for j in jobs_by_block.values()), "dropped", sum(dropped.values()))

# residents (user, 2026-10-08: "the rule that fits our data best", option B). The 2020 Census adds noise to block
# population counts (disclosure avoidance) but keeps housing-unit counts exact, so a block's residents are estimated as
#   housing units (HU100) x residential occupancy x persons per household (ACS B25010, the block's tract);
# a block with no housing units keeps its Census count only if it is at least groupQuartersMinPop (group quarters:
# dormitories, care homes, shelters); smaller counts there are taken as noise. They live in the block's own buildings:
#   1. on-site share = the share of the block's building footprint (LARIAC 2020, the whole block, also outside the
#      site) that lies inside the site; the block's land area does not say where people live;
#   2. inside the block, by Assessor housing units of its buildings; if the Assessor lists no units there (tax-exempt
#      or converted buildings, dormitories), by the floor area of its residential buildings, else of all its buildings
#      (blocks with residents but no housing units are group quarters: dormitories, care homes, shelters);
#   3. a block whose buildings are all missing from the hand-off keeps its residents in the nearest hand-off building
#      within NEAR_M (the same building, slightly misaligned); anything else is reported, not placed.
NEAR_M = 30.0
LARIAC = HERE.parent / "houdini" / "in" / "lariac_3km.geojson"     # git-ignored input of the Houdini pipeline
lar = []
for f in json.loads(LARIAC.read_text(encoding="utf-8"))["features"]:
    try:
        lar.append(local(shape(f["geometry"])).buffer(0))
    except Exception:
        pass
lar_tree = STRtree(lar)


def onsite_share(g):
    fp = [lar[i].intersection(g) for i in lar_tree.query(g)]
    tot = sum(x.area for x in fp)
    return sum(x.intersection(EXT).area for x in fp) / tot if tot > 1 else 0.0


def block_buildings(g):
    """Hand-off buildings with a real part of their footprint in block g (>= 50 m2 and >= 10 %): large complexes
    span several blocks (Angelus Plaza, Two California Plaza)."""
    geom = blocks[g]["geom"]
    out = []
    for x in BIDS:
        if FOOT[x].intersects(geom):
            a = FOOT[x].intersection(geom).area
            if a >= 50 and a >= 0.1 * FOOT[x].area:
                out.append(x)
    return out


res_by_block = defaultdict(list)
res_log = {}     # block -> {"residents", "share", "rule", "buildings"}
hh_size = {g[-11:]: v["B25010_E001"] for g, v in acs["B25010_household_size"].items() if v.get("B25010_E001")}
HH_DEFAULT = float(np.median([v for k, v in hh_size.items() if len(k) == 11 and k.startswith("06037")]))
res_census = res_noise = 0
for g, b in blocks.items():
    share = onsite_share(b["geom"])
    if share == 0:
        continue
    if b["hu"] > 0:
        est = b["hu"] * AS["residentialOccupancy"] * hh_size.get(g[:11], HH_DEFAULT)
    elif b["pop"] >= AS["groupQuartersMinPop"]:
        est = b["pop"]
    else:
        res_noise += round(b["pop"] * share)
        est = 0
    res_census += round(b["pop"] * share)
    n = int(round(est * share))
    if n == 0:
        continue
    cand = block_buildings(g)
    rule = "units"
    if not cand:
        near = sorted(BIDS, key=lambda x: FOOT[x].distance(b["geom"]))[:1]
        if near and FOOT[near[0]].distance(b["geom"]) <= NEAR_M:
            cand, rule = near, "nearest building"
        else:
            dropped["residents " + g] += n
            res_log[g] = {"residents": n, "share": round(share, 2), "rule": "not placed", "buildings": []}
            continue
    w = np.array([B[x]["units"] * FOOT[x].intersection(b["geom"]).area / FOOT[x].area for x in cand], float)
    if w.sum() <= 0:
        resid = [x for x in cand if B[x]["use"] == "residential"]
        cand, rule = (resid, "residential floor area") if resid else (cand, "floor area (group quarters)" if blocks[g]["hu"] == 0
                                                                          else "floor area")
        w = np.array([max(B[x]["modeled_m2"], 1) for x in cand], float)
    res_log[g] = {"residents": n, "share": round(share, 2), "rule": rule, "buildings": [B[x]["name"] for x in cand][:4]}
    for x, m in zip(cand, rng.multinomial(n, w / w.sum())):
        for _ in range(int(m)):
            p = new_person("resident", home_bid=x, tract=g[:11])
            p["home_spot"] = floor_spot(x, True)
            res_by_block[g].append(p)
            B[x]["residents"] += 1
print("residents", sum(len(v) for v in res_by_block.values()), f"(Census count on site {res_census}, of which {res_noise} "
      f"in blocks without housing taken as noise)", "| by rule:",
      dict(Counter(v["rule"] for v in res_log.values() for _ in range(v["residents"]))))
for g, v in sorted(res_log.items(), key=lambda kv: -kv[1]["residents"]):
    if v["rule"] != "units":
        print(f"  block {g[-4:]}: {v['residents']} residents ({v['share']:.0%} on site) -> {v['rule']}: {v['buildings']}")

# resident workers (RAC) and the share who work on site (OD home blocks inside the site)
for g, plist in res_by_block.items():
    rac = lodes["rac"].get(g)
    if not rac:
        continue
    nw = min(int(round(rac["C000"] * blocks[g]["frac"])), len(plist))
    secs = []
    for s, n in scaled({s: rac.get(s, 0) for s in SECTORS[1:]}, nw).items():
        secs += [s] * n
    for p, s in zip(rng.permutation(plist)[:nw], secs):
        p["sector"] = SECTORS.index(s)
        p["worker"] = True

# ---------------------------------------------------------------- jobs -> people (workers + residents)
tll = load("tracts_ll.json")["tracts"]
ll_o = Transformer.from_crs(26911, 4326, always_xy=True).transform(OX, OY)[::-1]   # (lat, lon) of the origin


def tract_geo(t):
    lat, lon = tll.get(t, ll_o)
    x, y = ll2loc(lat, lon)
    return math.hypot(x, y) / 1000, math.degrees(math.atan2(x, y)) % 360


def commute_mode(km, sec, near_share):
    """CTPP shares for the people who work here: drive by industry group (C214208); walking and cycling only from
    within walkMaxKm, scaled so their overall shares match B202105; the rest by bus / rail / other (B202105)."""
    if rng.random() < DRIVE_BY_SECTOR.get(sec, SHARE["drive"]):
        return "drive"
    nondrive = 1 - SHARE["drive"]
    if km <= AS["modeByDistance"]["walkMaxKm"]:
        pw = min(SHARE["walk"] / max(nondrive * near_share, 1e-6), 0.9)
        pb = min(SHARE["bike"] / max(nondrive * near_share, 1e-6), 0.9 - pw)
        r = rng.random()
        if r < pw:
            return "walk"
        if r < pw + pb:
            return "bike"
    return pick({k: work_modes[k] for k in ("bus", "rail", "taxi / other")})


od = lodes["od_by_home_tract"]
commuters = []   # (person, sector): their mode is drawn once everyone's distance is known
for g, jobs in jobs_by_block.items():
    homes = od.get(g, {})
    if not jobs:
        continue
    keys = list(homes) or ["06037207502"]
    w = np.array([homes.get(k, 1) for k in keys], float)
    choice = rng.choice(len(keys), size=len(jobs), p=w / w.sum())
    for (bid, sec), k in zip(jobs, choice):
        home = keys[k]
        B[bid]["jobs"] += 1
        spot = floor_spot(bid)
        if len(home) > 11:  # lives on site: give the job to a resident worker of that block, if any free
            pool = [p for p in res_by_block.get(home, []) if p.get("worker") and p["work_bid"] is None]
            if pool:
                p = pool[rng.integers(len(pool))]
                p.update(work_bid=bid, work_spot=spot, sector=SECTORS.index(sec), mode=MODES.index("walk"))
                continue
            home = home[:11]
        km, br = tract_geo(home)
        commuters.append((new_person("worker", work_bid=bid, work_spot=spot, sector=SECTORS.index(sec), tract=home,
                                     dist_km=km, bearing=br), sec))
NEAR = float(np.mean([p["dist_km"] <= AS["modeByDistance"]["walkMaxKm"] for p, _ in commuters]))
for p, sec in commuters:
    p["mode"] = MODES.index(commute_mode(p["dist_km"], sec, NEAR))
mode_check = Counter(MODES[p["mode"]] for p, _ in commuters)
print("workers", sum(p["type"] == 1 for p in people), f"(from within {AS['modeByDistance']['walkMaxKm']} km: {NEAR:.0%})",
      {k: f"{v / len(commuters):.0%}" for k, v in mode_check.most_common()})

# hotel guests (audit 2026-10-09): visitor hotels with published room counts (hotelRooms, matched by address).
# Other Assessor "hotel & motels" parcels in the site are mostly residential hotels (SROs in Skid Row and the Historic
# Core): their people are Census residents already, so they get no guests.
HR = AS["hotelRooms"]
by_addr = {}
for bid in BIDS:
    for a in B[bid]["addr"]:
        by_addr.setdefault(a.split(",")[0].strip().upper(), bid)
hotel_bids = {}
for name, h in HR.items():
    bid = next((by_addr[a.upper()] for a in h["addr"] if a.upper() in by_addr), None)
    if bid is None:
        print("hotel not found in the buildings:", name)
        continue
    hotel_bids[bid] = hotel_bids.get(bid, 0) + h["rooms"]
for bid, rooms in hotel_bids.items():
    B[bid]["rooms"] = rooms
    n = int(rng.binomial(rooms, AS["hotelOccupancy"]) * AS["guestsPerRoom"])
    B[bid]["guests"] = n
    for _ in range(n):
        p = new_person("hotel", home_bid=bid)
        p["home_spot"] = floor_spot(bid)
print("hotel guests", sum(p["type"] == 2 for p in people))

# ---------------------------------------------------------------- schedules
work_hours = AS["workHours"]
WEEKEND_SHARE = AS["weekendWorkShare"]
lunch_t = {d: time_sampler(["03>13"], 10.75, 14.5, d) for d in ("weekday", "weekend")}
lunch_dw = {d: dwell_sampler(["03>13"], 15, 75, d) for d in ("weekday", "weekend")}
outing_t = {d: time_sampler(["01>11", "01>13", "01>15", "01>17", "01>16", "01>12"], 7, 22.5, d) for d in ("weekday", "weekend")}
outing_dw = {d: dwell_sampler(["to=11", "to=13", "to=15", "to=17", "to=12"], 15, 240, d) for d in ("weekday", "weekend")}
meal_t = {d: time_sampler(["to=13"], 0, 24, d) for d in ("weekday", "weekend")}
meal_dw = {d: dwell_sampler(["to=13"], 20, 120, d) for d in ("weekday", "weekend")}


def state_at(trips, t, default):
    """Where the person is at time t: the end of the last finished trip (the day wraps around)."""
    done = [x for x in trips if x[1] <= t]
    if any(x[0] <= t < x[1] for x in trips):
        return -1  # moving
    if done:
        return max(done, key=lambda x: x[1])[5]
    return max(trips, key=lambda x: x[1])[5] if trips else default


def home_free(trips, t0, t1):
    """True if the person is at home from t0 to t1 with no trip in between."""
    return (all(t1 + 120 < x[0] or t0 - 120 > x[1] for x in trips)
            and state_at(trips, t0, SPOT_HOME) == SPOT_HOME)


def schedule_work(p, day, door, start, end, flags):
    """Commute in, optional lunch out, optional after-work stop, commute out.
    start / end: (node, spot kind, anchor index) where the commute begins and ends."""
    office = SECTORS[p["sector"]] in OFFICE
    mean, sd = work_hours["office" if office else "shift"]
    arrive = arrival[MODES[p["mode"]] == "drive"]()
    stay = float(np.clip(rng.normal(mean, sd), 4, 12)) * 3600
    add_trip(p, day, arrive, start[0], door, start[1], SPOT_WORK, "arrive for work", flags, start[2], -1, backwards=True)
    t_out = arrive + stay
    if office and arrive < 11.5 * 3600 and t_out > 14 * 3600 and rng.random() < AS["lunchOutShare"]:
        L = lunch_t[day]()
        if arrive + 300 < L < t_out - 3600:
            f = food_near(door)
            back = add_trip(p, day, L, door, f["node"], SPOT_WORK, SPOT_PLACE, "lunch", flags, -1, place_idx[id(f)])
            add_trip(p, day, back + lunch_dw[day](), f["node"], door, SPOT_PLACE, SPOT_WORK, "back from lunch", flags, place_idx[id(f)], -1)
    going = "back home" if end[1] == SPOT_HOME else "leave the site"
    if 16 * 3600 < t_out < 20 * 3600 and rng.random() < AS["afterWorkOutShare"]:
        f = food_near(door, ("food", "bar"))
        t = add_trip(p, day, t_out, door, f["node"], SPOT_WORK, SPOT_PLACE, "after-work stop", flags, -1, place_idx[id(f)])
        add_trip(p, day, t + rng.uniform(45, 100) * 60, f["node"], end[0], SPOT_PLACE, end[1], going, flags, place_idx[id(f)], end[2])
    else:
        add_trip(p, day, t_out % DAY, door, end[0], SPOT_WORK, end[1], "leave work", flags, -1, end[2])


def offsite_portal(p, door):
    """Out-of-site trips by residents and guests: their tract's means of transport."""
    modes = res_modes.get(p["tract"]) or res_modes.get("06037207502")
    m = pick(modes) if modes else "walk"
    return m, portal_for(m, door, None, p["home_bid"])


def outings(p, day, n, door):
    for _ in range(n):
        t = outing_t[day]()
        dw = outing_dw[day]()
        if rng.random() < AS["residentOutings"]["onSiteShare"]:
            f = softmin([q for q in places if q["kind"] != "bar"] or places, lambda q: netdist(q["node"], door) / q["w"], 250)
            dest, dk, di, oi = f["node"], SPOT_PLACE, place_idx[id(f)], place_idx[id(f)]
        else:
            _, q = offsite_portal(p, door)
            dest, dk = (q["node"], SPOT_HIDDEN) if q else (door, SPOT_HIDDEN)
            di = oi = portal_idx[id(q)] if q else -1
        go = leg_seconds(p, door, dest, SPOT_HOME, dk, p["speed"])
        if t + 2 * go + dw > DAY - 60 or not home_free(p["trips"][day], t, t + 2 * go + dw):
            continue
        t1 = add_trip(p, day, t, door, dest, SPOT_HOME, dk, "outing", 0, -1, di)
        add_trip(p, day, t1 + dw, dest, door, dk, SPOT_HOME, "back home", 0, oi, -1)


for p in [q for q in people if q["type"] in (0, 1)]:
    for day in ("weekday", "weekend"):
        sec = SECTORS[p["sector"]]
        works = day == "weekday" or rng.random() < WEEKEND_SHARE.get(sec, WEEKEND_SHARE["default"])
        if p["type"] == 1:  # in-commuter
            if not works:
                continue
            door = B[p["work_bid"]]["door"]
            q = portal_for(MODES[p["mode"]], door, p["bearing"], p["work_bid"])
            ends = (q["node"], SPOT_HIDDEN, portal_idx[id(q)]) if q else (door, SPOT_HIDDEN, -1)
            schedule_work(p, day, door, ends, ends, F_ATTEND if day == "weekday" else 0)
            continue
        # residents
        hdoor = B[p["home_bid"]]["door"]
        flags = F_ATTEND if day == "weekday" else 0
        if p.get("worker") and works:
            if p["work_bid"] is not None:  # works on site: walks from home
                schedule_work(p, day, B[p["work_bid"]]["door"], (hdoor, SPOT_HOME, -1), (hdoor, SPOT_HOME, -1), flags)
            else:
                m, q = offsite_portal(p, hdoor)
                p["mode"] = MODES.index(m)
                dep = departure_by_tract.get(p["tract"], arrival[False])()
                node, di = (q["node"], portal_idx[id(q)]) if q else (hdoor, -1)
                t1 = add_trip(p, day, dep, hdoor, node, SPOT_HOME, SPOT_HIDDEN, "head out", flags, -1, di)
                back = t1 + float(np.clip(rng.normal(9.5, 1.0), 5, 13)) * 3600
                if back < DAY - 1800:
                    add_trip(p, day, back, node, hdoor, SPOT_HIDDEN, SPOT_HOME, "come home", flags, di, -1)
            n = rng.poisson(AS["residentOutings"]["weekdayWorker" if day == "weekday" else "weekend"])
        else:
            n = rng.poisson(AS["residentOutings"]["weekdayNonWorker" if day == "weekday" else "weekend"])
        outings(p, day, n, hdoor)

# hotel guests
HG = AS["hotelGuests"]
for p in [q for q in people if q["type"] == 2]:
    door = B[p["home_bid"]]["door"]
    for day in ("weekday", "weekend"):
        if rng.random() > HG["dayOutShare"]:
            outings(p, day, 1, door)
            continue
        lo, hi = (7.5, 11) if day == "weekday" else (8.5, 12)
        t = rng.uniform(lo, hi) * 3600
        m = pick({"rail": 0.3, "walk": 0.3, "taxi / other": 0.4})
        q = portal_for(m, door)
        node, di = (q["node"], portal_idx[id(q)]) if q else (door, -1)
        if rng.random() < HG["onSiteFirstStop"]:
            f = softmin([x for x in places if x["kind"] in ("culture", "food")], lambda x: netdist(x["node"], door) / x["w"], 300)
            t = add_trip(p, day, t, door, f["node"], SPOT_HOME, SPOT_PLACE, "outing", 0, -1, place_idx[id(f)])
            t = add_trip(p, day, t + rng.uniform(40, 90) * 60, f["node"], node, SPOT_PLACE, SPOT_HIDDEN, "leave the site", 0, place_idx[id(f)], di)
        else:
            t = add_trip(p, day, t, door, node, SPOT_HOME, SPOT_HIDDEN, "head out", 0, -1, di)
        back = rng.uniform(16.5, 22.5) * 3600
        if back > t + 1800:
            t = add_trip(p, day, back, node, door, SPOT_HIDDEN, SPOT_HOME, "come home", 0, di, -1)
            if t < 19 * 3600 and rng.random() < HG["dinnerNearby"]:
                f = food_near(door, ("food", "bar"))
                t2 = add_trip(p, day, max(t + 1800, 18.5 * 3600), door, f["node"], SPOT_HOME, SPOT_PLACE, "outing", 0, -1, place_idx[id(f)])
                add_trip(p, day, t2 + meal_dw[day](), f["node"], door, SPOT_PLACE, SPOT_HOME, "back home", 0, place_idx[id(f)], -1)

# visitors: arrive through a portal, visit a place (or two), leave
VA = AS["visitorArrival"]


def visitor(day, place, t_arrive, dwell, flags=0, chain=None):
    m = pick(VA)
    m = {"subway": "rail", "parking": "drive", "walk": "walk", "bus": "bus"}[m]
    p = new_person("visitor", mode=MODES.index(m))
    line = pick_line() if m == "rail" else None
    q = portal_for(m if m != "drive" else "drive", place["node"], line=line)
    if q is None:
        q = softmin(by_kind["parking"], lambda x: netdist(x["node"], place["node"]), 120)
    di = portal_idx[id(q)]
    pi = place_idx[id(place)]
    t = add_trip(p, day, t_arrive, q["node"], place["node"], SPOT_HIDDEN, SPOT_PLACE, "visit", flags, di, pi)
    t += dwell
    last = place
    if chain:
        t = add_trip(p, day, t, place["node"], chain["node"], SPOT_PLACE, SPOT_PLACE,
                     "ride Angels Flight" if chain["node"] == AF_UP else "visit", flags, pi, place_idx[id(chain)])
        t += rng.uniform(10, 40) * 60
        last = chain
    q2 = rail_for(last["node"], line) if line else softmin(by_kind[q["kind"]], lambda x: netdist(x["node"], last["node"]), 150)
    if t < DAY - 1800:
        add_trip(p, day, t, last["node"], q2["node"], SPOT_PLACE, SPOT_HIDDEN, "leave the site", flags,
                 place_idx[id(last)], portal_idx[id(q2)])


def per_day(v, day):
    """Visitors on a typical day: an annual count spread over 261 weekdays and 104 weekend days, a weekend day
    weekendFactor times a weekday (visitorWeekendFactor unless the destination says otherwise)."""
    if "annual" not in v:
        return v[day]
    wf = v.get("weekendFactor", AS["visitorWeekendFactor"])
    wd = v["annual"] / (261 + 104 * wf)
    return wd * (wf if day == "weekend" else 1.0)


for name, v in AS["visitors"].items():
    for day in ("weekday", "weekend"):
        lo, hi = v["window"]
        ts = meal_t[day] if v["profile"] == "meals" else (lambda lo=lo, hi=hi: rng.uniform(lo, hi) * 3600)
        target = DEST.get(name)
        if "annual" in v and target is None:
            print("skip visitors for", name, "(not found)")
            continue
        for _ in range(int(round(per_day(v, day)))):
            t = ts()
            while not lo * 3600 <= t < hi * 3600:
                t = ts()
            if target is None:  # evening dining: any restaurant or bar, by its weight (bars count double after 21:00)
                c = [q for q in places if q["kind"] in ("food", "bar")]
                w = np.array([q["w"] * (2 if q["kind"] == "bar" and t > 21 * 3600 else 1) for q in c])
                pl = c[rng.choice(len(c), p=w / w.sum())]
            else:
                pl = target
            chain = None
            if pl is gcm and AF_UP is not None and rng.random() < AS["angelsFlightShare"]:
                chain = places[-1] if places[-1]["node"] == AF_UP else None
                if moca and rng.random() < 0.5:
                    chain = moca
            visitor(day, pl, t, float(np.clip(rng.normal(*v["dwell"]), 10, 240)) * 60, 0, chain)

# event: Walt Disney Concert Hall evening concerts (user, 2026-10-09: decided by the calendar, no toggle). A typical
# day carries the expected audience: seats x occupancy x the share of that day type's evenings with a concert
# (eveningShare, counted on the LA Phil calendar). The hall is inside the site (whole point cloud): people walk
# between their garage / Metro entrance and the hall; were it outside, to the site edge nearest it (throughSite).
ev = AS["event"]
hx, hy = ll2loc(*ev["latlon"])
hall_inside = EXT.contains(Point(hx, hy))
hall = {"node": nearest_node(Point(hx, hy))}
north = [hall] if hall_inside else sorted(by_kind["edge"], key=lambda q: math.dist(XYZ[q["node"]][:2], (hx, hy)))[:3]
if hall_inside:
    places.append({"name": AS["event"]["name"].replace("Concert at ", ""), "kind": "culture", "node": hall["node"], "w": 0.0})
    anchor_names.append(places[-1]["name"]); place_idx[id(hall)] = len(anchor_names) - 1
# The Music Center's other houses (audit 2026-10-09): a typical day carries annual attendance / 365, at the same times.
venues = [(north, {d: ev["seats"] * ev["occupancy"] * AS["eveningShare"][d] * (1.0 if hall_inside else ev["throughSite"])
                   for d in ("weekday", "weekend")}, hall_inside)]
for name, v in AS["theatres"].items():
    f = next((p for p in places if re.search(v["match"], p["name"], re.I)), None)
    if f is None:
        print("theatre not found:", name)
        continue
    venues.append(([f], {d: v["annual"] / 365 for d in ("weekday", "weekend")}, True))
for day in ("weekday", "weekend"):
  for targets, n_day, inside in venues:
    for _ in range(int(round(n_day[day]))):
        m = "drive" if rng.random() < 0.6 else "rail"
        p = new_person("visitor", mode=MODES.index(m))
        e = targets[rng.integers(len(targets))]
        q = (softmin(by_kind["parking"], lambda x: netdist(x["node"], e["node"]), 150) if m == "drive"
             else rail_for(e["node"], pick_line()))
        t = rng.uniform(*ev["arrive"]) * 3600
        ea = place_idx[id(e)] if inside else portal_idx[id(e)]
        add_trip(p, day, t, q["node"], e["node"], SPOT_HIDDEN, SPOT_HIDDEN, "event", 0,
                 portal_idx[id(q)], ea, backwards=True)
        add_trip(p, day, rng.uniform(*ev["leave"]) * 3600, e["node"], q["node"], SPOT_HIDDEN, SPOT_HIDDEN,
                 "leave the site", 0, ea, portal_idx[id(q)])

for p in people:
    for d in p["trips"]:
        p["trips"][d].sort(key=lambda t: t[0])
print(f"people {len(people)}  paths {len(paths)}  trips weekday {sum(len(p['trips']['weekday']) for p in people)}"
      f"  weekend {sum(len(p['trips']['weekend']) for p in people)}")


# ---------------------------------------------------------------- checks: who is on site, hour by hour
def present(p, day, attendance):
    if p["type"] != 1 and p["type"] != 0:
        return True
    return p["rank"] < SECTOR_ATT[p["sector"]] * 256 or day == "weekend"


def default_spot(p):
    return SPOT_HOME if p["type"] in (0, 2) else SPOT_HIDDEN


def onsite_curve(day, attendance, event=False):
    """People on site (indoors, at a place, or walking) per 15-minute bin, by type."""
    out = np.zeros((4, 96))
    t = (np.arange(96) + 0.5) * 900
    for p in people:
        tr = [x for x in p["trips"][day] if (not x[6] & F_ATTEND or present(p, day, attendance)) and (not x[6] & F_EVENT or event)]
        for i, ti in enumerate(t):
            if state_at(tr, ti, default_spot(p)) != SPOT_HIDDEN:
                out[p["type"], i] += 1
    return out


att = AS["officeAttendance"]
checks = {}
for day in ("weekday", "weekend"):
    c = onsite_curve(day, att)
    checks[day] = {TYPES[k]: [int(x) for x in c[k]] for k in range(4)}
    tot = c.sum(0)
    print(f"{day}: on site at 03:00 {int(tot[12])}, 08:00 {int(tot[32])}, 12:30 {int(tot[50])}, 15:00 {int(tot[60])},"
          f" 19:00 {int(tot[76])}, 23:00 {int(tot[92])}  (peak {int(tot.max())} at {int(tot.argmax()) // 4:02d}:{int(tot.argmax()) % 4 * 15:02d})")

# ---------------------------------------------------------------- calibration: Metro rail stations (user, 2026-10-09)
# Weekday trips that leave the site by rail through a station's entrances (= its boardings from the site) and that
# arrive by rail (alightings), against Metro's FY2026 average weekday rail boardings per station (metroBoardings in
# assumptions.json). Each OSM entrance belongs to the nearest station (within 250 m). The model has no transfers and
# no trips that only pass through, so it should come out below Metro's counts; the ratio is a check, nothing is
# changed by it here.
MB = AS["metroBoardings"]
st_xy = {k: ll2loc(*v["latlon"]) for k, v in MB.items()}
rail_station = {}
for q in by_kind["rail"]:
    x, y = XYZ[q["node"]][:2]
    k, d = min(((k, math.dist((x, y), xy)) for k, xy in st_xy.items()), key=lambda kd: kd[1])
    rail_station[portal_idx[id(q)]] = k if d <= 250 else None
board, alight = Counter(), Counter()
for p in people:
    for t in p["trips"]["weekday"]:
        if t[6] & F_ATTEND and not present(p, "weekday", att):
            continue
        if t[9] in rail_station and rail_station[t[9]]:
            board[rail_station[t[9]]] += 1
        if t[8] in rail_station and rail_station[t[8]]:
            alight[rail_station[t[8]]] += 1
calibration = {k: {"model_boardings": board[k], "model_alightings": alight[k], "metro_boardings": MB[k]["boardings"],
                   "ratio": round(board[k] / MB[k]["boardings"], 2) if MB[k]["boardings"] else None,
                   "transfer_hub": MB[k].get("transfer", False)}
               for k in MB}
print("Metro calibration (weekday):")
for k, v in calibration.items():
    print(f"  {k:28s} model in/out {v['model_boardings']:6d} / {v['model_alightings']:6d}   Metro boardings {v['metro_boardings'] or '-':>6}"
          f"   ratio {v['ratio']}{'  (transfer hub)' if v['transfer_hub'] else ''}")
print("  entrances without a station within 250 m:", sum(1 for v in rail_station.values() if v is None))

# ---------------------------------------------------------------- keep the people the viewer draws (user, 2026-10-08)
# The viewer fades people with distance from Y-1 like the point cloud (site-model/houdini/thinning.json): within R0
# everyone is drawn, farther out a share (R0 / d_eff)^P. Only those people are written, each with a weight = 1 / share,
# so the counts and the chart still add up to everyone (the checks above use everyone). The distance is the person's
# own anchor: work place for workers, home for residents and hotel guests, the first stop for visitors.
TH = json.loads((HERE.parent / "houdini" / "thinning.json").read_text())
R0, PW, KMIN, EDGE, EDGE_W, JIT = (TH["full_density_radius_m"], TH["falloff_power"], TH["keep_min"], TH["edge_end_m"],
                                   TH.get("edge_width_m", 300), TH.get("object_jitter", 0.18))
all_people = len(people)


def anchor_xy(p):
    s = p["work_spot"] if p["type"] == 1 else p["home_spot"]
    if s:
        return s[0], s[1]
    for day in ("weekday", "weekend"):
        if p["trips"][day]:
            return tuple(XYZ[p["trips"][day][0][3]][:2])
    return 0.0, 0.0


def share(x, y, u):
    d = math.hypot(x, y)
    if d <= R0:
        return 1.0
    r = min(1.0, (R0 / max(d * (1 + JIT * (2 * u - 1)), 1)) ** PW)
    return 0.0 if r < KMIN else r * min(max((EDGE - d) / EDGE_W, 0), 1)


kept = []
for p in people:
    sh = share(*anchor_xy(p), rng.random())
    if sh > 0 and rng.random() < sh:
        p["weight"] = 1.0 / sh
        kept.append(p)
# people with no share (beyond the cloud's edge, or below keep_min) are drawn by nobody: rescale each type's weights
# so the counts still add up to everyone of that type
for t in range(len(TYPES)):
    tot = sum(1 for p in people if p["type"] == t)
    kw = sum(p["weight"] for p in kept if p["type"] == t)
    for p in kept:
        if p["type"] == t and kw > 0:
            p["weight"] *= tot / kw
people = kept
print(f"drawn: {len(people):,} of {all_people:,} people (weights add up to {sum(p['weight'] for p in people):,.0f})")
# only the paths their trips use
used = sorted({path_between(t[2], t[3])[0] for p in people for d in ("weekday", "weekend") for t in p["trips"][d]})
pmap = {k: i for i, k in enumerate(used)}
paths = [paths[k] for k in used]
_pb = path_between
path_between = lambda a, b: (lambda r: (pmap[r[0]], r[1]))(_pb(a, b))

# ---------------------------------------------------------------- write web/data/population.{json,bin}
sections, blob = {}, bytearray()


def put(name, arr):
    global blob
    arr = np.ascontiguousarray(arr)
    while len(blob) % 8:
        blob += b"\0"
    sections[name] = {"offset": len(blob), "count": int(arr.size), "type": arr.dtype.name}
    blob += arr.tobytes()


three = lambda x, y, z: (x, z, -y)  # scene-local -> three.js
put("nodes", np.array([three(*p) for p in XYZ], np.float32).ravel())
off = np.cumsum([0] + [len(s) for s in paths]).astype(np.uint32)
put("pathOffsets", off)
put("pathNodes", np.array([n for s in paths for n in s], np.uint16 if N < 65536 else np.uint32))
A = len(people)
put("type", np.array([p["type"] for p in people], np.uint8))
put("mode", np.array([p["mode"] for p in people], np.uint8))
put("sector", np.array([p["sector"] for p in people], np.uint8))
put("rank", np.array([p["rank"] for p in people], np.uint8))
put("weight", np.array([p["weight"] for p in people], np.float32))
bidx = {b: k for k, b in enumerate(BIDS)}
put("homeBld", np.array([bidx[p["home_bid"]] if p["home_bid"] else -1 for p in people], np.int16))
put("workBld", np.array([bidx[p["work_bid"]] if p["work_bid"] else -1 for p in people], np.int16))
dm = lambda s: three(*s) if s else (0, -1000, 0)
put("homeSpot", np.round(np.array([dm(p["home_spot"]) for p in people]) * 10).astype(np.int16).ravel())
put("workSpot", np.round(np.array([dm(p["work_spot"]) for p in people]) * 10).astype(np.int16).ravel())
put("distKm", np.array([min(p["dist_km"], 650) * 100 for p in people]).astype(np.uint16))
put("bearing", np.array([p["bearing"] / 360 * 255 for p in people]).astype(np.uint8))
tracts = sorted({p["tract"] for p in people})
tix = {t: k for k, t in enumerate(tracts)}
put("tract", np.array([tix[p["tract"]] for p in people], np.uint16))
for day in ("weekday", "weekend"):
    tr = [t for p in people for t in p["trips"][day]]
    put(f"{day}.offsets", np.cumsum([0] + [len(p["trips"][day]) for p in people]).astype(np.uint32))
    put(f"{day}.t0", np.array([round(t[0] / 2) for t in tr], np.uint16))
    put(f"{day}.t1", np.array([max(round(t[1] / 2), round(t[0] / 2) + 1) for t in tr], np.uint16))
    pid = [path_between(t[2], t[3]) for t in tr]
    put(f"{day}.path", np.array([i for i, _ in pid], np.uint32))
    put(f"{day}.flags", np.array([t[4] | t[5] << 2 | (16 if r else 0) | (t[6] << 5) for t, (_, r) in zip(tr, pid)], np.uint8))
    put(f"{day}.purpose", np.array([t[7] for t in tr], np.uint8))
    put(f"{day}.orig", np.array([t[8] for t in tr], np.int16))
    put(f"{day}.dest", np.array([t[9] for t in tr], np.int16))
(WEB / "population.bin").write_bytes(bytes(blob))

office_b = [b for b in BIDS if B[b]["use"] == "office"]
office_m2 = sum(B[b]["area_m2"] for b in office_b)
office_jobs = sum(B[b]["jobs"] for b in office_b)
print(f"office: {office_jobs} jobs in {office_m2:,.0f} m2; at {AS['officeVacancy']:.1%} vacancy "
      f"{office_m2 * (1 - AS['officeVacancy']) / max(office_jobs, 1):.1f} m2 of occupied office space per job")
assumptions = json.loads((POP / "assumptions.json").read_text())
meta = {
    "_comment": "Generated by site-model/population/prep_population.py. A modeled typical day, not observed data.",
    "generated_by": "site-model/population/prep_population.py (after Clark Amenudo's population layer, PR #9 of the archived Blender project)",
    "bin": "population.bin", "sections": sections, "count": A,
    "time_unit_s": 2, "spot_unit_m": 0.1,
    "flags": {"from": "bits 0-1", "to": "bits 2-3 (0 off site, 1 home, 2 work, 3 place)", "reverse": 16,
              "attendance": 32, "event": 64},
    "types": TYPES, "modes": MODES, "sectors": SECTORS, "sectorLabels": SECTOR_LABELS,
    "remoteEligible": sorted(OFFICE), "sectorAttendance": [round(x, 4) for x in SECTOR_ATT],
    "officeAttendance": AS["officeAttendance"], "purposes": PURPOSES,
    "anchors": anchor_names, "tracts": tracts,
    "buildings": [{"id": b, "name": B[b]["name"], "use": B[b]["use"], "addr": B[b]["addr"], "area_m2": round(B[b]["area_m2"]),
                   "area_src": B[b]["area_src"], "units": B[b]["units"], "jobs": B[b]["jobs"],
                   "residents": B[b]["residents"], "rooms": B[b]["rooms"], "guests": B[b]["guests"],
                   "base": round(min(bb for _, bb, _ in prisms[b]), 1), "fh": B[b]["fh"]} for b in BIDS],
    "event": AS["event"]["name"],
    "calibration": {"metro": calibration, "note": "model weekday rail trips leaving / entering the site through each station's entrances, against Metro FY2026 average weekday boardings (assumptions: metroBoardings)"},
    # the Y-1 parcel (LA County Assessor, APN 5149-010-951), scene-local [x east, y north], for the "on Y-1" count
    "y1": [[[round(x, 2), round(y, 2)] for x, y in local(shape(f["geometry"])).exterior.coords]
           for f in load("parcels.geojson")["features"] if "5149-010-951" in (f["properties"].get("APNs") or [f["properties"].get("APN")])],
    "totals": {"people": all_people, "drawn": A,
               "by_type": {t: round(sum(p["weight"] for p in people if TYPES[p["type"]] == t)) for t in TYPES},
               "jobs_placed": sum(B[b]["jobs"] for b in BIDS), "jobs_dropped": sum(v for k, v in dropped.items() if not k.startswith("residents")),
               "lodes_jobs_in_blocks": sum(v["C000"] for v in lodes["wac"].values()),
               "residents_2020": sum(len(v) for v in res_by_block.values()),
               "residents_census_count_on_site": res_census, "residents_census_noise_dropped": res_noise,
               "residents_by_rule": dict(Counter(v["rule"] for v in res_log.values() for _ in range(v["residents"]))),
               "office_m2_per_job_occupied": round(office_m2 * (1 - AS["officeVacancy"]) / max(office_jobs, 1), 1)},
    "checks": {"note": f"People on site per 15 min at {att:.0%} office attendance, Disney Hall audience by eveningShare (computed by the script)", **checks},
    "sources": {
        "jobs": lodes["source"], "residents": load("blocks.geojson")["source"],
        "buildings": load("parcels.geojson")["source"] + " floor area and use; building entities and their LiDAR "
                     "prisms from " + hand["source"],
        "commute": load("ctpp.json")["source"] + " (workers' mode and arrival time); residents: " + acs["source"],
        "trip_times": nhts["source"], "network": osm["source"],
    },
    "assumptions": {k: {"value": v["value"], "note": v["note"]} for k, v in assumptions.items() if isinstance(v, dict) and "value" in v},
}
(WEB / "population.json").write_text(json.dumps(meta, separators=(",", ":")))
print(f"wrote population.bin {len(blob) / 1e6:.1f} MB, population.json {(WEB / 'population.json').stat().st_size / 1e3:.0f} KB")
