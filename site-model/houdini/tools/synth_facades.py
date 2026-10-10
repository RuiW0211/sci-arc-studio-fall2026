"""Estimated facade points for buildings whose walls the airborne LiDAR barely saw (user, 2026-10-08, trial).

Airborne LiDAR sees roofs well and walls badly: glass curtain walls reflect the laser away, and the near-vertical
view grazes walls (~0.1-0.7 returns / m2 on walls against 5-9 on roofs). This adds points on the walls of the
building's stepped prisms (handoff/buildings.json), ONLY where no measured return is near, so measured points stay
as they are and there is no second "skin" next to them:

  1. walls: every outline edge of every tier rises from whatever is just outside it (the ground, or a lower tier)
     to the tier's top; edges shared with a taller tier belong to that taller tier;
  2. each wall is moved onto the measured wall points near it (median offset along its normal, within SNAP_M),
     which takes out roof overhangs and the 1 m roof-grid outline;
  3. points on the storeys: measured walls show one band per floor (the opaque spandrels return the laser, the glass
     does not), so most points sit within BAND_M of a floor line, the storey height and phase read from the building's
     own wall returns (FLOOR_M where they are too few), the rest anywhere on the wall; at random, DENSITY per m2 (the density of the walls the LiDAR did see, so filled walls match
     their neighbours), not within GAP_M of a measured return, not in the lowest BOTTOM_M above the ground
     (arcades, entrances and plazas under towers are not closed).

The points are estimates, not measurements: the viewer shows them as their own layer, in their own colour.

Like the measured cloud, the estimate thins with distance from Y-1 (pack_wide.ratio, thinning.json), each building
with its own random draw.

  python site-model/houdini/tools/synth_facades.py ["The entity name" ...]   (default: every building of the hand-off)
  -> web/data/facades_estimated.bin (float32 x, y, z in the viewer frame: x east, y up, z -north; then the object of
     each point and its height above the building's base) + .json. The viewer merges them into the building points.
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import export_handoff as eh   # noqa: E402  (full-density labelled points, the hand-off layout)

OUT = HERE.parents[2] / "web" / "data"
TRIAL = ["400 S Hope St", "Wells Fargo Center - North Tower", "AT&T building (windowless, with antenna tower)"]   # first test
DENSITY = 0.3        # points / m2 of wall: a little below the walls the LiDAR saw well (0.4-0.7), so filled walls do not stand out (user, 2026-10-08)
FLOOR_M = 4.0        # storey height when the building's own wall returns do not show one (office default)
BAND_M = 0.25        # spread of the points around each floor line (spandrels: where walls return the laser)
IN_BANDS = 0.8       # share of the points on the floor lines; the rest anywhere on the wall
GAP_M = 1.5          # no estimate within this distance of a measured return
SNAP_M = 2.5         # largest wall shift onto the measured wall points
BOTTOM_M = 6.0       # nothing in the lowest metres above the ground


def walls(tiers):
    """[(p0, p1, outward normal, z_from, z_to)] for the outline edges of all tiers (plan x east, y north)."""
    polys = [(Polygon(t["outer"], t["holes"]).buffer(0), t) for t in tiers]
    out = []
    for poly, t in polys:
        for ring in [poly.exterior] + list(poly.interiors) if poly.geom_type == "Polygon" else []:
            c = np.asarray(ring.coords)
            for a, b in zip(c[:-1], c[1:]):
                d = b - a
                L = np.hypot(*d)
                if L < 0.5:
                    continue
                n = np.array([d[1], -d[0]]) / L
                mid = (a + b) / 2
                if poly.contains(Point(*(mid + 0.3 * n))):
                    n = -n                                   # point the normal away from the tier
                probe = Point(*(mid + 0.6 * n))
                outside = [u for p, u in polys if u is not t and p.contains(probe)]
                z_from = max(u["top"] for u in outside) if outside else t["base"]
                if t["top"] - z_from > 1.0:
                    out.append((a, b, n, z_from, t["top"], t["base"]))
    return out


def storeys(zw, base, top):
    """(storey height, phase) from the heights of a building's measured wall returns, else (FLOOR_M, base)."""
    zw = zw[(zw > base + 10) & (zw < top - 8)]
    if len(zw) >= 500:
        h, _ = np.histogram(zw, bins=np.arange(base + 10, top - 8, 0.25))
        h = h - h.mean()
        ac = np.correlate(h, h, "full")[len(h) - 1:]
        lags = np.arange(len(ac)) * 0.25
        m = (lags >= 3.3) & (lags <= 4.8)
        if m.any() and ac[0] > 0 and ac[m].max() / ac[0] >= 0.15:
            per = float(lags[m][np.argmax(ac[m])])
            ph = np.arange(0, per, 0.1)
            score = [np.sum(np.exp(-0.5 * (((zw - base - q) % per) - per / 2) ** 2 / BAND_M ** 2)) for q in ph]
            return per, base + float(ph[int(np.argmin(score))])   # the phase whose band centres catch most returns
    return FLOOR_M, base


def main(names):
    x, y, z, obj, hag, objnames = eh.load_points()
    hand = json.loads((eh.OUT / "buildings.json").read_text(encoding="utf-8"))["buildings"]
    index = {n: i for i, n in enumerate(objnames)}
    rng = np.random.default_rng(2026)
    pts, objs, hags, report = [], [], [], []
    todo = [b for b in hand if not names or (b.get("name") or "") in names]
    for e in todo:
        want = e.get("name") or e["id"]
        u_bld = rng.random()                                  # this building's own draw for the distance thinning
        ids = [index[p] for p in e["parts"] if p in index]
        sel = np.flatnonzero(np.isin(obj, ids))
        P = np.c_[x[sel], y[sel], z[sel]]
        tree = cKDTree(P)
        top = max(t["top"] for t in e["tiers"]); base = min(t["base"] for t in e["tiers"])
        per, phase = storeys(P[:, 2], base, top)
        added = 0
        for a, b, n, z0, z1, ground in walls(e["tiers"]):
            lo = max(z0, ground + BOTTOM_M)
            if z1 - lo < 1.0:
                continue
            # measured wall points near this edge (not roof): snap the wall onto them
            d = b - a
            L = np.hypot(*d)
            u = d / L
            rel = P[:, :2] - a
            along, off = rel @ u, rel @ n
            near = (along > -0.5) & (along < L + 0.5) & (np.abs(off) < SNAP_M) & (P[:, 2] > lo) & (P[:, 2] < z1 - 1.5)
            shift = float(np.clip(np.median(off[near]), -SNAP_M, SNAP_M)) if near.sum() >= 8 else 0.0
            k = rng.poisson(DENSITY * L * (z1 - lo))
            if k == 0:
                continue
            S = rng.uniform(0, L, k)
            lines = phase + per * np.arange(np.ceil((lo - phase) / per), np.floor((z1 - phase) / per) + 1)
            Z = rng.uniform(lo, z1, k)
            if len(lines):
                on = rng.random(k) < IN_BANDS
                Z[on] = rng.choice(lines, on.sum()) + rng.normal(0, BAND_M, on.sum())
                Z = np.clip(Z, lo, z1)
            XY = a + np.outer(S, u) + n * shift
            C = np.c_[XY, Z]
            free = tree.query(C, distance_upper_bound=GAP_M)[0] == np.inf
            C = C[free]
            C = C[rng.random(len(C)) < eh.pw.ratio(C[:, 0], C[:, 1], np.full(len(C), u_bld))]   # thin with distance
            pts.append(C)
            # merged into the building (user, 2026-10-10): each point takes the object of the nearest measured return,
            # so it is picked and highlighted with its building, and that return's ground (its z - height above ground)
            if len(C):
                k_near = tree.query(C)[1]
                objs.append(obj[sel][k_near])
                hags.append(np.round((C[:, 2] - (z[sel][k_near] - hag[sel][k_near])) * 10).astype(np.int16))
            added += len(C)
        report.append({"name": want, "id": e["id"], "measured": int(len(sel)), "estimated": added,
                       "storey_m": round(per, 2), "storey_from": "measured walls" if per != FLOOR_M or phase != base else "default"})
        if names or added > 2000:
            print(f"{want}: {len(sel)} measured points, {added} estimated wall points, storeys {per:.2f} m ({report[-1]['storey_from']})")
    A = np.concatenate(pts) if pts else np.zeros((0, 3))
    three = np.c_[A[:, 0], A[:, 2], -A[:, 1]].astype(np.float32)          # viewer frame
    O = np.concatenate(objs) if objs else np.zeros(0, int)
    used = sorted(set(O.tolist()))
    oi = {o: k for k, o in enumerate(used)}
    obj_idx = np.array([oi[o] for o in O], np.uint16)                       # index into "objects" (names)
    H = np.concatenate(hags) if hags else np.zeros(0, np.int16)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facades_estimated.bin").write_bytes(three.tobytes() + obj_idx.tobytes() + H.astype(np.int16).tobytes())
    (OUT / "facades_estimated.json").write_text(json.dumps({
        "file": "facades_estimated.bin", "count": int(len(three)),
        "format": "float32 x, y, z (x east, y up, z -north) for every point, then uint16 object (index into objects), "
                  "then int16 height above the building's base (0.1 m)",
        "objects": [objnames[o] for o in used],
        "buildings": report,
        "source": "ESTIMATED, not measured: points on the walls of the building prisms of site-model/houdini/handoff/ "
                  "where the 2023 LiDAR has no return within %.1f m (site-model/houdini/tools/synth_facades.py)" % GAP_M,
        "settings": {"density_per_m2": DENSITY, "floor_m": FLOOR_M, "band_m": BAND_M, "in_bands": IN_BANDS, "gap_m": GAP_M, "snap_m": SNAP_M, "bottom_m": BOTTOM_M},
    }, indent=1))
    print(f"wrote {len(three)} points ({(OUT / 'facades_estimated.bin').stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main(sys.argv[1:])
