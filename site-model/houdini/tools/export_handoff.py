"""Write the Houdini hand-off for analysis layers (population and the like): site-model/houdini/handoff/.

Analysis layers (e.g. a modeled population, one point per person) need buildings with floor areas and the ground. This is
that information from the Houdini results, in the layout of the earlier Blender scene.json + terrain.npy (archived
project), so a script written for those only has to change where it reads from:

  buildings.json  one record per building entity (annotations/entities.json: name, address, use, Assessor
                  parcel data), each with stepped prisms ("tiers") measured from its own labelled LiDAR points;
                  plus the terrain grid description and the landmark objects (Metro portal canopy, Angels Flight).
  terrain.npy     ground heights, float32 rows x cols, row 0 = north (same layout as site-model/data/terrain.npy).

Frame: EPSG:26911 metres, NAVD88 heights, local origin E 384580 / N 3768520; x = east, y = north (NOT three.js).
Extent: the ±400 m box around Y-1 (as the earlier scene.json).

Sources: the staged, labelled points of work/stage/ at full density, named as tools/pack_wide.py pack names them
(USGS 3DEP 2023 points with the Houdini labels; ground = z - hag, i.e. Houdini's own ground model) and annotations/entities.json. Run after pack_wide.py pack and auto_entities.py:

  python tools/export_handoff.py
"""
import json
from collections import defaultdict
from pathlib import Path

import sys

import numpy as np
from scipy import ndimage
from shapely.geometry import box, mapping
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent.parent          # site-model/houdini
sys.path.insert(0, str(HERE / "tools"))
import pack_wide as pw                                 # noqa: E402  (the staged, labelled points)
ENT = HERE / "annotations/entities.json"
OUT = HERE / "handoff"

HALF = 400.0          # extent, metres from the origin
TSTEP = 2.0           # terrain grid step (as the earlier scene.json)
CELL = 1.0            # roof grid for the prisms
GAP = 2.0             # roof heights more than this apart start a new tier
MIN_TIER = 40.0       # m2: smaller tiers join the neighbouring tier closest in height
MIN_PIECE = 4.0       # m2: smaller footprint pieces are dropped
MIN_RETURNS = 3       # returns a 1 m roof cell needs
MIN_PATCH = 25.0      # m2: smaller connected groups of roof cells are dropped (as the earlier Blender tiers)
SIMPLIFY = 0.5        # m: outline simplification


def load_points():
    """Every return inside the extent (+20 m) at full density, with the final object names of pack_wide.pack
    (joins, splits, renames, point relabels). The web LAZ is thinned beyond 250 m, so it is not used here."""
    alias, final = pw.plan(verbose=False)
    xs, ys, zs, hs, os_ = [], [], [], [], []
    names_out, index = [], {}
    for c in pw.chunks():
        nm = c["file"][:-4]
        z = pw.load_chunk(nm)
        x, y = z["X"] * 0.01 - pw.OX, z["Y"] * 0.01 - pw.OY
        m = (np.abs(x) <= HALF + 20) & (np.abs(y) <= HALF + 20)
        if not m.any():
            continue
        loc = np.zeros(len(z["names"]), dtype=np.int64)
        for k, t in enumerate(z["names"]):
            while t in alias:
                t = alias[t]
            if t in pw.SPLITS:
                t = f"{t}~0"           # split objects: resolved per point below
            out = final[t]["name"] if t in final else t
            loc[k] = index.setdefault(out, len(names_out))
            if loc[k] == len(names_out):
                names_out.append(out)
        o = loc[z["name"]]
        for k, t in enumerate(z["names"]):
            while t in alias:
                t = alias[t]
            if t in pw.SPLITS:
                mk = z["name"] == k
                if mk.any():
                    cs = pw.SPLITS[t]
                    part = np.argmin((x[mk, None] - cs[None, :, 0]) ** 2 + (y[mk, None] - cs[None, :, 1]) ** 2, axis=1)
                    ids = []
                    for i in range(len(cs)):
                        t_i = f"{t}~{i}"; out = final[t_i]["name"] if t_i in final else t_i
                        ids.append(index.setdefault(out, len(names_out)))
                        if ids[-1] == len(names_out):
                            names_out.append(out)
                    o[mk] = np.array(ids)[part]
        xs.append(x[m]); ys.append(y[m]); zs.append(z["Z"][m] * 0.01); hs.append(z["hag"][m] * 0.1); os_.append(o[m])
    cat = lambda v: np.concatenate(v)
    return cat(xs), cat(ys), cat(zs), cat(os_), cat(hs).astype(np.float64), names_out


def terrain(x, y, z, hag):
    """Ground = z - hag of every point (Houdini's ground model, also under buildings), median per 2 m cell."""
    n = int(2 * HALF / TSTEP)
    x0, y0 = -HALF + TSTEP / 2, HALF - TSTEP / 2          # centre of the NW cell
    c = np.floor((x + HALF) / TSTEP).astype(int)
    r = np.floor((HALF - y) / TSTEP).astype(int)
    ok = (c >= 0) & (c < n) & (r >= 0) & (r < n)
    g = (z - hag)[ok]
    idx = (r[ok] * n + c[ok])
    order = np.argsort(idx, kind="stable")
    idx, g = idx[order], g[order]
    starts = np.r_[0, np.flatnonzero(np.diff(idx)) + 1]
    grid = np.full(n * n, np.nan, np.float64)
    grid[idx[starts]] = [np.median(s) for s in np.split(g, starts[1:])]
    grid = grid.reshape(n, n)
    holes = np.isnan(grid)
    if holes.any():                                        # nearest measured cell
        _, (ri, ci) = ndimage.distance_transform_edt(holes, return_indices=True)
        grid = grid[ri, ci]
    info = {"x0": x0, "y0": y0, "step": TSTEP, "rows": n, "cols": n,
            "note": "value at the centre of each cell; row 0 = north, column 0 = west; x0 / y0 = the NW cell centre",
            "filled_cells": f"{holes.mean():.1%} had no points and take the nearest measured cell"}
    return grid.astype(np.float32), info


def tiers_of(px, py, pz, pg):
    """Stepped prisms from an entity's points: 1 m roof cells (highest return), cut into height tiers."""
    cxy = np.floor(np.c_[px, py] / CELL).astype(np.int64)
    cells, inv, cnt = np.unique(cxy, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    top = np.full(len(cells), -np.inf)
    np.maximum.at(top, inv, pz)
    gnd = ndimage.median(pg, inv, np.arange(len(cells)))
    good = cnt >= MIN_RETURNS                              # a cell with one or two returns is a facade edge or noise
    top, gnd, kx, ky = top[good], np.asarray(gnd)[good], cells[good, 0], cells[good, 1]
    if len(top) == 0:
        return []
    # stray specks (points attached to the building from a few metres away): drop connected groups < MIN_PATCH
    ox, oy = kx.min(), ky.min()
    occ = np.zeros((kx.max() - ox + 1, ky.max() - oy + 1), bool); occ[kx - ox, ky - oy] = True
    lab_, _ = ndimage.label(occ, structure=np.ones((3, 3)))
    size = np.bincount(lab_.ravel())
    big = size[lab_[kx - ox, ky - oy]] * CELL * CELL >= MIN_PATCH
    top, gnd, kx, ky = top[big], gnd[big], kx[big], ky[big]
    if len(top) == 0:
        return []
    # tiers: sorted cell heights cut at gaps > GAP
    o = np.argsort(top)
    lab = np.zeros(len(top), int)
    lab[o] = np.r_[0, np.cumsum(np.diff(top[o]) > GAP)]
    while True:                                            # small tiers join the nearest tier in height
        ids, area = np.unique(lab, return_counts=True)
        if len(ids) == 1 or area.min() * CELL * CELL >= MIN_TIER:
            break
        s = ids[area.argmin()]
        lv = {i: np.percentile(top[lab == i], 90) for i in ids}
        lab[lab == s] = min((i for i in ids if i != s), key=lambda i: abs(lv[i] - lv[s]))
    out = []
    for t in np.unique(lab):
        m = lab == t
        shape = unary_union([box(a * CELL, b * CELL, (a + 1) * CELL, (b + 1) * CELL) for a, b in zip(kx[m], ky[m])])
        shape = shape.simplify(SIMPLIFY, preserve_topology=True)
        polys = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
        tp = float(np.percentile(top[m], 90))
        base = float(np.percentile(gnd[m], 10))
        for p in polys:
            if p.area < MIN_PIECE:
                continue
            g = mapping(p)["coordinates"]
            r2 = lambda ring: [[round(a, 2), round(b, 2)] for a, b in ring[:-1]]
            out.append({"base": round(base, 2), "top": round(tp, 2), "area_m2": round(p.area, 1),
                        "outer": r2(g[0]), "holes": [r2(h) for h in g[1:]]})
    out.sort(key=lambda t: t["top"])
    return out


def main():
    x, y, z, obj, hag, names = load_points()
    grid, tinfo = terrain(x, y, z, hag)
    OUT.mkdir(exist_ok=True)
    np.save(OUT / "terrain.npy", grid)

    ents = json.loads(ENT.read_text(encoding="utf-8"))["entities"]
    index = {n: i for i, n in enumerate(names)}
    by_obj = defaultdict(list)
    sel = np.flatnonzero(np.isin(obj, [index[n] for n in names if n.startswith(("BLD_", "PC_")) or n == "MOCA"]))
    order = sel[np.argsort(obj[sel], kind="stable")]
    o_sorted = obj[order]
    cuts = np.r_[0, np.flatnonzero(np.diff(o_sorted)) + 1, len(order)]
    for a, b in zip(cuts[:-1], cuts[1:]):
        by_obj[names[o_sorted[a]]] = order[a:b]

    inside = lambda px, py: (np.abs(px) <= HALF) & (np.abs(py) <= HALF)
    keep_fields = ("id", "name", "landmark", "use", "address", "parcel", "status", "source", "parts")
    blds = []
    for e in ents:
        parts = list(e.get("parts", [])) + list(e.get("auto_parts", []))
        pts = [by_obj[p] for p in parts if p in by_obj]
        if not pts:
            continue
        ii = np.concatenate(pts)
        ii = ii[inside(x[ii], y[ii]) & (hag[ii] > 2.0)]
        if len(ii) < 20:
            continue
        tiers = tiers_of(x[ii], y[ii], z[ii], z[ii] - hag[ii])
        if not tiers:
            continue
        rec = {k: e[k] for k in keep_fields if k in e}
        rec["parts"] = parts
        rec["height_m"] = round(max(t["top"] for t in tiers) - min(t["base"] for t in tiers), 1)
        rec["footprint_m2"] = round(sum(t["area_m2"] for t in tiers), 1)   # tiers do not overlap
        rec["tiers"] = tiers
        blds.append(rec)

    lm = {}
    for n in names:
        if n.startswith(("AF_", "Metro_")):
            ii = np.flatnonzero(obj == index[n])
            if len(ii):
                lm[n] = {"center": [round(float(x[ii].mean()), 2), round(float(y[ii].mean()), 2)],
                         "z": [round(float(z[ii].min()), 2), round(float(z[ii].max()), 2)],
                         "ground": round(float(np.median(z[ii] - hag[ii])), 2), "points": int(len(ii))}

    doc = {
        "_about": __doc__.split("\n\n")[0] + " See the docstring of site-model/houdini/tools/export_handoff.py.",
        "source": "USGS 3DEP CA_LosAngeles_B23 (2023) LiDAR at full density with the Houdini labels (the same "
                  "names as web/data/lidar_points.laz); entities, names and Assessor data from site-model/houdini/annotations/entities.json",
        "origin_utm": [384580, 3768520], "crs": "EPSG:26911 (NAD83 / UTM 11N), metres, NAVD88 heights",
        "axes": "x = east, y = north, z = up (local, from the origin)", "extent_m": [-HALF, HALF, -HALF, HALF],
        "tiers_note": f"Each tier is a prism from 'base' (ground, 10th percentile under it) to 'top' (90th percentile "
                      f"of its {CELL:g} m roof cells); tiers are cut where roof heights jump more than {GAP:g} m and "
                      f"do not overlap. Only the part of a building inside the extent is included.",
        "terrain": {**tinfo, "file": "terrain.npy"},
        "buildings": blds,
        "landmarks": lm,
    }
    (OUT / "buildings.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"buildings {len(blds)}  tiers {sum(len(b['tiers']) for b in blds)}  landmarks {len(lm)}  "
          f"buildings.json {(OUT / 'buildings.json').stat().st_size / 1e6:.2f} MB  terrain {grid.shape} "
          f"{(OUT / 'terrain.npy').stat().st_size / 1e6:.2f} MB  ({tinfo['filled_cells']})")


if __name__ == "__main__":
    main()
