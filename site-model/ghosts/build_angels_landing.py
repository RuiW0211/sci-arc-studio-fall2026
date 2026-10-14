"""Ghost towers for the viewer: the Angels Landing scheme of the January 2021 Draft EIR (approved February 3, 2022),
traced from the EIR's own drawings (user, 2026-10-13: "put the research into the viewer: ghost towers").

  python site-model/ghosts/build_angels_landing.py "<path to D_II.pdf>"   -> web/data/ghosts.json

D_II.pdf is Chapter II (Project Description) of the Angels Landing Draft EIR, City of Los Angeles, January 2021 (a
public document; not kept in the repository for its size, 30 MB). What is read from it:

  * floor plates: Figure II-14, Level 6 (Lower California Plaza), page II-23. The plan is vector: Tower A's hotel floor
    is the green fill, Tower B's fitness / spa floor the orange fill; each tower's outline is the convex hull of its fill.
  * scale: the plan's dimensions, 314'-0" along Hill Street (351 pt) and 313'-11" along 4th Street (350 pt), read off the
    page at 4 px / pt: 0.27302 m per pt (the two agree to 0.25 %).
  * placement: the plan's property line (Hill Street at the bottom, 4th Street on the left) laid on the Y-1 parcel
    (web/data/population.json "y1", from the LA County Assessor) by the parcel's minimum rotated rectangle: centres
    matched, the plan's x along the parcel's Hill Street side (bearing 38.5 deg), y along its 4th Street side.
    The parcel measures 316.3 x 314.7 ft; the plan 314'-0" x 313'-11".
  * heights: Figure II-4, "854'-0" T.O. parapet, 63 floors" (Tower A) and "494'-0" T.O. parapet, 42 floors" (Tower B);
    level elevations on the plans are feet above sea level (Level PB1, Hill Street Plaza, 287'-0", Fig. II-8; Level 6
    376'-0", Fig. II-14). ASSUMED: the tower heights are measured from Level PB1 (287 ft), so the parapets stand at
    1,141 ft and 781 ft above sea level. The LiDAR ground agrees with the EIR's grades (Hill & 4th 287.7 ft, Olive 354.2
    ft; EIR about 285 and 355 ft).
  * uses: Figure II-4's floor bands. ASSUMED: floors are spread evenly between Level 6 (376 ft) and the parapet; the
    figure gives floor-to-floor heights for some bands only.
  * point density (user, 2026-10-13: the ghosts' points as dense as the buildings around them): the median points per m2
    of roof and of wall of the towers over 80 m within 300 m of Y-1, in the web point cloud (web/data/lidar_points.laz)
    plus the estimated facade points, measured on their prisms in site-model/houdini/handoff/buildings.json.

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

PAGE = 23                                    # Figure II-14, 0-based page index in D_II.pdf
FILL = {"A": (0.67, 0.86, 0.81), "B": (1.0, 0.83, 0.57)}
DIM_U = (222.0, 573.0, 314.0)                # x of the 314'-0" dimension's ends (pt), its length (ft)
DIM_V = (84.0, 434.0, 313.0 + 11 / 12)       # y of the 313'-11" dimension's ends (pt)
HILL_BEARING = 38.5                          # deg east of north: the parcel's Hill Street side (minimum rotated rectangle)
PB1_FT, L6_FT = 287.0, 376.0
SITE_FT = (314.0, 313.0 + 11 / 12)           # the property line: along Hill Street, along 4th Street

# (level from, level to, use) bottom to top, from Figure II-4; levels below 6 are the podium
BANDS = {
    "A": [(0, 5, "podium"), (6, 18, "hotel"), (19, 21, "lobby and amenity"), (22, 27, "apartments"),
          (28, 39, "condominiums"), (40, 41, "amenity"), (42, 61, "condominiums"), (62, 63, "top")],
    "B": [(0, 6, "podium"), (7, 21, "hotel"), (22, 22, "amenity"), (23, 40, "apartments"), (41, 42, "roof deck")],
}
TOWERS = {
    "A": {"floors": 63, "height_ft": 854, "name": "Angels Landing, Tower A"},
    "B": {"floors": 42, "height_ft": 494, "name": "Angels Landing, Tower B"},
}


def plan_outlines(pdf):
    page = pymupdf.open(pdf)[PAGE]
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
    for k, col in FILL.items():
        gs = [g for g in fills if g.get("fill") and tuple(round(c, 2) for c in g["fill"]) == col]
        assert gs, f"no {k} fill on the page"
        out[k] = list(MultiPoint([q for g in gs for q in pts(g)]).convex_hull.simplify(0.6).exterior.coords)[:-1]
    return out


def to_site(plan):
    s = ((DIM_U[2] / (DIM_U[1] - DIM_U[0])) + (DIM_V[2] / (DIM_V[1] - DIM_V[0]))) / 2 * FT
    uc, vc = (DIM_U[0] + DIM_U[1]) / 2, (DIM_V[0] + DIM_V[1]) / 2
    y1 = Polygon(json.loads((ROOT / "web/data/population.json").read_text(encoding="utf-8"))["y1"][0])
    cx, cy = y1.minimum_rotated_rectangle.centroid.coords[0]
    a = math.radians(90 - HILL_BEARING)                          # plan x: along Hill Street, towards the north-east
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = uy, -ux                                             # plan y (down the page): towards Hill Street, south-east
    rings = {k: [(round(cx + (u - uc) * s * ux + (v - vc) * s * vx, 2), round(cy + (u - uc) * s * uy + (v - vc) * s * vy, 2))
                 for u, v in ring] for k, ring in plan.items()}
    for k, r in rings.items():
        assert Polygon(r).within(y1.buffer(0.5)), f"Tower {k} leaves the parcel"
    return rings, s


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
    # walls: the same density as the estimated facades of the real buildings (synth_facades.py DENSITY, user 2026-10-15:
    # 0.75, the median of the wall cells the LiDAR saw), so built and unbuilt towers read alike; the measured median is kept
    return {"roof_per_m2": round(float(np.median(roofs)), 2), "wall_per_m2": 0.75, "wall_measured_median": round(float(np.median(walls)), 2),
            "towers": used, "note": "medians over these towers; roof = returns within 1.5 m of a tier top, wall = the rest "
                                    "plus the estimated facade points"}


# Three California Plaza: the third office tower of California Plaza, planned for Y-1 (Phase 3A), on hold by 1990, never
# drawn in anything we could reach (user, 2026-10-13: model it schematically from the sources and the two CCA images).
# SCHEMATIC: every number is a choice within what the sources allow, all listed on its card.
THREE_CAL = {
    "plaza_ft": 385.0,         # the upper plaza level the tower would rise from (Angels Flight's top station raised from
                               # 370 to 385 ft in 1989, LA Times 1989-06-09; plaza levels 385 / 370 ft, CCA ARCH82125-7)
    "floors": 60,              # the 1981 DDA's maximum ("3 towers 37-60 stories", USC finding aid); the web gives 62-65
    "floor_m": 4.44,           # the mean floor-to-floor of One (4.33 m) and Two (4.54 m) California Plaza, from the LiDAR
    "office_sqft": 1_080_000,  # midpoint of what the 3.2M (1981 DDA) or 3.5M sq ft (LA Times 1987) totals leave after
                               # One (1.0M) and Two (1.27M) California Plaza
    "corner": 0.18,            # rounded corners, radius / side: the rounded square towers of the 1980 rendering and model
    "setback_m": 8.0,          # from Olive Street and 4th Street
}


def three_cal_plaza():
    """A rounded square on the Olive / 4th corner of Y-1 (SkyscraperPage: "Olive Street & 4th Street"; the 1980 CCA
    rendering shows the lower, Hill Street side of Y-1 as a garden with Angels Flight), aligned with the street grid."""
    import numpy as np
    T = THREE_CAL
    plate = T["office_sqft"] / T["floors"] / 10.7639
    side = math.sqrt(plate / (1 - (4 - math.pi) * T["corner"] ** 2))
    r, h = T["corner"] * side, side / 2
    loop = []
    for cx, cy, a0 in ((h - r, h - r, 0), (-(h - r), h - r, 90), (-(h - r), -(h - r), 180), (h - r, -(h - r), 270)):
        for k in range(7):
            a = math.radians(a0 + 15 * k)
            loop.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    y1 = Polygon(json.loads((ROOT / "web/data/population.json").read_text(encoding="utf-8"))["y1"][0])
    rect = y1.minimum_rotated_rectangle
    cx, cy = rect.centroid.coords[0]
    a = math.radians(90 - HILL_BEARING)
    ux, uy = math.cos(a), math.sin(a)          # along Hill Street, north-east
    vx, vy = uy, -ux                           # towards Hill Street, south-east
    half_u = half_v = SITE_FT[0] * FT / 2
    # the plan's top-left is the west corner (Olive and 4th): centre the square setback + side / 2 in from both
    cu, cv = -half_u + T["setback_m"] + h, -half_v + T["setback_m"] + h
    ring = [(round(cx + (cu + u) * ux + (cv + v) * vx, 2), round(cy + (cu + u) * uy + (cv + v) * vy, 2)) for u, v in loop]
    assert Polygon(ring).within(y1), "Three California Plaza leaves the parcel"
    # ground under it (Houdini terrain), for the podium below the plaza
    tb = json.loads((ROOT / "site-model/houdini/handoff/buildings.json").read_text(encoding="utf-8"))["terrain"]
    grid = np.load(ROOT / "site-model/houdini/handoff/terrain.npy")
    px, py = Polygon(ring).centroid.coords[0]
    ground = float(grid[int(round((tb["y0"] - py) / tb["step"])), int(round((px - tb["x0"]) / tb["step"]))])
    base, plaza = ground, T["plaza_ft"] * FT
    top = plaza + T["floors"] * T["floor_m"]
    tower = {"id": "three-california-plaza", "name": "Three California Plaza (schematic)", "ring": ring,
             "base_z": round(base, 2), "top_z": round(top, 2), "floors": T["floors"],
             "height_ft": round((top - plaza) / FT), "area_m2": round(Polygon(ring).area, 1),
             "bands": [{"use": "podium", "levels": [0, 0], "z": [round(base, 2), round(plaza, 2)]},
                       {"use": "offices", "levels": [1, T["floors"]], "z": [round(plaza, 2), round(top, 2)]}]}
    return {
        "id": "three-california-plaza", "name": "Three California Plaza, Phase 3A of California Plaza (1981 plan; on hold by 1990)",
        "layer": "Unbuilt_schematic", "years": [1981, 1990], "research": ["ghost-001", "plaza-006", "plaza-001"],
        "source": "SCHEMATIC. 1981 DDA scope (USC Bunker Hill records, finding aid): 3 office towers, 37-60 stories, 3.2M sq ft; "
                  "LA Times 1985, 1987, 1989 (sizes of the built towers, plaza at 385 ft, third phase with Angels Flight); "
                  "1980 competition rendering and master-plan model (CCA, Arthur Erickson fonds) for the tower's form",
        "assumptions": [
            "No drawing of this tower was found: its plan, position, height and floors are all assumed.",
            "60 floors, the 1981 DDA's maximum; other sources give 62, 63 or 65, and 853, 915 or 950 ft, all unsourced.",
            "Floors 4.44 m apart, the mean of One and Two California Plaza; rising from the 385 ft plaza, a podium below.",
            "About 1.08M sq ft of offices (what the 3.2M or 3.5M sq ft programmes leave after the two built towers), "
            "18,000 sq ft a floor, as a rounded square like the towers of the 1980 rendering and model.",
            "On the Olive and 4th corner of Y-1, 8 m from both streets; the Hill Street side left as the garden of the rendering.",
            "The tower's own drawing (CCA ARCH254551, c.1985, 'footprint of tower three') has not been seen."],
        "towers": [tower],
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rings, s = to_site(plan_outlines(sys.argv[1]))
    towers = []
    for k, ring in rings.items():
        t = TOWERS[k]
        top = (PB1_FT + t["height_ft"]) * FT
        lv = lambda n, t=t, top=top: L6_FT * FT + (n - 6) * (top - L6_FT * FT) / (t["floors"] + 1 - 6) if n >= 6 \
            else PB1_FT * FT + n * (L6_FT - PB1_FT) * FT / 6
        bands = [{"use": u, "levels": [a, b], "z": [round(lv(a), 2), round(lv(b + 1), 2)]} for a, b, u in BANDS[k]]
        bands[-1]["z"][1] = round(top, 2)
        towers.append({"id": f"angels-landing-2021-{k.lower()}", "name": t["name"], "ring": ring,
                       "base_z": round(PB1_FT * FT, 2), "top_z": round(top, 2), "floors": t["floors"],
                       "height_ft": t["height_ft"], "area_m2": round(Polygon(ring).area, 1), "bands": bands})
    data = {
        "_comment": "Unbuilt schemes on Y-1 for the viewer, built by site-model/ghosts/build_angels_landing.py; see its notes.",
        "frame": "local metres: x east, y north from E 384580 / N 3768520; z NAVD88 metres",
        "schemes": [{
            "id": "angels-landing-2021",
            "name": "Angels Landing (Draft EIR 2021; approved 2022)",
            "years": [2021, 2024], "research": ["ghost-005", "ent-002", "ent-004", "lit-002"],
            "source": "Angels Landing Draft EIR, ch. II, City of Los Angeles, Jan 2021: Figs. II-4 (heights, uses), II-8 and "
                      "II-14 (floor plates, dimensions)",
            "assumptions": ["Heights are measured from Level PB1, the Hill Street Plaza (287 ft above sea level).",
                            "Floors are spread evenly between Level 6 (376 ft) and the parapet.",
                            "Floor plates are those of Level 6, kept for the whole height."],
            "scale_m_per_pt": round(s, 5),
            "density": site_density(),
            "towers": towers,
        }],
    }
    tc = three_cal_plaza()
    tc["density"] = data["schemes"][0]["density"]
    data["schemes"].insert(0, tc)
    OUT.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    for sc in data["schemes"]:
        for t in sc["towers"]:
            print(f"{t['name']}: {t['area_m2']} m2 plate ({t['area_m2'] * 10.7639:,.0f} sq ft), {t['floors']} floors, "
                  f"base {t['base_z']} m, top {t['top_z']} m ({t['top_z'] / FT:.0f} ft)")


if __name__ == "__main__":
    main()
