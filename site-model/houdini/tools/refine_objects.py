"""Refine the object grouping of the chunked LiDAR labels (after pack_wide.py stage, before plan / pack).

  python site-model/houdini/tools/refine_objects.py trees [--depth 1.0] [--report]
  python site-model/houdini/tools/refine_objects.py shrubs [--gap 0.5]
  python site-model/houdini/tools/refine_objects.py vehicles      (fragments joined, merged cars split)
  python site-model/houdini/tools/refine_objects.py other         (unassigned points -> their building / tree)

Writes work/stage/refine_alias.json ({dropped name: kept name}); pack_wide.py plan reads it and joins those objects,
the same way it joins seam splits.

Trees (user, 2026-10-08: "group everything that belongs together"): the Houdini tree segmentation makes every local top
(highest point within 1.5-4 m) a tree, so one wide crown with two bumps, or a side branch, becomes two or more trees.
Two touching trees are one crown when the canopy between their tops hardly dips: from the lower top down to the highest
point where the two canopies meet (the saddle, on a 1 m grid of each tree's highest point) is small, and the lower top
lies within the higher tree's plausible crown: dip < DEPTH m and plan distance <= max(REACH x its height, 3 m), or an
almost flat join (dip < FLAT m) and distance <= max(REACH_FLAT x height, 3 m) (wide crowns: user saw big trees still
split at 0.35 x height, 2026-10-08), measured from
the top of the tree it would join after earlier joins (so a row of touching street trees does not chain into one). Tiny pieces
(< TINY points) join the touching tree they share the highest saddle with, whatever the dip.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_wide import STAGE, OX, OY, chunks  # noqa: E402

DEPTH, REACH, FLAT, REACH_FLAT, TINY, CELL = 1.0, 0.45, 0.6, 0.75, 15, 1.0


def tree_points():
    """All tree points of all chunks: x, n (local m), z (m), hag (m), global tree id; and the tree names."""
    xs, ns, zs, hs, ids, names = [], [], [], [], [], {}
    for c in chunks():
        z = np.load(STAGE / f"{c['file'][:-4]}.npz", allow_pickle=True)
        nm = z["names"]
        is_tree = np.array([s.startswith("Tree_") for s in nm])
        m = is_tree[z["name"]]
        loc = np.full(len(nm), -1, dtype=np.int64)
        for k in np.nonzero(is_tree)[0]:
            loc[k] = names.setdefault(nm[k], len(names))
        xs.append(z["X"][m] * 0.01 - OX); ns.append(z["Y"][m] * 0.01 - OY); zs.append(z["Z"][m] * 0.01)
        hs.append(z["hag"][m] * 0.1); ids.append(loc[z["name"][m]])
    names = sorted(names, key=names.get)
    return (np.concatenate(xs), np.concatenate(ns), np.concatenate(zs), np.concatenate(hs), np.concatenate(ids), names)


def trees(depth=DEPTH, report=False):
    x, n, z, hag, tid, names = tree_points()
    T = len(names)
    print(f"{len(x):,} tree points, {T:,} trees")
    cnt0 = np.bincount(tid, minlength=T)
    gi, gj = np.floor(x / CELL).astype(np.int64), np.floor(n / CELL).astype(np.int64)
    par = np.arange(T)

    def find(k):
        while par[k] != k:
            par[k] = par[par[k]]; k = par[k]
        return k
    # several passes on the current groups (2026-10-08: one pass with one partner per piece left crowns split): each pass
    # measures the groups' tops and saddles afresh, and a piece tries all its touching partners, highest saddle first
    for it in range(8):
        g = np.array([find(k) for k in range(T)])[tid]                 # current group (root tree index) per point
        cnt = np.bincount(g, minlength=T)
        o = np.lexsort((z, g)); last = np.r_[np.nonzero(np.diff(g[o]))[0], len(o) - 1]
        top = o[last]
        tx, tn, tz, th = np.zeros(T), np.zeros(T), np.full(T, -1e9), np.zeros(T)
        tx[g[top]], tn[g[top]], tz[g[top]], th[g[top]] = x[top], n[top], z[top], hag[top]
        # canopy grid: highest point of each group in each 1 m cell; saddle of every touching pair = max over
        # neighbouring cells (incl. the same cell) of min(hA, hB)
        df = pd.DataFrame({"i": gi, "j": gj, "t": g, "h": z}).groupby(["i", "j", "t"], as_index=False)["h"].max()
        parts = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                sh = df.rename(columns={"t": "u", "h": "g"}).assign(i=df.i + di, j=df.j + dj)
                m = df.merge(sh, on=["i", "j"])
                m = m[m.t < m.u]
                parts.append(pd.DataFrame({"a": m.t.values, "b": m.u.values, "s": np.minimum(m.h.values, m.g.values)}))
        pr = pd.concat(parts).groupby(["a", "b"], as_index=False)["s"].max()
        a, b, sd = pr.a.values, pr.b.values, pr.s.values
        hi = np.where(tz[a] >= tz[b], a, b); lo = np.where(tz[a] >= tz[b], b, a)     # higher / lower top
        dip = tz[lo] - sd
        dist = np.hypot(tx[hi] - tx[lo], tn[hi] - tn[lo])
        f = np.where(dip < FLAT, REACH_FLAT, REACH)                    # reach factor of this pair
        one_crown = (dip < depth) & (dist <= np.maximum(f * th[hi], 3.0))
        ok = one_crown | (cnt[lo] < TINY)
        cand = pd.DataFrame({"lo": lo[ok], "hi": hi[ok], "s": sd[ok], "f": f[ok]}).sort_values("s", ascending=False)
        joined = 0
        for l, h, fk in zip(cand.lo.values, cand.hi.values, cand.f.values):
            rl, rh = find(l), find(h)
            if rl == rh:
                continue
            if tz[rl] > tz[rh]:
                rl, rh = rh, rl
            # the lower group's top must lie within the crown of the group it joins (tiny pieces always join);
            # the root is always the highest top, so tx / tn / th of a root stay that group's top
            if cnt[rl] >= TINY and np.hypot(tx[rl] - tx[rh], tn[rl] - tn[rh]) > max(fk * th[rh], 3.0):
                continue
            par[rl] = rh; cnt[rh] += cnt[rl]; joined += 1
        print(f"  pass {it + 1}: touching pairs {len(pr):,}, joined {joined:,}")
        if joined == 0:
            break
    roots = np.array([find(k) for k in range(T)])
    alias = {names[k]: names[roots[k]] for k in range(T) if roots[k] != k}
    after = len(set(roots.tolist()))
    print(f"{len(alias):,} trees joined, {T:,} -> {after:,} trees")
    cnt = cnt0
    # original tops for the report
    o = np.lexsort((z, tid)); last = np.r_[np.nonzero(np.diff(tid[o]))[0], len(o) - 1]; top = o[last]
    tx, tn, th = np.zeros(T), np.zeros(T), np.zeros(T)
    tx[tid[top]], tn[tid[top]], th[tid[top]] = x[top], n[top], hag[top]
    d0 = np.hypot(tx, tn)
    core = d0 < 250
    print(f"  within 250 m of Y-1: {core.sum():,} -> {len(set(roots[core].tolist())):,} trees;"
          f" small (< 60 pts) {np.sum(core & (cnt < 60)):,} -> "
          f"{np.sum([cnt[roots == r].sum() < 60 for r in set(roots[core].tolist())]):,}")
    if report:
        groups = pd.Series(roots).value_counts()
        print("  largest joins (parts, name, height m):")
        for r, k in groups.head(10).items():
            print(f"    {k:3d}  {names[r]}  {th[r]:.1f}")
    path = STAGE / "refine_alias.json"
    old = json.load(open(path)) if path.exists() else {}
    old = {k: v for k, v in old.items() if not k.startswith("Tree_")}
    old.update(alias)
    json.dump(old, open(path, "w"), indent=0)
    print(f"-> {path} ({len(old):,} aliases)")


def kind_points(prefix):
    """All points of the objects whose name starts with prefix: x, n (local m), global object id; and the names."""
    xs, ns, ids, names = [], [], [], {}
    for c in chunks():
        z = np.load(STAGE / f"{c['file'][:-4]}.npz", allow_pickle=True)
        nm = z["names"]
        hit = np.array([s.startswith(prefix) for s in nm])
        m = hit[z["name"]]
        loc = np.full(len(nm), -1, dtype=np.int64)
        for k in np.nonzero(hit)[0]:
            loc[k] = names.setdefault(nm[k], len(names))
        xs.append(z["X"][m] * 0.01 - OX); ns.append(z["Y"][m] * 0.01 - OY); ids.append(loc[z["name"][m]])
    return np.concatenate(xs), np.concatenate(ns), np.concatenate(ids), sorted(names, key=names.get)


def patches(prefix, gap=0.5, cell=0.5):
    """Shrubs (user, 2026-10-08): the low-vegetation clustering leaves one hedge or planting bed as many small objects.
    Objects of one kind whose points come within `gap` m of each other (plan, on a `cell` m grid) become one object,
    named after its largest part."""
    from scipy import ndimage
    x, n, oid, names = kind_points(prefix)
    # objects relabelled to another kind (refine_relabel.json, e.g. cars from car_sweep.py) stay out of the patches
    rp = STAGE / "refine_relabel.json"
    relabelled = {k for k in json.load(open(rp)) if not k.startswith("_")} if rp.exists() else set()
    keep = ~np.isin(np.array(names, dtype=object)[oid], list(relabelled))
    x, n, oid = x[keep], n[keep], oid[keep]
    T = len(names)
    gi = np.floor((x - x.min()) / cell).astype(np.int64); gj = np.floor((n - n.min()) / cell).astype(np.int64)
    occ = np.zeros((gi.max() + 1, gj.max() + 1), bool); occ[gi, gj] = True
    r = max(1, int(round(gap / cell)))
    lab, _ = ndimage.label(ndimage.binary_dilation(occ, np.ones((2 * r + 1, 2 * r + 1), bool)))
    comp = lab[gi, gj]
    cnt = np.bincount(oid, minlength=T)
    df = pd.DataFrame({"c": comp, "t": oid}).drop_duplicates()
    df["n"] = cnt[df.t.values]
    keep = df.sort_values("n", ascending=False).drop_duplicates("c").set_index("c")["t"]
    root = keep.loc[df.c.values].values
    alias = {names[t]: names[k] for t, k in zip(df.t.values, root) if t != k}
    cx = np.bincount(oid, x, T) / np.maximum(cnt, 1); cn = np.bincount(oid, n, T) / np.maximum(cnt, 1)
    core = np.nonzero((np.hypot(cx, cn) < 250) & (cnt > 0))[0]
    print(f"{prefix}: {len(x):,} points, {T:,} objects -> {T - len(alias):,} (gap {gap} m);"
          f" within 250 m: {len(core):,} -> {len({alias.get(names[k], names[k]) for k in core}):,}")
    path = STAGE / "refine_alias.json"
    old = json.load(open(path)) if path.exists() else {}
    old = {k: v for k, v in old.items() if not k.startswith(prefix)}
    old.update(alias)
    json.dump(old, open(path, "w"), indent=0)
    print(f"-> {path} ({len(old):,} aliases)")


CAR_L, CAR_W, TALL, FRAG_N, FRAG_L = 4.8, 2.2, 2.6, 20, 2.0


def vehicles(gap=0.6, cell=0.3):
    """Vehicles (user, 2026-10-08). Two fixes:
    * fragments (< FRAG_N points or shorter than FRAG_L m) join the largest vehicle within `gap` m, if the joined car is
      not longer than 6 m (alias, as for trees and shrubs);
    * cars parked nose to tail or side by side that came out as one vehicle are split: an object lower than TALL m
      (buses, trucks and vans are taller and stay whole) whose plan footprint (principal axes) holds round(L / CAR_L) x
      round(W / CAR_W) >= 2 cars gets that many part centres (a grid along its axes, then 10 Lloyd steps);
      pack_wide.py gives each point to the nearest centre (work/stage/refine_split.json)."""
    from scipy import ndimage
    xs, ns, hs, ids, names = [], [], [], [], {}
    for c in chunks():
        z = np.load(STAGE / f"{c['file'][:-4]}.npz", allow_pickle=True)
        nm = z["names"]
        hit = np.array([s.startswith("Vehicle_") for s in nm]); m = hit[z["name"]]
        loc = np.full(len(nm), -1, dtype=np.int64)
        for k in np.nonzero(hit)[0]:
            loc[k] = names.setdefault(nm[k], len(names))
        xs.append(z["X"][m] * 0.01 - OX); ns.append(z["Y"][m] * 0.01 - OY); hs.append(z["hag"][m] * 0.1)
        ids.append(loc[z["name"][m]])
    x, n, h, oid = map(np.concatenate, (xs, ns, hs, ids)); names = sorted(names, key=names.get); T = len(names)

    def shape(i):
        P = np.c_[x[i], n[i]]; c = P.mean(0)
        if len(i) < 3:
            return c, np.eye(2), 0.0, 0.0
        _, _, vt = np.linalg.svd(P - c, full_matrices=False); q = (P - c) @ vt.T
        return c, vt, float(np.ptp(q[:, 0])), float(np.ptp(q[:, 1]))
    o = np.argsort(oid, kind="stable"); b = np.searchsorted(oid[o], np.arange(T)); e = np.searchsorted(oid[o], np.arange(T), "right")
    cnt = e - b
    L = np.array([shape(o[b[k]:e[k]])[2] for k in range(T)])
    frag = (cnt < FRAG_N) | (L < FRAG_L)
    # touching vehicles (points within gap, on a cell grid)
    gi = np.floor((x - x.min()) / cell).astype(np.int64); gj = np.floor((n - n.min()) / cell).astype(np.int64)
    r = max(1, int(round(gap / cell)))
    df = pd.DataFrame({"i": gi, "j": gj, "t": oid}).drop_duplicates()
    pairs = []
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            m = df.merge(df.assign(i=df.i + di, j=df.j + dj).rename(columns={"t": "u"}), on=["i", "j"])
            m = m[m.t != m.u]
            pairs.append(m[["t", "u"]])
    pr = pd.concat(pairs).drop_duplicates()
    alias = {}
    for t in np.nonzero(frag)[0]:
        nb = pr.u[pr.t == t].values
        nb = [u for u in nb if not frag[u]]
        if not nb:
            continue
        u = max(nb, key=lambda u: cnt[u])
        i = np.r_[o[b[t]:e[t]], o[b[u]:e[u]]]
        if shape(i)[2] <= 6.0:
            alias[names[t]] = names[u]
    # splits, on the groups after the fragment joins
    grp = {}
    for k in range(T):
        grp.setdefault(alias.get(names[k], names[k]), []).append(k)
    split = {}
    for root_name, ks in grp.items():
        i = np.concatenate([o[b[k]:e[k]] for k in ks])
        if len(i) < 40 or np.percentile(h[i], 95) >= TALL:
            continue
        c, vt, l, w = shape(i)
        nl, nw = max(1, int(round(l / CAR_L))), max(1, int(round(w / CAR_W)))
        if nl * nw < 2:
            continue
        P = np.c_[x[i], n[i]]
        q = (P - c) @ vt.T
        lo0, hi0, lo1, hi1 = q[:, 0].min(), q[:, 0].max(), q[:, 1].min(), q[:, 1].max()
        g0 = lo0 + (np.arange(nl) + 0.5) * (hi0 - lo0) / nl; g1 = lo1 + (np.arange(nw) + 0.5) * (hi1 - lo1) / nw
        C = np.array([[a, bb] for a in g0 for bb in g1]) @ vt + c
        for _ in range(10):
            lab = np.argmin(((P[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
            C = np.array([P[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(len(C))])
        split[root_name] = [[round(float(a), 2), round(float(bb), 2)] for a, bb in C]
    cx = np.bincount(oid, x, T) / np.maximum(cnt, 1); cn = np.bincount(oid, n, T) / np.maximum(cnt, 1)
    core = np.hypot(cx, cn) < 250
    cs = {names[k] for k in np.nonzero(core)[0]}
    print(f"vehicles {T:,}: fragments {frag.sum():,}, joined {len(alias):,}; split {len(split):,} into"
          f" {sum(map(len, split.values())):,} cars; within 250 m: {core.sum():,} vehicles, joined"
          f" {sum(1 for k in alias if k in cs):,}, split {sum(1 for k in split if k in cs):,}")
    path = STAGE / "refine_alias.json"
    old = json.load(open(path)) if path.exists() else {}
    old = {k: v for k, v in old.items() if not k.startswith("Vehicle_")}
    old.update(alias)
    json.dump(old, open(path, "w"), indent=0)
    sp = STAGE / "refine_split.json"
    olds = json.load(open(sp)) if sp.exists() else {}
    olds = {k: v for k, v in olds.items() if not k.startswith("Vehicle_")}
    olds.update(split)
    json.dump(olds, open(sp, "w"), indent=0)
    print(f"-> {path} ({len(old):,} aliases), {sp} ({len(olds):,} splits)")


def other(r_near=1.5, h_min=2.0, r_outline=3.0, min_struct=150):
    """Unassigned points that belong to an existing object (user, 2026-10-09: "then the remaining unassigned points"):
      1. segment tree / podium_tree within r_near m of a tree point -> that tree (crown edges; first, so trees on
         podium decks inside an outline stay trees);
      2. inside a LARIAC outline and more than h_min m above ground -> that building (roof equipment, parapets, light
         wells, skylight frames - the Angelus Plaza skylight grid had been called podium_tree);
      3. Houdini segment building / unsure within r_near m (3D) of a building, structure or landmark point -> that object
         (balconies, canopies, facade parts outside the outline);
      4. segment building / unsure, above h_min, within r_outline m (plan) of a LARIAC outline -> that building (sparse
         glass facades of towers, outlines a little off).
    The rest (street clutter: people, poles, signs, benches) stays _other. Writes work/stage/points/<chunk>__other.npz,
    applied by pack_wide.load_chunk after the car / truck relabels (run car_sweep.py apply first)."""
    from scipy.spatial import cKDTree
    from shapely import points
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    from pack_wide import SEGMENTS, load_chunk
    HZ = STAGE.parent.parent
    feats = json.load(open(HZ / "in" / "lariac_3km.geojson"))["features"]
    fp_names = ["BLD_" + str(f["properties"]["BLD_ID"]) for f in feats]
    tree = STRtree([shape(f["geometry"]).buffer(0) for f in feats])
    (STAGE / "points").mkdir(exist_ok=True)
    tot = np.zeros(5, int)
    for c in chunks():
        nm_ = c["file"][:-4]
        out = STAGE / "points" / f"{nm_}__other.npz"
        if out.exists():
            out.unlink()
        z = load_chunk(nm_)                      # with the car / truck relabels applied
        names = z["names"]; ni = z["name"]
        x = z["X"] * 0.01 - OX; n = z["Y"] * 0.01 - OY; Z = z["Z"] * 0.01; h = z["hag"] * 0.1
        kind = np.array([str(s).split("_")[0] for s in names])[ni]
        lay_of = np.asarray(z["layers"], dtype=object)[z["layer"]]
        idx = np.nonzero(np.isin(names, ["_other", ""])[ni])[0]
        if not len(idx):
            continue
        new_name = np.full(len(idx), None, dtype=object); new_layer = np.full(len(idx), None, dtype=object)
        seg = z["segc"][idx]
        P = np.c_[x, n, Z]
        def nearest(mask):
            k = np.nonzero(mask)[0]
            if not len(k):
                return np.full(len(idx), np.inf), np.zeros(len(idx), int)
            d, j = cKDTree(P[k]).query(P[idx], distance_upper_bound=r_near)
            return d, k[np.minimum(j, len(k) - 1)]
        free = lambda: new_name == None  # noqa: E711
        # 1. crown edges next to a tree (first, so trees on podium decks inside an outline stay trees)
        dt, jt = nearest(kind == "Tree")
        r3 = free() & np.isin(seg, [SEGMENTS.index("tree"), SEGMENTS.index("podium_tree")]) & np.isfinite(dt)
        new_name[r3] = names[ni[jt[r3]]]; new_layer[r3] = "Trees"
        # 2. inside a building outline (roof equipment, parapets, light wells, skylight frames)
        hit = tree.query(points(x[idx] + OX, n[idx] + OY), predicate="within")
        r1 = np.zeros(len(idx), bool)
        for pi, fi in zip(*hit):
            if h[idx[pi]] > h_min and new_name[pi] is None:
                new_name[pi] = fp_names[fi]; new_layer[pi] = "Buildings"; r1[pi] = True
        # 3. facade parts next to a building / structure / landmark point
        db, jb = nearest(np.isin(kind, ["BLD", "PC", "AF", "MOCA", "Metro"]))
        bseg = np.isin(seg, [SEGMENTS.index("building"), SEGMENTS.index("unsure")])
        r2 = free() & bseg & np.isfinite(db)
        new_name[r2] = names[ni[jb[r2]]]; new_layer[r2] = lay_of[jb[r2]]
        # 4. building surfaces within r_outline m (plan) of an outline: sparse glass facades, towers whose outline is off
        rest = np.nonzero(free() & bseg & (h[idx] > h_min))[0]
        if len(rest):
            hit = tree.query(points(x[idx[rest]] + OX, n[idx[rest]] + OY), predicate="dwithin", distance=r_outline)
            for pi, fi in zip(*hit):
                q = rest[pi]
                if new_name[q] is None:
                    new_name[q] = fp_names[fi]; new_layer[q] = "Buildings"; r2[q] = True
        # 5. what is left of the building surfaces, clustered (1 m grid): a cluster of >= min_struct points becomes a new
        #    LiDAR-only structure PC_<x>_<z> (m) - low links and podium wings between towers, plaza canopies and terraces
        #    that LARIAC has no outline for (user, 2026-10-09)
        from scipy import ndimage
        rest = np.nonzero(free() & bseg & (h[idx] > h_min))[0]
        r5 = np.zeros(len(idx), bool)
        if len(rest) >= min_struct:
            xr, nr = x[idx[rest]], n[idx[rest]]
            gi = np.floor(xr - xr.min()).astype(int); gj = np.floor(nr - nr.min()).astype(int)
            g = np.zeros((gi.max() + 1, gj.max() + 1), bool); g[gi, gj] = True
            lab, nl = ndimage.label(g, np.ones((3, 3), bool)); cl = lab[gi, gj]
            for c in np.nonzero(np.bincount(cl) >= min_struct)[0]:
                if c == 0:
                    continue
                q = rest[cl == c]
                nmq = f"PC_{int(round(x[idx[q]].mean()))}_{int(round(-n[idx[q]].mean()))}"
                new_name[q] = nmq; new_layer[q] = "Buildings_LiDAR_only"; r5[q] = True
        k = new_name != None  # noqa: E711
        if k.any():
            np.savez(out, idx=idx[k], name=new_name[k], layer=new_layer[k])
        tot += [len(idx), r1.sum(), r2.sum(), r3.sum(), r5.sum()]
        print(f"{nm_}: {k.sum():,} of {len(idx):,} unassigned points placed", flush=True)
    print(f"unassigned {tot[0]:,}: inside outlines {tot[1]:,}, next to buildings {tot[2]:,}, next to trees {tot[3]:,},"
          f" new structures {tot[4]:,}; left {tot[0] - tot[1:].sum():,}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "trees":
        d = float(args[args.index("--depth") + 1]) if "--depth" in args else DEPTH
        trees(d, "--report" in args)
    elif args and args[0] == "other":
        other()
    elif args and args[0] == "shrubs":
        patches("Shrub_", float(args[args.index("--gap") + 1]) if "--gap" in args else 0.5)
    elif args and args[0] == "vehicles":
        vehicles()
    else:
        print(__doc__)
