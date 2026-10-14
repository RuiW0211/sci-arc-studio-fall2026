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
            "towers": towers,
        }],
    }
    OUT.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    for t in towers:
        print(f"{t['name']}: {t['area_m2']} m2 plate, {t['floors']} floors, top {t['top_z']} m ({t['top_z'] / FT:.0f} ft)")


if __name__ == "__main__":
    main()
