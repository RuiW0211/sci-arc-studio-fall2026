"""Ghost towers for the viewer: the Angels Landing schemes on Y-1, traced from the City's own documents (user,
2026-10-13: "put the research into the viewer: ghost towers").

  python site-model/ghosts/build_angels_landing.py "<D_II.pdf>" "<AngelsLanding_InitialStudy.pdf>"   -> web/data/ghosts.json

Two schemes:

  2021  Angels Landing Draft EIR, chapter II (Project Description), City of Los Angeles, January 2021; approved
        February 3, 2022. D_II.pdf, 30 MB, kept outside the repository. Its plans are vector:
          * floor plates: Figure II-14, Level 6 (Lower California Plaza), page II-23. Tower A's hotel floor is the green
            fill, Tower B's fitness / spa floor the orange fill; each outline is the convex hull of its fill.
          * scale: the plan's dimensions, 314'-0" along Hill Street (351 pt) and 313'-11" along 4th Street (350 pt).
          * heights: Figure II-4, "854'-0" T.O. parapet, 63 floors" (A) and "494'-0" T.O. parapet, 42 floors" (B);
            level elevations on the plans are feet above sea level (Level PB1, Hill Street Plaza, 287'-0", Fig. II-8;
            Level 6 376'-0", Fig. II-14).
  2019  Angels Landing Initial Study (with the Notice of Preparation), City of Los Angeles, March 2019; its figures are
        Handel Architects' drawings of 2018. AngelsLanding_InitialStudy.pdf (Y1-site-model/references). Its plans are
        rasters:
          * floor plates: Figure 10 (Lower California Plaza), PDF page 28. The towers' floors are the green fill, found
            by colour: Tower A the outer contour of its fill (its core is inside), Tower B the convex hull of its fill
            (its core is a notch on the east side).
          * scale: the property line drawn in the figure (IS_FRAME, read off the raster), taken as 314'-0" by 313'-11"
            as in 2021 (same site, 97,631 sq ft in both).
          * heights: Figures 3 and 4: Tower A 64 floors, 853'-6" to the parapet; Tower B 48 floors, 541'-8". The study's
            TEXT (NOP p. 2, IS p. 9) gives Tower B 42 floors and 494 ft: text and figures disagree. The ghost follows the
            figures, which also give its floor plate and uses; the card says so.

Both: the plan's property line (Hill Street at the bottom, 4th Street on the left) is laid on the Y-1 parcel
(web/data/population.json "y1", from the LA County Assessor) by the parcel's minimum rotated rectangle: centres matched,
the plan's x along the parcel's Hill Street side (bearing 38.5 deg), y along its 4th Street side. ASSUMED: heights are
measured from the Hill Street plaza (287 ft above sea level); floors are spread evenly between Level 6 / the Lower
California Plaza level (376 ft) and the parapet; the plate of that level is kept for the whole height. The LiDAR ground
agrees with the EIR's grades (Hill & 4th 287.7 ft, Olive 354.2 ft; EIR about 285 and 355 ft).

Point density (user, 2026-10-13: the ghosts' points as dense as the buildings around them): the median points per m2 of
roof and of wall of the towers over 80 m within 300 m of Y-1, in the web point cloud (web/data/lidar_points.laz) plus
the estimated facade points, measured on their prisms in site-model/houdini/handoff/buildings.json.

Frame of the output: local metres, x east, y north (from E 384580 / N 3768520), z NAVD88 metres, as the LiDAR.
"""
import json
import math
import sys
from pathlib import Path

import pymupdf
from shapely.geometry import MultiPoint, Polygon

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "data" / "ghosts.json"
FT = 0.3048
HILL_BEARING = 38.5                          # deg east of north: the parcel's Hill Street side (minimum rotated rectangle)
SITE_FT = (314.0, 313.0 + 11 / 12)           # the property line: along Hill Street, along 4th Street
PB1_FT, L6_FT = 287.0, 376.0                 # Hill Street plaza; Level 6 / Lower California Plaza

# 2021 Draft EIR, Figure II-14 (vector)
DEIR_PAGE = 23                               # 0-based page index in D_II.pdf
DEIR_FILL = {"A": (0.67, 0.86, 0.81), "B": (1.0, 0.83, 0.57)}
DEIR_FRAME = (222.0, 573.0, 84.0, 434.0)     # the 314'-0" and 313'-11" dimensions' ends: left, right, top, bottom (pt)

# 2019 Initial Study, Figure 10 (raster)
IS_PAGE = 27                                 # 0-based page index (PDF p. 28)
IS_FRAME = (275.0, 2368.0, 189.0, 2300.0)    # the property line in the figure's raster: left, right, top, bottom (px)
IS_INSET_X = 2550                            # the axonometric inset on the right begins here (px)

SCHEMES = [
    {
        "id": "angels-landing-2019", "name": "Angels Landing (NOP and Initial Study, March 2019)",
        "years": [2019, 2021], "research": ["ghost-004", "ent-001"],
        "source": "Angels Landing Initial Study, City of Los Angeles, March 2019: Figs. 3 and 4 (heights, uses), 10 (floor "
                  "plates, Lower California Plaza level); drawings by Handel Architects, 2018",
        "assumptions": [
            "Tower B follows the figures (48 floors, 541 ft 8 in to the parapet); the study's text gives 42 floors and 494 ft.",
            "Heights are measured from the Hill Street plaza (287 ft above sea level), as in the 2021 scheme.",
            "Floors are spread evenly between the Lower California Plaza level (taken as 376 ft, as in 2021) and the parapet.",
            "Floor plates are those of Figure 10, kept for the whole height, scaled by the property line (314 ft by 313 ft 11 in)."],
        "towers": {
            "A": {"floors": 64, "height_ft": 853.5, "name": "Angels Landing 2019, Tower A",
                  "bands": [(0, 5, "podium"), (6, 18, "hotel"), (19, 22, "lobby and amenity"), (23, 28, "apartments"),
                            (29, 40, "condominiums"), (41, 43, "amenity"), (44, 63, "condominiums"), (64, 64, "top")]},
            "B": {"floors": 48, "height_ft": round(541 + 8 / 12, 2), "name": "Angels Landing 2019, Tower B",
                  "bands": [(0, 4, "podium"), (5, 19, "hotel"), (20, 21, "amenity"), (22, 46, "apartments"),
                            (47, 48, "roof deck")]},
        },
    },
    {
        "id": "angels-landing-2021", "name": "Angels Landing (Draft EIR 2021; approved 2022)",
        "years": [2021, 2024], "research": ["ghost-005", "ent-002", "ent-004", "lit-002"],
        "source": "Angels Landing Draft EIR, ch. II, City of Los Angeles, Jan 2021: Figs. II-4 (heights, uses), II-8 and "
                  "II-14 (floor plates, dimensions)",
        "assumptions": ["Heights are measured from Level PB1, the Hill Street Plaza (287 ft above sea level).",
                        "Floors are spread evenly between Level 6 (376 ft) and the parapet.",
                        "Floor plates are those of Level 6, kept for the whole height."],
        "towers": {
            "A": {"floors": 63, "height_ft": 854, "name": "Angels Landing, Tower A",
                  "bands": [(0, 5, "podium"), (6, 18, "hotel"), (19, 21, "lobby and amenity"), (22, 27, "apartments"),
                            (28, 39, "condominiums"), (40, 41, "amenity"), (42, 61, "condominiums"), (62, 63, "top")]},
            "B": {"floors": 42, "height_ft": 494, "name": "Angels Landing, Tower B",
                  "bands": [(0, 6, "podium"), (7, 21, "hotel"), (22, 22, "amenity"), (23, 40, "apartments"),
                            (41, 42, "roof deck")]},
        },
    },
]


def deir_outlines(pdf):
    """Draft EIR Figure II-14: the towers' fills, in page points."""
    page = pymupdf.open(pdf)[DEIR_PAGE]
    m = page.rotation_matrix

    def pts(g):
        out = []
        for it in g["items"]:
            if it[0] == "l":
                out += [it[1] * m, it[2] * m]
            elif it[0] == "c":
                out += [q * m for q in it[1:5]]
            elif it[0] == "re":
                r = it[1]
                out += [pymupdf.Point(x, y) * m for x, y in ((r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1))]
            elif it[0] == "qu":
                out += [q * m for q in it[1]]
        return [(q.x, q.y) for q in out]

    fills = page.get_drawings()
    out = {}
    for k, col in DEIR_FILL.items():
        gs = [g for g in fills if g.get("fill") and tuple(round(c, 2) for c in g["fill"]) == col]
        assert gs, f"no {k} fill on the page"
        out[k] = list(MultiPoint([q for g in gs for q in pts(g)]).convex_hull.simplify(0.6).exterior.coords)[:-1]
    return out


def is_outlines(pdf):
    """Initial Study Figure 10: the towers' green fills, in the raster's pixels."""
    import cv2
    import numpy as np
    doc = pymupdf.open(pdf)
    x = doc.extract_image(doc[IS_PAGE].get_image_info(xrefs=True)[0]["xref"])
    im = cv2.imdecode(np.frombuffer(x["image"], np.uint8), cv2.IMREAD_COLOR)[..., ::-1].astype(int)
    r, g = im[..., 0], im[..., 1]
    green = ((g > r + 25) & (g > 120) & (r < 200)).astype(np.uint8) * 255
    green[:, IS_INSET_X:] = 0
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 41)))
    cs = sorted(cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea, reverse=True)[:2]
    out = {}
    for c in cs:
        k = "A" if c[:, 0, 0].mean() > (IS_FRAME[0] + IS_FRAME[1]) / 2 else "B"
        poly = cv2.approxPolyDP(c, 6, True) if k == "A" else cv2.convexHull(c)
        out[k] = [(float(u), float(v)) for u, v in poly.reshape(-1, 2)]
    assert set(out) == {"A", "B"}, "two towers expected in Figure 10"
    return out


def place(plan, frame):
    """Plan coordinates -> site metres. frame: the property line's left, right, top, bottom in plan units."""
    su, sv = SITE_FT[0] * FT / (frame[1] - frame[0]), SITE_FT[1] * FT / (frame[3] - frame[2])
    uc, vc = (frame[0] + frame[1]) / 2, (frame[2] + frame[3]) / 2
    y1 = Polygon(json.loads((ROOT / "web/data/population.json").read_text(encoding="utf-8"))["y1"][0])
    cx, cy = y1.minimum_rotated_rectangle.centroid.coords[0]
    a = math.radians(90 - HILL_BEARING)                # plan x: along Hill Street, towards the north-east
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = uy, -ux                                   # plan y (down the page): towards Hill Street, south-east
    rings = {k: [(round(cx + (u - uc) * su * ux + (v - vc) * sv * vx, 2), round(cy + (u - uc) * su * uy + (v - vc) * sv * vy, 2))
                 for u, v in ring] for k, ring in plan.items()}
    for k, r in rings.items():   # within tracing error of the parcel (its west corner is rounded; 2019 Tower B ~1.3 m)
        out = Polygon(r).difference(y1).area
        assert Polygon(r).within(y1.buffer(1.5)), f"Tower {k} leaves the parcel"
        if out > 0.5:
            print(f"  note: tower {k} lies {out:.1f} m2 outside the parcel outline (within 1.5 m)")
    return rings, (su + sv) / 2


def towers_of(rings, sc):
    out = []
    for k, ring in sorted(rings.items()):
        t = sc["towers"][k]
        top, l6 = (PB1_FT + t["height_ft"]) * FT, L6_FT * FT

        def lv(n, t=t, top=top):
            if n >= 6:
                return l6 + (n - 6) * (top - l6) / (t["floors"] + 1 - 6)
            return PB1_FT * FT + n * (l6 - PB1_FT * FT) / 6
        bands = [{"use": u, "levels": [a, b], "z": [round(lv(a), 2), round(lv(b + 1), 2)]} for a, b, u in t["bands"]]
        bands[-1]["z"][1] = round(top, 2)
        out.append({"id": f"{sc['id']}-{k.lower()}", "name": t["name"], "ring": ring, "base_z": round(PB1_FT * FT, 2),
                    "top_z": round(top, 2), "floors": t["floors"], "height_ft": t["height_ft"],
                    "area_m2": round(Polygon(ring).area, 1), "bands": bands})
    return out


def site_density():
    """Median points per m2 of roof and of wall of the towers near Y-1, as the viewer draws them."""
    import laspy
    import numpy as np
    from shapely import contains_xy
    las = laspy.read(ROOT / "web/data/lidar_points.laz")
    meta = json.loads((ROOT / "web/data/lidar_points.json").read_text(encoding="utf-8"))
    x, y, z, ob = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z), np.asarray(las["object"])
    idx = {n: i for i, n in enumerate(meta["attributes"]["object"]["names"])}
    est = {b["id"]: b["estimated"] for b in json.loads((ROOT / "web/data/facades_estimated.json").read_text(encoding="utf-8"))["buildings"]}
    roofs, walls, used = [], [], []
    for b in json.loads((ROOT / "site-model/houdini/handoff/buildings.json").read_text(encoding="utf-8"))["buildings"]:
        parts = [idx[p] for p in b["parts"] if p in idx]
        if b.get("height_m", 0) < 80 or not parts:
            continue
        m = np.isin(ob, parts)
        px, py, pz = x[m], y[m], z[m]
        if math.hypot(px.mean(), py.mean()) > 300:
            continue
        wall = roof = 0.0
        on_roof = 0
        for t in b["tiers"]:
            pg = Polygon(t["outer"])
            if pg.area < 50:
                continue
            wall += pg.length * (t["top"] - t["base"])
            roof += pg.area
            on_roof += int(np.sum(contains_xy(pg, px, py) & (np.abs(pz - t["top"]) < 1.5)))
        if roof and wall:
            roofs.append(on_roof / roof)
            walls.append((m.sum() - on_roof + est.get(b["id"], 0)) / wall)
            used.append(b["name"])
    return {"roof_per_m2": round(float(np.median(roofs)), 2), "wall_per_m2": round(float(np.median(walls)), 2),
            "towers": used, "note": "medians over these towers; roof = returns within 1.5 m of a tier top, wall = the rest "
                                    "plus the estimated facade points"}


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    density = site_density()
    plans = {"angels-landing-2019": (is_outlines(sys.argv[2]), IS_FRAME),
             "angels-landing-2021": (deir_outlines(sys.argv[1]), DEIR_FRAME)}
    schemes = []
    for sc in SCHEMES:
        rings, s = place(*plans[sc["id"]])
        schemes.append({**{k: v for k, v in sc.items() if k != "towers"}, "scale_m_per_unit": round(s, 5),
                        "density": density, "towers": towers_of(rings, sc)})
    data = {"_comment": "Unbuilt schemes on Y-1 for the viewer, built by site-model/ghosts/build_angels_landing.py; see its notes.",
            "frame": "local metres: x east, y north from E 384580 / N 3768520; z NAVD88 metres", "schemes": schemes}
    OUT.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    for sc in schemes:
        for t in sc["towers"]:
            print(f"{t['name']}: {t['area_m2']} m2 plate ({t['area_m2'] * 10.7639:,.0f} sq ft), {t['floors']} floors, "
                  f"top {t['top_z']} m ({t['top_z'] / FT:.0f} ft)")


if __name__ == "__main__":
    main()
