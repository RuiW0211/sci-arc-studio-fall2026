"""The population model's walking network and ground, rebuilt for the Free view's questions.

build(): the same steps as site-model/population/prep_population.py's "walking network" stage, line for line (OSM
ways a pedestrian may use, bridges and Angels Flight at a straight grade, gaps of up to snapM joined, Tobler's slope at
slopeWeight strength, the largest connected part), keeping what the model drops: each node's OSM id and each edge's
OSM way (which ways are steps, lifts, escalators). With no arguments it gives the model's own nodes (2026-10-18: the
same 14,539, within float rounding, as population_full.npz). open_ways: OSM ways walked although OSM marks them
private (Angels Knoll's paths behind the fence: "if it opened", q_passing.py); link_ends: their loose ends joined to
the street. ground_fn(): the model's ground height.
"""
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

POP = Path(__file__).resolve().parent.parent / "population"
HANDOFF = Path(__file__).resolve().parent.parent / "houdini" / "handoff"
WALK = {"footway": 1.0, "pedestrian": 1.0, "steps": 1.05, "path": 1.0, "corridor": 1.0, "living_street": 1.0,
        "cycleway": 1.1, "service": 1.25, "residential": 1.3, "unclassified": 1.3, "tertiary": 1.4,
        "secondary": 1.6, "primary": 1.6, "secondary_link": 2.0, "primary_link": 2.0, "tertiary_link": 2.0,
        "elevator": 1.0}


def ground_fn():
    """The ground height (m, NAVD88) at scene-local (x east, y north), as the model reads it (terrain.npy, bilinear)."""
    hand = json.loads((HANDOFF / "buildings.json").read_text(encoding="utf-8"))
    TER, tg = np.load(HANDOFF / "terrain.npy"), hand["terrain"]

    def ground(x, y):
        c = min(max((x - tg["x0"]) / tg["step"], 0), tg["cols"] - 1.001)
        r = min(max((tg["y0"] - y) / tg["step"], 0), tg["rows"] - 1.001)
        c0, r0 = int(c), int(r)
        fc, fr = c - c0, r - r0
        t = TER[r0:r0 + 2, c0:c0 + 2]
        return float((t[0, 0] * (1 - fc) + t[0, 1] * fc) * (1 - fr) + (t[1, 0] * (1 - fc) + t[1, 1] * fc) * fr)
    return ground


def build(open_ways=(), link_ends=(), link_max_m=10.0):
    """-> dict: XYZ (N x 3, east / north / up), G (csr, route costs), osm (N, OSM node id or -1), E (edge list
    (a, b, length, cost, way)), funicular (node indices), links (what link_ends joined).
    link_ends: OSM node ids of open ways' loose ends (OSM drew Angels Knoll's Hill Street path joined to nothing),
    each joined, as a footway, to the nearest node of another way within link_max_m and 2 m of its height."""
    AS = {k: v["value"] for k, v in json.loads((POP / "data" / "assumptions.json").read_text(encoding="utf-8")).items()
          if isinstance(v, dict) and "value" in v}
    hand = json.loads((HANDOFF / "buildings.json").read_text(encoding="utf-8"))
    OX, OY = hand["origin_utm"]
    HALF = hand["extent_m"][1]
    ground = ground_fn()
    to_utm = Transformer.from_crs(4326, 26911, always_xy=True)

    def ll2loc(lat, lon):
        x, y = to_utm.transform(lon, lat)
        return x - OX, y - OY

    osm = json.loads((POP / "data" / "osm.json").read_text(encoding="utf-8"))
    opened = set(open_ways)
    nid, NXY, NOSM, edges, cut, funicular_nodes = {}, [], [], {}, set(), []

    def node(osm_id, x, y):
        if osm_id not in nid:
            nid[osm_id] = len(NXY)
            NXY.append([x, y, None]); NOSM.append(osm_id)
        return nid[osm_id]

    for e in osm["elements"]:
        if e["type"] != "way" or "geometry" not in e:
            continue
        t = e.get("tags", {})
        hw = t.get("highway")
        fun = t.get("railway") == "funicular"
        open_foot = t.get("foot") in ("yes", "designated", "permissive") or e["id"] in opened
        if not fun and (hw not in WALK or (t.get("access") in ("no", "private") and not open_foot) or t.get("foot") == "no"):
            continue
        if t.get("tunnel") in ("yes", "building_passage") and hw not in ("footway", "pedestrian", "corridor"):
            continue
        factor = 0.6 if fun else WALK[hw]
        graded = not fun and hw not in ("steps", "elevator") and t.get("tunnel") is None and not t.get("conveying")
        pts = [ll2loc(g["lat"], g["lon"]) for g in e["geometry"]]
        inside = [abs(x) <= HALF and abs(y) <= HALF for x, y in pts]
        ids = [node(n, x, y) if ins else None for n, (x, y), ins in zip(e["nodes"], pts, inside)]
        elevated = fun or t.get("bridge") in ("yes", "viaduct") or (t.get("layer", "0").lstrip("-").isdigit() and int(t.get("layer", "0")) >= 1)
        if elevated:
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
                    edges[key] = (L, L * factor, graded, e["id"])
    for p in NXY:
        if p[2] is None:
            p[2] = ground(p[0], p[1])

    deg = Counter()
    for i, j in edges:
        deg[i] += 1; deg[j] += 1
    P2 = np.array([p[:2] for p in NXY]); kd = cKDTree(P2)
    for i in [n for n, d in deg.items() if d == 1]:
        for j in kd.query_ball_point(P2[i], AS["network"]["snapM"]):
            if j != i and (min(i, j), max(i, j)) not in edges and abs(NXY[i][2] - NXY[j][2]) < 2.0:
                L = max(math.dist(P2[i], P2[j]), 0.1)
                edges[(min(i, j), max(i, j))] = (L, L, False, -1)
                break

    links = []
    for osm_id in link_ends:
        i = nid.get(osm_id)
        if i is None:
            continue
        own = {j for key in edges for j in key if i in key}   # its own way's neighbours
        for j in sorted(kd.query_ball_point(P2[i], link_max_m), key=lambda j: math.dist(P2[i], P2[j])):
            if j != i and j not in own and (min(i, j), max(i, j)) not in edges and abs(NXY[i][2] - NXY[j][2]) < 2.0:
                L = max(math.dist(P2[i], P2[j]), 0.1)
                edges[(min(i, j), max(i, j))] = (L, L, False, -2)
                links.append({"from_osm": osm_id, "to_osm": NOSM[j], "m": round(L, 1), "dz": round(NXY[j][2] - NXY[i][2], 1)})
                break

    SL = AS["network"]["slopeWeight"]
    tob = lambda g: math.exp(-3.5 * (abs(g + 0.05) - 0.05))
    for key, (L, c, graded, way) in list(edges.items()):
        if graded and L > 1:
            g = abs(NXY[key[1]][2] - NXY[key[0]][2]) / L
            m = 0.5 * (1 / tob(g) + 1 / tob(-g))
            edges[key] = (L, c * (1 + SL * (m - 1)), graded, way)

    n0 = len(NXY)
    ei = np.array(list(edges), dtype=np.int64)
    ew = np.array([v[1] for v in edges.values()])
    G = csr_matrix((np.r_[ew, ew], (np.r_[ei[:, 0], ei[:, 1]], np.r_[ei[:, 1], ei[:, 0]])), shape=(n0, n0))
    ncomp, lab = connected_components(G, directed=False)
    keep = np.flatnonzero(lab == np.bincount(lab).argmax())
    remap = -np.ones(n0, dtype=np.int64)
    remap[keep] = np.arange(len(keep))
    XYZ = np.array([NXY[i] for i in keep])
    N = len(XYZ)
    E = [(int(remap[i]), int(remap[j]), L, c, way) for (i, j), (L, c, _, way) in edges.items() if remap[i] >= 0 and remap[j] >= 0]
    ea = np.array([[a, b] for a, b, *_ in E])
    ec = np.array([c for _, _, _, c, _ in E])
    G = csr_matrix((np.r_[ec, ec], (np.r_[ea[:, 0], ea[:, 1]], np.r_[ea[:, 1], ea[:, 0]])), shape=(N, N))
    return {"XYZ": XYZ, "G": G, "osm": np.array([NOSM[i] for i in keep], np.int64), "E": E,
            "funicular": sorted({int(remap[i]) for i in funicular_nodes if remap[i] >= 0}), "links": links}
