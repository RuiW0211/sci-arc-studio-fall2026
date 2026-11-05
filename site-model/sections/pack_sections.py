"""Site sections (Rui, 2026-11-05): four sections and a north-up top view of Parcel Y-1, for web/sections/.

Reads only files in this repository:
  web/data/lidar_points.laz                    the 2023 USGS 3DEP point cloud (local frame: x east, y north, z NAVD88)
  site-model/population/data/parcels.geojson   LA County Assessor parcels (EPSG:26911); Y-1 = APN 5149-010-951 + -952
  site-model/population/data/osm.json          OpenStreetMap streets and Angels Flight (ODbL)
Writes:
  web/data/sections.json     the cuts (plane, look direction, frame), the labels under each cut, ground elevations at the
                             parcel edges and street centrelines, the California Plaza levels the cut passes through,
                             Olive Street under the California Plaza deck (estimate), and the top view's overlay
  web/data/sections_top.png  the top view: highest LiDAR point per 0.25 m cell, hillshaded, north up (grey + alpha)

The page (web/js/sections.js) draws the sections live from lidar_points.laz with the same planes.

Frame of the cuts: s runs across the site from Olive (NW) to Hill (SE), bearing 128.4 deg, perpendicular to Hill Street;
a runs along Hill Street from NE to SW, bearing 218.4 deg; the origin is the centroid of Y-1.
  A  a = 0      looking NE   (through the middle of Y-1, across the slope)
  B  a = -50.2  looking SW   (along Angels Flight)
  C  s = 0      looking NW   (through the middle of Y-1, along Hill Street)
  D  s = -63.6  looking SE   (along Olive Street, through the California Plaza deck)
Olive Street is covered by the California Plaza deck from a = +12 to a = -78 (OSM: tunnel=building_passage); there the
LiDAR has no street points, so its grade is interpolated between the open stretches either side (102.4 m at a = +12,
109.0 m at a = -78; checked 2026-11-05) and drawn dashed as an estimate.

  python site-model/sections/pack_sections.py
"""
import json
import math
from pathlib import Path

import laspy
import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import gaussian_filter, median_filter
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
LAZ = ROOT / "web" / "data" / "lidar_points.laz"
PARCELS = ROOT / "site-model" / "population" / "data" / "parcels.geojson"
OSM = ROOT / "site-model" / "population" / "data" / "osm.json"
OUT_JSON = ROOT / "web" / "data" / "sections.json"
OUT_TOP = ROOT / "web" / "data" / "sections_top.png"

ORIGIN = np.array([384580.0, 3768520.0])                       # the site origin (E, N), EPSG:26911
Y1_APNS = ("5149-010-951", "5149-010-952")
BEARING_S = 128.4                                               # perpendicular to Hill Street (38.4 deg)
U = np.array([math.sin(math.radians(BEARING_S)), math.cos(math.radians(BEARING_S))])   # s: NW -> SE
V = np.array([U[1], -U[0]])                                                            # a: NE -> SW
FT = 0.3048
H_RANGE, Z_RANGE, DEPTH, SLAB = (-110.0, 110.0), (75.0, 175.0), 100.0, 0.5
NO_CUT = (3, 5, 7, 8)          # segments never drawn as cut (Rui, 2026-11-05): tree, podium tree, shrub, vehicle
TOP_HALF, TOP_CELL = 150.0, 0.25
OLIVE_COVERED = (12.0, -78.0)                                   # a range of the covered stretch
OLIVE_GRADE = ((12.0, 102.4), (-78.0, 109.0))                   # (a, z) at its two open ends
PLAZA_BANDS = ((113.0, 114.0, "lower"), (117.5, 118.6, "upper"))   # California Plaza levels (DEM check, 2026-11-05)


def olive_grade(a):
    (a0, z0), (a1, z1) = OLIVE_GRADE
    return z0 + (a - a0) * (z1 - z0) / (a1 - a0)


def main():
    # ---- Y-1 and its centroid (local frame) ----
    feats = json.loads(PARCELS.read_text())["features"]
    y1 = unary_union([shape(f["geometry"]) for f in feats if f["properties"].get("APN") in Y1_APNS])
    y1 = max(y1.geoms, key=lambda g: g.area) if y1.geom_type == "MultiPolygon" else y1
    c0 = np.array(y1.centroid.coords[0]) - ORIGIN
    ring = [tuple(np.array(p) - ORIGIN) for p in y1.exterior.coords]
    sa = lambda p: (float(np.dot(np.array(p) - c0, U)), float(np.dot(np.array(p) - c0, V)))
    ring_sa = [sa(p) for p in ring]
    print(f"Y-1 {y1.area:.0f} m2, centroid local ({c0[0]:.1f}, {c0[1]:.1f})")

    # ---- streets (OSM) in (s, a) ----
    osm = json.loads(OSM.read_text())
    els = osm["elements"]
    nodes = {e["id"]: e for e in els if e.get("type") == "node"}
    to_utm = Transformer.from_crs(4326, 26911, always_xy=True)
    ways = {}
    for e in els:
        t = e.get("tags", {})
        if e.get("type") != "way":
            continue
        road = t.get("highway") in ("primary", "secondary", "tertiary", "residential", "unclassified")
        if not (road or t.get("railway") == "funicular"):
            continue
        ll = ([(p["lon"], p["lat"]) for p in e["geometry"]] if "geometry" in e
              else [(nodes[n]["lon"], nodes[n]["lat"]) for n in e.get("nodes", []) if n in nodes])
        if len(ll) >= 2:
            name = "Angels Flight" if t.get("railway") == "funicular" else t.get("name", "")
            ways.setdefault(name, []).append([sa(np.array(to_utm.transform(*p)) - ORIGIN) for p in ll])
    short = {"South Olive Street": "S Olive St", "South Hill Street": "S Hill St", "West 4th Street": "W 4th St",
             "West 3rd Street": "W 3rd St", "Angels Flight": "Angels Flight"}

    # ---- the point cloud ----
    las = laspy.read(str(LAZ))
    X, Y, Z = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)
    SEG = np.asarray(las["segment"])
    S = (X - c0[0]) * U[0] + (Y - c0[1]) * U[1]
    A = (X - c0[0]) * V[0] + (Y - c0[1]) * V[1]
    win = (np.abs(S) < 260) & (np.abs(A) < 260)
    X, Y, Z, SEG, S, A = X[win], Y[win], Z[win], SEG[win], S[win], A[win]
    print(f"{win.sum():,} points within 260 m of Y-1")

    cuts = {
        "A": dict(fixed=("a", 0.0), look=-V, right=U, look_name="northeast",
                  sub="through the middle of Parcel Y-1, across the slope"),
        "B": dict(fixed=("a", -50.2), look=V, right=-U, look_name="southwest",
                  sub="along Angels Flight, across the slope"),
        "C": dict(fixed=("s", 0.0), look=-U, right=-V, look_name="northwest",
                  sub="through the middle of Parcel Y-1, along Hill Street"),
        "D": dict(fixed=("s", -63.6), look=U, right=V, look_name="southeast",
                  sub="along Olive Street, through the California Plaza deck"),
    }
    out = {"source": ("USGS 3DEP CA_LosAngeles_B23 LiDAR (2023, web/data/lidar_points.laz); LA County Assessor parcels; "
                      "OpenStreetMap (ODbL). Written by site-model/sections/pack_sections.py."),
           "frame": "local: x east, y north from the site origin E 384580 / N 3768520 (EPSG:26911), metres, NAVD88",
           "range": {"h": H_RANGE, "z": Z_RANGE, "depth": DEPTH, "slab": SLAB}, "noCut": list(NO_CUT),
           "c0": [round(float(c0[0]), 3), round(float(c0[1]), 3)],
           "parcel": [[round(x, 2), round(y, 2)] for x, y in ring], "sections": {}}

    for k, c in cuts.items():
        fk, fv = c["fixed"]
        p0 = c0 + (fv * V if fk == "a" else fv * U)
        w, r = c["look"], c["right"]
        h = (X - p0[0]) * r[0] + (Y - p0[1]) * r[1]
        d = (X - p0[0]) * w[0] + (Y - p0[1]) * w[1]
        along = (lambda s_, a_: a_) if fk == "s" else (lambda s_, a_: s_)   # the coordinate that runs along the cut
        to_h = lambda s_, a_: float(np.dot((c0 + s_ * U + a_ * V) - p0, r))
        cut = (np.abs(d) <= SLAB) & (h >= H_RANGE[0]) & (h < H_RANGE[1]) & (Z >= Z_RANGE[0]) & (Z < Z_RANGE[1]) & ~np.isin(SEG, NO_CUT)
        ground = cut & (SEG == 0)

        def ground_at(hh):
            q = ground & (np.abs(h - hh) < 1.0)
            return float(np.median(Z[q])) if q.sum() >= 3 else None

        # the cut line in (s, a)
        line = (LineString([(-300, fv), (300, fv)]) if fk == "a" else LineString([(fv, -300), (fv, 300)]))
        # streets crossing the cut (one label per street, at the mean of its crossings)
        xs = {}
        for nm, segs in ways.items():
            if nm not in short:
                continue
            for sg in segs:
                g = LineString(sg).intersection(line)
                for p in ([g] if g.geom_type == "Point" else list(getattr(g, "geoms", []))):
                    if p.is_empty:
                        continue
                    hh = to_h(p.x, p.y)
                    if H_RANGE[0] + 4 < hh < H_RANGE[1] - 4:
                        xs.setdefault(nm, []).append(hh)
        streets = []
        for nm, hs in xs.items():
            if k == "B" and nm == "Angels Flight":
                streets.append({"name": "Angels Flight (along the cut)", "h": 0.0})
            elif k == "D" and nm == "South Olive Street":
                continue
            else:
                streets.append({"name": short[nm], "h": round(float(np.mean(hs)), 1)})
        if k == "D":
            streets.append({"name": "S Olive St (along the cut)", "h": round(to_h(fv, -30.0), 1)})
        streets.sort(key=lambda x: x["h"])

        # Y-1 along the cut: crossed, or behind it
        pc = Polygon(ring_sa).intersection(line)
        if not pc.is_empty:
            hs = [to_h(*q) for q in (pc.coords if pc.geom_type == "LineString" else [q for g in pc.geoms for q in g.coords])]
            parcel = {"h": [round(min(hs), 1), round(max(hs), 1)], "behind": False}
        else:
            hs = [to_h(*q) for q in ring_sa]
            parcel = {"h": [round(min(hs), 1), round(max(hs), 1)], "behind": True}

        # ground elevations: the parcel edges (when cut) and the street centrelines
        tags = []
        if not parcel["behind"]:
            tags += [parcel["h"][0] + 1.5, parcel["h"][1] - 1.5]
        tags += [s_["h"] for s_ in streets if s_["name"] in ("S Hill St", "W 4th St", "W 3rd St")]
        tag_out = []
        for hh in sorted(set(round(t, 1) for t in tags)):
            zz = ground_at(hh)
            if zz is not None:
                tag_out.append({"h": round(hh, 1), "z": round(zz, 2)})

        # California Plaza levels the cut passes through (the longest run of cut points in each band)
        levels = []
        for z0, z1, name in PLAZA_BANDS:
            q = cut & (Z >= z0) & (Z < z1)
            q &= (h > 40) if k == "B" else ((np.abs(h + 30) < 50) if k == "D" else (h < 0))
            if q.sum() < 25:
                continue
            hq = np.sort(h[q])
            run = max(np.split(hq, np.where(np.diff(hq) > 3)[0] + 1), key=len)
            sel = q & (h >= run[0]) & (h <= run[-1])
            levels.append({"h": round(float(np.median(run)), 1), "z": round(float(np.median(Z[sel])), 2),
                           "label": f"California Plaza, {name} level"})

        # Olive Street under the deck (estimate)
        est = []
        if fk == "a" and OLIVE_COVERED[1] <= fv <= OLIVE_COVERED[0]:
            olive = [s_["h"] for s_ in streets if s_["name"] == "S Olive St"]
            if olive:
                zz = olive_grade(fv)
                est.append({"pts": [[olive[0] - 14, round(zz, 2)], [olive[0] + 14, round(zz, 2)]],
                            "label": "S Olive St under the deck (estimate)"})
        if k == "D":
            aa = np.linspace(OLIVE_COVERED[1], OLIVE_COVERED[0], 10)
            est.append({"pts": [[round(to_h(fv, a_), 2), round(olive_grade(a_), 2)] for a_ in aa],
                        "label": "S Olive St under the deck (estimate)"})

        out["sections"][k] = {
            "title": f"Section {k}", "look": c["look_name"], "sub": c["sub"],
            "p0": [round(float(p0[0]), 3), round(float(p0[1]), 3)],
            "w": [round(float(w[0]), 6), round(float(w[1]), 6)], "right": [round(float(r[0]), 6), round(float(r[1]), 6)],
            "parcel": parcel, "streets": streets, "tags": tag_out, "levels": levels, "estimates": est,
        }
        print(k, "cut points", int(cut.sum()), "| streets", [(s_["name"], s_["h"]) for s_ in streets],
              "| tags", [round(t["z"] / FT) for t in tag_out], "| levels", [(l["label"][17:], round(l["z"] / FT)) for l in levels])

    # ---- top view: highest point per cell, hillshaded, north up ----
    n = int(2 * TOP_HALF / TOP_CELL)
    e0, n0 = c0[0] - TOP_HALF, c0[1] - TOP_HALF
    ix = ((X - e0) / TOP_CELL).astype(int)
    iy = ((n0 + 2 * TOP_HALF - Y) / TOP_CELL).astype(int)          # row 0 = north
    ok = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    zt = np.full(n * n, -np.inf)
    np.maximum.at(zt, iy[ok] * n + ix[ok], Z[ok])
    zt = zt.reshape(n, n)
    for _ in range(2):                                              # close one-cell gaps
        pad = np.pad(zt, 1, constant_values=-np.inf)
        nb = np.max([pad[1 + dy:n + 1 + dy, 1 + dx:n + 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)
        zt = np.where(np.isfinite(zt), zt, nb)
    hole = ~np.isfinite(zt)
    zt = np.where(hole, np.min(zt[~hole]), zt)
    zt = gaussian_filter(median_filter(zt, size=3), 0.8)
    gy, gx = np.gradient(zt, TOP_CELL)
    gy = -gy                                                         # rows run south
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, -gy)
    az, alt = math.radians(315), math.radians(45)                    # light from the north-west
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    rel = np.clip((zt - 85) / 60, 0, 1)
    g = np.clip(250 - (1 - np.clip(shade, 0, 1)) * 120 - rel * 35, 0, 255).astype(np.uint8)
    alpha = np.where(hole, 0, 255).astype(np.uint8)
    Image.fromarray(np.dstack([g, alpha]), "LA").save(OUT_TOP, optimize=True)
    out["top"] = {"image": "sections_top.png", "bounds": [round(e0, 2), round(n0, 2), round(e0 + 2 * TOP_HALF, 2), round(n0 + 2 * TOP_HALF, 2)],
                  "cell": TOP_CELL, "note": "highest LiDAR point per cell, hillshaded (light from the north-west)",
                  "labels": [], "lines": {}}
    for nm, (s_, a_) in {"S Olive St": (-66, 92), "S Hill St": (64, 92), "W 4th St": (-20, 66),
                        "Angels Flight": (8, -70), "W 3rd St": (-20, -140)}.items():
        p = c0 + s_ * U + a_ * V
        out["top"]["labels"].append({"name": nm, "x": round(float(p[0]), 2), "y": round(float(p[1]), 2)})
    for k, c in cuts.items():
        sec = out["sections"][k]
        p0, r = np.array(sec["p0"]), np.array(sec["right"])
        a_, b_ = p0 + H_RANGE[0] * r, p0 + H_RANGE[1] * r
        out["top"]["lines"][k] = [[round(float(a_[0]), 2), round(float(a_[1]), 2)], [round(float(b_[0]), 2), round(float(b_[1]), 2)]]
    OUT_JSON.write_text(json.dumps(out, indent=1))
    print("wrote", OUT_JSON.relative_to(ROOT), f"({OUT_JSON.stat().st_size / 1e3:.0f} kB),",
          OUT_TOP.relative_to(ROOT), f"({OUT_TOP.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
