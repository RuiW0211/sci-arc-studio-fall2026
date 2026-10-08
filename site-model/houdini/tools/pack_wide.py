"""Merge the chunked LiDAR labels into one web point cloud, thinned per object with distance from Y-1.

  python site-model/houdini/tools/pack_wide.py stage    chunk labels + chunk LAZ -> work/stage/<chunk>.npz (compact) and
                                                        work/stage/objects.json (per-object point count, centroid, layer)
  python site-model/houdini/tools/pack_wide.py plan     names unified across seams, renumbered; keep ratios; point estimate
  python site-model/houdini/tools/pack_wide.py pack     thinned LAZ + meta -> web/data/lidar_points.laz / .json (the website's point cloud)
  options for trials: --r0 <m> --power <p> --keep-min <r> --out <dir under site-model/houdini/> (trials; not the website)

Thinning (agreed with the user 2026-10-06):
  * full density for every object whose centre lies within R0 = 300 m of Y-1;
  * farther out the keep ratio falls off as (R0 / d_eff)^P, d_eff = the object's distance stretched by a per-object random
    factor and a smooth large-scale noise field, so the fade is irregular and the outer edge is ragged, not a drawn circle;
  * one ratio per object (a building, tree, car ... keeps one density); points are picked by a hash of their coordinates,
    so a re-run gives the same result; objects whose ratio falls below KEEP_MIN are left out;
  * beyond that a faint "mist" (MIST = 0.8 % of every object and of the ground) carries on and fades out itself around
    0.9-1.3 km with its own noise, so the city does not stop at a line;
  * Terrain, _other and Street_furniture are not objects: their ratio comes from each point's position, with a smooth
    60 m noise field in place of the per-object random (irregular patches, no squares).
"""
import json
import sys
import zlib
from pathlib import Path

import laspy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_chunks import geo_attribs  # noqa: E402

HZ = Path(__file__).resolve().parent.parent
WORK, STAGE = HZ / "work", HZ / "work" / "stage"
OUT = HZ.parents[1] / "web" / "data"     # the website reads it from here (one location)
OX, OY = 384580, 3768520
R0, P, KEEP_MIN, CELL = 300.0, 3.3, 0.015, 60.0
JITTER, NOISE, NOISE_SCALE = 0.18, 0.22, 350.0      # per-object stretch (+-), smooth field amplitude, its wavelength (m)
# "mist" beyond the fade: every object / ground patch still keeps MIST of its points (a faint haze of the city going on),
# itself fading out between MIST_END - MIST_W and MIST_END (stretched by its own +-12 % noise), inside the 9-tile data
MIST, MIST_END, MIST_W = 0.0, 1150.0, 250.0
# outer edge of the whole fade: everything tapers to nothing between EDGE_END - EDGE_W and EDGE_END (stretched by +-12 %
# noise), so the cloud never reaches the square edge of the 9-tile data (~1.42 km east of Y-1)
EDGE_END, EDGE_W = 1230.0, 300.0
DENSITY, DENSITY_INSIDE = 1.0, False
# site-model/houdini/thinning.json overrides the defaults above (see its "_" notes); command-line flags override both
_cfg_path = HZ / "thinning.json"
if _cfg_path.exists():
    _c = json.load(open(_cfg_path))
    R0 = float(_c.get("full_density_radius_m", R0)); P = float(_c.get("falloff_power", P))
    DENSITY = float(_c.get("density", DENSITY)); DENSITY_INSIDE = bool(_c.get("density_inside_too", DENSITY_INSIDE))
    KEEP_MIN = float(_c.get("keep_min", KEEP_MIN)); EDGE_END = float(_c.get("edge_end_m", EDGE_END))
    EDGE_W = float(_c.get("edge_width_m", EDGE_W)); JITTER = float(_c.get("object_jitter", JITTER))
    NOISE = float(_c.get("noise_amplitude", NOISE)); NOISE_SCALE = float(_c.get("noise_wavelength_m", NOISE_SCALE))
    CELL = float(_c.get("ground_patch_m", CELL)); MIST = float(_c.get("mist", MIST)); MIST_END = float(_c.get("mist_end_m", MIST_END))
CELL_KINDS = ("Terrain", "_other", "Street_furniture")
RENUMBER = ("Tree", "Vehicle", "Shrub", "Wall", "PC")
# kinds that keep their position-based chunk names (PC_<x>_<z>, metres) instead of a running number: the building
# entity table (annotations/entities.json) refers to them, and a running number shifts whenever one is added or removed
KEEP_NAMES = ("PC",)
SEGMENTS = ["ground", "low", "building", "tree", "unsure", "podium_tree", "porous_facade", "shrub", "vehicle", "wall",
            "street_furniture"]


def chunks():
    return json.load(open(WORK / "chunks" / "chunks.json"))["chunks"]


# ---------------------------------------------------------------- stage
def stage():
    STAGE.mkdir(exist_ok=True)
    objects = {}
    for c in chunks():
        nm = c["file"][:-4]
        A, n = geo_attribs(WORK / "labels" / f"{nm}.geo")
        las = laspy.read(WORK / "chunks" / c["file"])
        src = A["ptsrc"].astype(np.int64)
        names, nidx = A["lname"]
        layers, lidx = A["llayer"]
        X, Y, Z = (np.asarray(getattr(las, k))[src].astype(np.int32) for k in "XYZ")
        np.savez(STAGE / f"{nm}.npz", X=X, Y=Y, Z=Z, cls=np.asarray(las.classification)[src],
                 inten=np.asarray(las.intensity)[src], segc=A["segc"].astype(np.uint8),
                 hag=np.clip(A["hagdm"], -32768, 32767).astype(np.int16), name=np.asarray(nidx, dtype=np.int32),
                 names=np.asarray(names, dtype=object), layer=np.asarray(lidx, dtype=np.int16),
                 layers=np.asarray(layers, dtype=object))
        # per object in this chunk: count, centroid sum (local x, north), layer
        x, nn = X * 0.01 - OX, Y * 0.01 - OY
        cnt = np.bincount(nidx, minlength=len(names))
        sx, sn = np.bincount(nidx, x, len(names)), np.bincount(nidx, nn, len(names))
        lay_of = np.zeros(len(names), dtype=np.int64); lay_of[nidx] = lidx
        for k, s in enumerate(names):
            if cnt[k] == 0 or s in CELL_KINDS:
                continue
            o = objects.setdefault(s, {"n": 0, "sx": 0.0, "sn": 0.0, "layer": layers[lay_of[k]], "chunks": []})
            o["n"] += int(cnt[k]); o["sx"] += float(sx[k]); o["sn"] += float(sn[k]); o["chunks"].append(nm)
        print(f"{nm}: {n:,} points, {len(names)} names", flush=True)
    json.dump(objects, open(STAGE / "objects.json", "w"))
    print(f"{len(objects):,} objects -> {STAGE}")


# ---------------------------------------------------------------- plan
def kind(name):
    k = name.split("_")[0]
    return k if k in RENUMBER else None


def name_pos(name):
    p = name.split("_")
    s = 1.0 if p[0] == "PC" else 0.1
    return float(p[1]) * s, -float(p[2]) * s        # local x, north


def hash01(*ints):
    h = zlib.crc32(np.asarray(ints, dtype=np.int64).tobytes())
    return (h & 0xFFFFFF) / float(0x1000000)


def noise(x, n, scale=None, seed=7):
    """Smooth value noise in [-1, 1] over the plan (smoothstep-bilinear on a random lattice, fixed seed), wavelength scale."""
    scale = scale or NOISE_SCALE
    rng = np.random.default_rng(seed)
    lat = rng.uniform(-1, 1, (64, 64))
    gx, gn = x / scale + 32, n / scale + 32
    i, j = np.floor(gx).astype(int) % 63, np.floor(gn).astype(int) % 63
    fx, fn = gx - np.floor(gx), gn - np.floor(gn)
    fx, fn = fx * fx * (3 - 2 * fx), fn * fn * (3 - 2 * fn)
    a, b, c, d = lat[i, j], lat[i + 1, j], lat[i, j + 1], lat[i + 1, j + 1]
    return (a * (1 - fx) + b * fx) * (1 - fn) + (c * (1 - fx) + d * fx) * fn


def ratio(x, n, u):
    """Keep ratio at plan position (x, north) for an object / cell with its own random u in [0, 1)."""
    d = np.hypot(x, n)
    d_eff = d * (1 + JITTER * (2 * u - 1)) * (1 + NOISE * noise(x, n))
    r = np.where(d <= R0, 1.0, np.minimum(1.0, DENSITY * (R0 / np.maximum(d_eff, 1)) ** P))
    if DENSITY_INSIDE:
        r = np.where(d <= R0, min(1.0, DENSITY), r)
    d_m = d * (1 + 0.12 * noise(x, n, 500.0, seed=23))
    r = np.where(r < KEEP_MIN, 0.0, r)                     # objects whose own share is too small are left out ...
    r = r * np.clip((EDGE_END - d_m) / EDGE_W, 0, 1)        # ... then the outer taper thins the rest to nothing
    mist = MIST * np.clip((MIST_END - d_m) / MIST_W, 0, 1)
    return np.maximum(r, mist)


SPLITS = {}      # object -> part centres, filled by plan()


def load_chunk(nm):
    """A staged chunk as a dict, with the point relabels of work/stage/points/ applied in order:
    <chunk>.npz (tools/car_sweep.py apply: unassigned points that are cars / trucks get a new vehicle object) and
    <chunk>__other.npz (tools/refine_objects.py other: unassigned points that belong to an existing building or tree).
    Each file holds idx (point indices), name (object name per point) and layer (one layer, or one per point)."""
    z = np.load(STAGE / f"{nm}.npz", allow_pickle=True)
    d = {k: z[k] for k in z.files}
    for pf in (STAGE / "points" / f"{nm}.npz", STAGE / "points" / f"{nm}__other.npz"):
        if not pf.exists():
            continue
        p = np.load(pf, allow_pickle=True)
        names = list(d["names"]); layers = list(d["layers"])
        name_i = {s: i for i, s in enumerate(names)}; layer_i = {s: i for i, s in enumerate(layers)}
        lay = np.broadcast_to(np.asarray(p["layer"], dtype=object), p["idx"].shape)
        for s in set(p["name"]):
            if s not in name_i:
                name_i[s] = len(names); names.append(s)
        for s in set(lay):
            if s not in layer_i:
                layer_i[s] = len(layers); layers.append(s)
        ni = d["name"].copy(); ni[p["idx"]] = np.array([name_i[s] for s in p["name"]])
        la = d["layer"].copy(); la[p["idx"]] = np.array([layer_i[s] for s in lay])
        d.update(names=np.asarray(names, dtype=object), layers=np.asarray(layers, dtype=object), name=ni, layer=la)
    return d


def point_objects():
    """Objects created by point relabels (new vehicles; new LiDAR-only structures PC_ of the __other files):
    {name: {n, sx, sn, layer, chunks}} (for plan())."""
    out = {}
    for pf in sorted((STAGE / "points").glob("*.npz")) if (STAGE / "points").exists() else []:
        z = np.load(STAGE / (pf.stem.split("__")[0] + ".npz"), allow_pickle=True); p = np.load(pf, allow_pickle=True)
        x, n = z["X"][p["idx"]] * 0.01 - OX, z["Y"][p["idx"]] * 0.01 - OY
        lay = np.broadcast_to(np.asarray(p["layer"], dtype=object), p["idx"].shape)
        known = set(z["names"])
        for s in set(p["name"]):
            if "__" in pf.stem and (s in known or not s.startswith("PC_")):
                continue           # __other files: only their new structures are new objects
            m = p["name"] == s
            o = out.setdefault(s, {"n": 0, "sx": 0.0, "sn": 0.0, "layer": str(lay[m][0]), "chunks": []})
            o["n"] += int(m.sum()); o["sx"] += float(x[m].sum()); o["sn"] += float(n[m].sum()); o["chunks"].append(pf.stem)
    return out


def plan(verbose=True):
    objects = json.load(open(STAGE / "objects.json"))
    objects.update(point_objects())      # cars found among unassigned points (car_sweep.py apply)
    # 1. seam splits: same kind, names < 2 m apart, seen by different chunks -> one name (the larger object's)
    alias = {}
    by_kind = {}
    for s in objects:
        k = kind(s)
        if k:
            by_kind.setdefault(k, []).append(s)
    from scipy.spatial import cKDTree
    merged = 0
    for k, ns in by_kind.items():
        pos = np.array([name_pos(s) for s in ns])
        pairs = cKDTree(pos).query_pairs(2.0)
        for a, b in pairs:
            sa, sb = ns[a], ns[b]
            if set(objects[sa]["chunks"]) & set(objects[sb]["chunks"]):
                continue                                    # both seen in one chunk: two distinct objects
            keep, drop = (sa, sb) if objects[sa]["n"] >= objects[sb]["n"] else (sb, sa)
            while keep in alias:
                keep = alias[keep]
            if drop != keep:
                alias[drop] = keep; merged += 1
    # 1b. object refinements from tools/refine_objects.py (e.g. tree fragments joined to their crown), {dropped: kept}
    def root(t):
        while t in alias:
            t = alias[t]
        return t
    refine = json.load(open(STAGE / "refine_alias.json")) if (STAGE / "refine_alias.json").exists() else {}
    for drop, keep in refine.items():
        if drop in objects and keep in objects and root(drop) != root(keep):
            alias[root(drop)] = root(keep)
    if verbose and refine:
        print(f"{len(refine):,} refinement joins (refine_alias.json)")
    final = {}
    for s, o in objects.items():
        t = s
        while t in alias:
            t = alias[t]
        f = final.setdefault(t, {"n": 0, "sx": 0.0, "sn": 0.0, "layer": o["layer"]})
        f["n"] += o["n"]; f["sx"] += o["sx"]; f["sn"] += o["sn"]
    # 1b'. relabels from tools/refine_objects.py (work/stage/refine_relabel.json, {object: {"layer": ..., "name": ...}}):
    # an object that is really another kind (e.g. pine crowns on a deck taken for a structure) gets a new layer and name
    relabel = json.load(open(STAGE / "refine_relabel.json")) if (STAGE / "refine_relabel.json").exists() else {}
    for s0, rl in relabel.items():
        if s0.startswith("_"):
            continue
        t = root(s0)
        if t not in final:
            continue
        f = final.pop(t)
        f["layer"] = rl.get("layer", f["layer"])
        new = rl.get("name", t)
        final[new] = f
        if new != t:
            alias[t] = new
    if verbose and relabel:
        print(f"{sum(1 for k in relabel if not k.startswith('_')):,} relabels (refine_relabel.json)")
    # 1c. splits from tools/refine_objects.py (e.g. cars parked nose to tail that came out as one vehicle):
    # {object: [[x, north], ...] part centres}; each point goes to the nearest centre, the parts are named <object>~<i>
    SPLITS.clear()
    split = json.load(open(STAGE / "refine_split.json")) if (STAGE / "refine_split.json").exists() else {}
    for t, cs in split.items():
        t = root(t)
        if t not in final or len(cs) < 2:
            continue
        f = final.pop(t)
        SPLITS[t] = np.asarray(cs, dtype=float)
        for i, (cx, cn) in enumerate(cs):
            m = f["n"] / len(cs)
            final[f"{t}~{i}"] = {"n": m, "sx": cx * m, "sn": cn * m, "layer": f["layer"]}
    if verbose and SPLITS:
        print(f"{len(SPLITS):,} objects split (refine_split.json) into {sum(len(c) for c in SPLITS.values()):,} parts")
    # 2. renumber the position-named kinds by distance from Y-1 (5 digits: never equal to the old 3-4 digit names)
    newname = {}
    for k in RENUMBER:
        if k in KEEP_NAMES:
            continue
        ns = [s for s in final if kind(s) == k]
        ns.sort(key=lambda s: np.hypot(final[s]["sx"] / final[s]["n"], final[s]["sn"] / final[s]["n"]))
        for i, s in enumerate(ns, 1):
            newname[s] = f"{k}_{i:05d}"
    # 3. keep ratio per object
    for s, f in final.items():
        cx, cn = f["sx"] / f["n"], f["sn"] / f["n"]
        f["r"] = float(ratio(np.array(cx), np.array(cn), hash01(zlib.crc32(s.encode()))))
        f["name"] = newname.get(s, s)
    est = sum(f["n"] * f["r"] for f in final.values())
    if verbose:
        print(f"{len(objects):,} chunk objects, {merged} seam splits joined -> {len(final):,} objects;"
              f" {sum(1 for f in final.values() if f['r'] > 0):,} kept; objects alone give ~{est / 1e6:.1f}M points")
    return alias, final


def cell_ratio(x, n):
    """Keep ratio for Terrain / _other / Street_furniture, which are not objects: per point from its position, with the
    per-object random replaced by a second smooth noise field (wavelength CELL m), so the fade forms irregular patches
    instead of squares."""
    u = 0.5 + 0.5 * noise(x, n, CELL, seed=11)
    return ratio(x, n, u)


def point_u(X, Y, Z):
    """Per-point uniform [0, 1) from the raw coordinates (deterministic)."""
    h = (X.astype(np.int64) * 73856093) ^ (Y.astype(np.int64) * 19349663) ^ (Z.astype(np.int64) * 83492791)
    h = (h ^ (h >> 13)) * 0x5bd1e995
    return ((h ^ (h >> 15)) & 0xFFFFFF) / float(0x1000000)


def estimate():
    alias, final = plan()
    tot = cells = 0
    for c in chunks():
        z = np.load(STAGE / f"{c['file'][:-4]}.npz", allow_pickle=True)
        names = z["names"]; cellk = np.isin(names, CELL_KINDS)[z["name"]]
        x, n = z["X"][cellk] * 0.01 - OX, z["Y"][cellk] * 0.01 - OY
        cells += float(cell_ratio(x, n).sum())
    tot = cells + sum(f["n"] * f["r"] for f in final.values())
    print(f"terrain / other cells ~{cells / 1e6:.1f}M points; total ~{tot / 1e6:.1f}M points")


# ---------------------------------------------------------------- pack
def pack():
    alias, final = plan()
    kept = {k: [] for k in ("X", "Y", "Z", "cls", "inten", "segc", "hag", "obj")}
    names_out = ["_other"]; layers_out = ["_other"]; index = {"_other": 0}
    for c in chunks():
        nm = c["file"][:-4]
        z = load_chunk(nm)
        names, layers = z["names"], z["layers"]
        # final name / layer / ratio per local name index
        loc_final, loc_r = [], np.zeros(len(names))
        for k, s in enumerate(names):
            t = s
            while t in alias:
                t = alias[t]
            loc_final.append(t)
            if t in SPLITS:
                t0 = f"{t}~0"
                loc_r[k] = final[t0]["r"]
            else:
                loc_r[k] = final[t]["r"] if t in final else -1      # -1: cell-thinned kinds
        X, Y = z["X"], z["Y"]
        x, n = X * 0.01 - OX, Y * 0.01 - OY
        r = loc_r[z["name"]]
        cellp = r < 0
        r[cellp] = cell_ratio(x[cellp], n[cellp])
        keep = point_u(X, Y, z["Z"]) < r
        # object index in the output table
        loc_out = np.zeros(len(names), dtype=np.int32)
        lay_of = np.zeros(len(names), dtype=np.int64); lay_of[z["name"]] = z["layer"]
        def out_index(t, k):
            out_name = final[t]["name"] if t in final else t
            if out_name not in index:
                lay = final[t]["layer"] if t in final else str(layers[lay_of[k]])   # final layer (relabels)
                index[out_name] = len(names_out); names_out.append(out_name); layers_out.append(lay)
            return index[out_name]
        for k, t in enumerate(loc_final):
            loc_out[k] = out_index(t, k) if t not in SPLITS else 0
        obj = loc_out[z["name"]]
        # split objects: each point to the nearest part centre
        for k, t in enumerate(loc_final):
            if t in SPLITS:
                m = z["name"] == k
                if not m.any():
                    continue
                cs = SPLITS[t]
                part = np.argmin((x[m, None] - cs[None, :, 0]) ** 2 + (n[m, None] - cs[None, :, 1]) ** 2, axis=1)
                ids = np.array([out_index(f"{t}~{i}", k) for i in range(len(cs))], dtype=np.int32)
                obj[m] = ids[part]
        for key_, arr in (("X", X), ("Y", Y), ("Z", z["Z"]), ("cls", z["cls"]), ("inten", z["inten"]),
                          ("segc", z["segc"]), ("hag", z["hag"]), ("obj", obj)):
            kept[key_].append(arr[keep])
        print(f"{nm}: kept {keep.sum():,} of {len(keep):,}", flush=True)
    K = {k: np.concatenate(v) for k, v in kept.items()}
    n = len(K["X"])
    # drop names that kept no point, keep "_other" first
    used = np.unique(K["obj"])
    remap = np.full(len(names_out), -1, dtype=np.int64); remap[used] = np.arange(len(used))
    names_out = [names_out[i] for i in used]; layers_out = [layers_out[i] for i in used]
    obj = remap[K["obj"]]
    big = len(names_out) > 65535
    it = K["inten"].astype(float)
    it = np.clip(it / np.percentile(it, 99) * 255, 0, 255).astype(np.uint16)
    x, y, zz = K["X"] * 0.01 - OX, K["Y"] * 0.01 - OY, K["Z"] * 0.01
    hdr = laspy.LasHeader(point_format=0, version="1.2")
    hdr.scales = np.array([0.01, 0.01, 0.01]); hdr.offsets = np.array([0.0, 0.0, 0.0])
    otype = np.uint32 if big else np.uint16
    hdr.add_extra_dims([laspy.ExtraBytesParams(name="object", type=otype),
                        laspy.ExtraBytesParams(name="segment", type=np.uint8),
                        laspy.ExtraBytesParams(name="hag", type=np.int16)])
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = x, y, zz
    las.intensity, las.classification = it, K["cls"]
    las.object, las.segment, las.hag = obj.astype(otype), K["segc"], K["hag"]
    OUT.mkdir(parents=True, exist_ok=True)
    las.write(OUT / "lidar_points.laz")
    ob = 4 if big else 2
    meta = {
        "format": "laz", "file": "lidar_points.laz", "count": int(n), "stride": 1, "frame": "local",
        "origin_utm": [OX, OY], "z_range": [float(zz.min()), float(zz.max())], "point_format": 0, "point_length": 20 + ob + 3,
        "extra_bytes": {"object": {"offset": 20, "type": "uint32" if big else "uint16"},
                        "segment": {"offset": 20 + ob, "type": "uint8"},
                        "hag": {"offset": 21 + ob, "type": "int16", "scale": 0.1, "unit": "m"}},
        "attributes": {
            "object": {"type": "uint32" if big else "uint16", "names": names_out, "layers": layers_out,
                       "source": "Houdini (site-model/houdini/y1_lidar.hipnc), labelled in 37 chunks of 500 m "
                                 "(tools/split_chunks.py, merge in tools/pack_wide.py)"},
            "segment": {"type": "uint8", "names": SEGMENTS, "source": "Houdini point segmentation"},
            "hag": {"type": "int16", "scale": 0.1, "unit": "m", "source": "height above the Houdini ground heightfield"}},
        "thinning": {"full_density_radius_m": R0, "falloff_power": P, "density": DENSITY, "density_inside_too": DENSITY_INSIDE, "per_object": True, "ground_noise_m": CELL,
                     "keep_min": KEEP_MIN, "mist": MIST, "mist_end_m": MIST_END, "edge_end_m": EDGE_END, "note": f"Every return within {R0:.0f} m of Y-1; farther out each object (building, "
                     "tree, car ...) keeps one share of its points, falling off with distance with a random, irregular edge, "
                     "then a faint mist that fades out itself."},
        "source": "USGS 3DEP CA_LosAngeles_B23 (2023), 9 tiles 11SLT0383-0385 / 3767-3769, public domain; labels by Houdini;"
                  " LAZ (LAS 1.2 format 0 + extra bytes), local frame, 1 cm",
    }
    (OUT / "lidar_points.json").write_text(json.dumps(meta, indent=1))
    print(f"{n:,} points, {len(names_out):,} objects, LAZ {(OUT / 'lidar_points.laz').stat().st_size / 1e6:.1f} MB"
          f" (object field {'uint32' if big else 'uint16'})")


if __name__ == "__main__":
    # optional overrides for trials, e.g.  pack --r0 200 --power 3.3 --out out/data_trial
    args = sys.argv[2:]
    for flag, conv, glob_name in (("--r0", float, "R0"), ("--power", float, "P"), ("--keep-min", float, "KEEP_MIN"),
                                  ("--density", float, "DENSITY"),
                                  ("--mist", float, "MIST"), ("--mist-end", float, "MIST_END"),
                                  ("--edge-end", float, "EDGE_END")):
        if flag in args:
            globals()[glob_name] = conv(args[args.index(flag) + 1])
    if "--out" in args:
        OUT = HZ / args[args.index("--out") + 1]
    print(f"R0 {R0} m, power {P}, density {DENSITY}{' (centre too)' if DENSITY_INSIDE else ''}, keep_min {KEEP_MIN},"
          f" edge {EDGE_END} m, mist {MIST}, out {OUT}")
    {"stage": stage, "plan": estimate, "pack": pack}[sys.argv[1]]()
