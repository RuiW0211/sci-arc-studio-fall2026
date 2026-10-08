"""Merge the per-chunk Houdini labels (work/labels/c_<i>_<j>.geo, written by /obj/lidar/chunk_write) with the chunk LAZ files
(work/chunks/, from split_chunks.py) into one labelled point table, and run consistency checks.

Each label file holds the core points of one chunk with i@ptsrc (row in the chunk LAZ), s@lname, s@llayer, i@segc,
i@hagdm. Object names from the chunks are position based ("Tree_<x>_<z>" decimetres, "Vehicle_...", "PC_<x>_<z>" metres),
so an object seen by two chunks has one name; they are renumbered here (Tree_0001 ... by distance from Y-1).

  python site-model/houdini/tools/merge_chunks.py check c_0_0 [c_2_2 ...]   per-chunk checks (+ c_0_0 against the 800 m run)
"""
import json
import sys
from pathlib import Path

import laspy
import numpy as np

HZ = Path(__file__).resolve().parent.parent
WORK = HZ / "work"
OX, OY = 384580, 3768520


def geo_attribs(path):
    """Houdini ASCII .geo (JSON) -> {name: array}; strings as (list of strings, index array)."""
    g = json.load(open(path))
    d = dict(zip(g[0::2], g[1::2]))
    att = dict(zip(d["attributes"][0::2], d["attributes"][1::2]))
    out = {}
    for meta, body in att["pointattributes"]:
        meta = dict(zip(meta[0::2], meta[1::2]))
        body = dict(zip(body[0::2], body[1::2]))
        if meta["type"] == "string":
            idx = body["indices"]
            idx = idx["arrays"][0] if isinstance(idx, dict) else dict(zip(idx[0::2], idx[1::2]))["arrays"][0]
            out[meta["name"]] = (body["strings"], np.asarray(idx))
            continue
        vals = dict(zip(body["values"][0::2], body["values"][1::2]))
        out[meta["name"]] = np.asarray(vals["tuples"] if "tuples" in vals else vals["arrays"][0])
    return out, d["pointcount"]


def strings(entry):
    s, i = entry
    return np.asarray(s, dtype=object)[i]


def load_chunk(name):
    A, n = geo_attribs(WORK / "labels" / f"{name}.geo")
    las = laspy.read(WORK / "chunks" / f"{name}.laz")
    src = A["ptsrc"].astype(np.int64)
    return {
        "X": np.asarray(las.X)[src], "Y": np.asarray(las.Y)[src], "Z": np.asarray(las.Z)[src],
        "cls": np.asarray(las.classification)[src], "lname": strings(A["lname"]), "llayer": strings(A["llayer"]),
        "segc": A["segc"].astype(int), "n_laz": len(las), "n": n, "src": src,
    }


def key(X, Y, Z):
    return ((X.astype(np.int64) - 38_300_000) << 34) | ((Y.astype(np.int64) - 376_700_000) << 17) | (Z.astype(np.int64) + 20000)


def check(name):
    c = load_chunk(name)
    meta = {m["file"][:-4]: m for m in json.load(open(WORK / "chunks" / "chunks.json"))["chunks"]}[name]
    cx, cz, h = meta["center"][0], meta["center"][1], meta["half"]
    las = laspy.read(WORK / "chunks" / f"{name}.laz")
    x, z = np.asarray(las.x) - OX, -(np.asarray(las.y) - OY)
    cl = np.asarray(las.classification)
    core = (x - cx >= -h) & (x - cx < h) & (z - cz >= -h) & (z - cz < h) & ~np.isin(cl, (7, 18))
    print(f"{name}: {c['n']:,} labelled core points, numpy core {core.sum():,} (LAZ {c['n_laz']:,});"
          f" duplicates in ptsrc {len(c['src']) - len(np.unique(c['src']))}, ptsrc outside numpy core {(~core[c['src']]).sum()}")
    lay, cnt = np.unique(c["llayer"], return_counts=True)
    print("  layers:", ", ".join(f"{l} {k:,}" for l, k in zip(lay, cnt)))
    if name == "c_0_0":
        compare_800(c)


def compare_800(c):
    """The centre chunk against the 800 m run (out/lidar_full_labels.geo, centre tile in its order): same points, labels."""
    A, n = geo_attribs(HZ / "out" / "lidar_full_labels.geo")
    las = laspy.read(HZ.parent / "data" / "lidar" / "USGS_LPC_CA_LosAngeles_B23_11SLT038400376800.laz")
    x, y = np.asarray(las.x) - OX, np.asarray(las.y) - OY
    m = (np.abs(x) <= 400) & (np.abs(y) <= 400) & ~np.isin(np.asarray(las.classification), (7, 18))
    idx = np.nonzero(m)[0]
    assert len(idx) == n
    ko = key(np.asarray(las.X)[idx], np.asarray(las.Y)[idx], np.asarray(las.Z)[idx])
    kn = key(c["X"], c["Y"], c["Z"])
    uo, io, co = np.unique(ko, return_index=True, return_counts=True)
    single = uo[co == 1]
    sel = np.isin(kn, single)
    pos = np.searchsorted(uo, kn[sel])
    oi = io[pos]
    old_layer, old_name = strings(A["llayer"])[oi], strings(A["lname"])[oi]
    old_seg = A["segc"].astype(int)[oi]
    new_layer, new_name, new_seg = c["llayer"][sel], c["lname"][sel], c["segc"][sel]
    print(f"  vs 800 m run: {sel.sum():,} points matched by raw XYZ; same layer {np.mean(old_layer == new_layer):.2%},"
          f" same segment {np.mean(old_seg == new_seg):.2%}")
    # object grouping: for each old object, share of its points that sit in its most common new object
    pairs = {}
    for o, nn in zip(old_name, new_name):
        pairs.setdefault(o, {}).setdefault(nn, 0)
        pairs[o][nn] += 1
    agree = sum(max(v.values()) for k, v in pairs.items() if k != "_other")
    tot = sum(sum(v.values()) for k, v in pairs.items() if k != "_other")
    print(f"  object grouping kept for {agree / tot:.2%} of the points in named objects")
    lays = sorted(set(old_layer) | set(new_layer))
    print("  rows = 800 m run, columns = chunk (thousand points, changed only):")
    for a in lays:
        row = [(b, np.sum((old_layer == a) & (new_layer == b))) for b in lays if b != a]
        row = [f"{b} {v / 1000:.1f}k" for b, v in row if v >= 200]
        if row:
            print(f"    {a}: " + ", ".join(row))


def seams(show=15):
    """Objects across chunk borders: for every pair of neighbouring chunks, take the named objects (trees, vehicles, shrubs,
    walls, PC) with points within 1 m of the shared border on one side and look for points within 1 m on the other side
    that are within 1.5 m of them. Such a touching object should carry the same name on both sides."""
    from scipy.spatial import cKDTree
    meta = json.load(open(WORK / "chunks" / "chunks.json"))["chunks"]
    have = {m["file"][:-4]: m for m in meta if (WORK / "labels" / f"{m['file'][:-4]}.geo").exists()}
    cache = {}

    def side(name):
        # only the 1 m strip along the core edges is kept, so all chunks fit in memory
        if name not in cache:
            c = load_chunk(name)
            x, z = c["X"] * 0.01 - OX, -(c["Y"] * 0.01 - OY)
            m = have[name]; cx, cz, h = m["center"][0], m["center"][1], m["half"]
            keep = (np.abs(x - cx) > h - 1) | (np.abs(z - cz) > h - 1)
            cache[name] = (x[keep], z[keep], (c["Z"] * 0.01)[keep], c["lname"][keep])
        return cache[name]

    tot, same, broken = 0, 0, []
    for a, ma in have.items():
        for b, mb in have.items():
            di, dj = mb["i"] - ma["i"], mb["j"] - ma["j"]
            if (di, dj) not in ((1, 0), (0, 1)):
                continue
            xa, za, ya, na = side(a)
            xb, zb, yb, nb = side(b)
            if di == 1:   # b is east of a: border x = a's core edge
                edge = ma["center"][0] + ma["half"]; da, db = edge - xa, xb - edge
            else:         # b is north of a: north = -z, border at z = a's centre z - half
                edge = ma["center"][1] - ma["half"]; da, db = za - edge, edge - zb
            sa, sb = (da >= 0) & (da < 1), (db >= 0) & (db < 1)
            named = lambda n: np.array([s.startswith(("Tree_", "Vehicle_", "Shrub_", "Wall_", "PC_")) for s in n])
            sa &= named(na); sb &= named(nb)
            if not sa.any() or not sb.any():
                continue
            ta = cKDTree(np.column_stack([xa[sa], ya[sa], za[sa]]))
            pb = np.column_stack([xb[sb], yb[sb], zb[sb]])
            d, k = ta.query(pb, distance_upper_bound=1.5)
            ok = np.isfinite(d)
            pa_names, pb_names = na[sa][k[ok]], nb[sb][ok]
            for o in sorted(set(pa_names)):
                m = pa_names == o
                tot += 1
                if np.any(pb_names[m] == o):
                    same += 1
                else:
                    vals, cnt = np.unique(pb_names[m], return_counts=True)
                    broken.append((a, b, o, vals[np.argmax(cnt)]))
    print(f"seams: {tot} objects touch a chunk border, {same} carry the same name on both sides ({same / max(tot, 1):.1%})")
    for br in broken[:show]:
        print("  differs:", br)


if __name__ == "__main__":
    if sys.argv[1] == "check":
        for nm in sys.argv[2:]:
            check(nm)
    elif sys.argv[1] == "seams":
        seams(10 ** 9 if "all" in sys.argv else 15)
