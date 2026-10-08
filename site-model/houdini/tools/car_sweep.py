"""Car sweep (user, 2026-10-07: "some car points are still shrub or something else - check carefully, at the end").

  python site-model/houdini/tools/car_sweep.py            -> work/stage/car_candidates.json, car_accepted.json (nothing is changed)
  python site-model/houdini/tools/car_sweep.py apply      -> the accepted cars become vehicles (relabel files, see apply())

Learns what a car looks like from the objects already labelled Vehicle_ (shape, height profile, roof flatness, return
intensity) against shrubs, small trees and walls, then scores every low object that is NOT a vehicle - Shrub_ objects, small
Tree_ objects (top below 5 m) and clusters of unassigned (_other) points 0.5-3.5 m above ground - and lists the ones
that look like cars. Out-of-fold predictions, so a mislabelled car in the training set is scored by a model that did
not see it. Review the candidates before relabelling anything.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_wide import STAGE, OX, OY, chunks  # noqa: E402


def features(x, n, h, it):
    """Shape features of one object: plan size on its principal axes, height profile, roof flatness, intensity."""
    P = np.c_[x, n]; c = P.mean(0)
    if len(P) >= 3:
        _, _, vt = np.linalg.svd(P - c, full_matrices=False); q = (P - c) @ vt.T
    else:
        q = np.zeros((len(P), 2))
    L, W = np.ptp(q[:, 0]), np.ptp(q[:, 1])
    cells = len(set(zip(np.floor(q[:, 0] / 0.5).astype(int), np.floor(q[:, 1] / 0.5).astype(int))))
    top = h >= np.percentile(h, 70)
    # car profile: the middle third (cabin) stands above both ends (bonnet, boot)
    # roofline = highest point in each 0.4 m slice along the length; cabin = middle 40 %, bonnet / boot = outer 20 %
    t = (q[:, 0] - q[:, 0].min()) / max(L, 0.1)
    sl = np.minimum((t * max(L, 0.1) / 0.4).astype(int), 999)
    roof = pd.Series(h).groupby(sl).max(); ts = (roof.index.values * 0.4 + 0.2) / max(L, 0.1)
    part = lambda m: np.median(roof.values[m]) if m.sum() else np.nan
    mid, e1, e2 = part((ts > 0.3) & (ts < 0.7)), part(ts <= 0.2), part(ts >= 0.8)
    bump = mid - np.nanmax([e1, e2]) if not (np.isnan(mid) or (np.isnan(e1) and np.isnan(e2))) else np.nan
    roof_frac = float(np.mean(h >= np.percentile(h, 95) - 0.3))   # share of points in the top 30 cm (hard roof: high)
    return dict(bump=bump, roof_frac=roof_frac, n=len(h), L=L, W=W, LW=L / max(W, 0.1), area=cells * 0.25, fill=cells * 0.25 / max(L * W, 0.25),
                h95=np.percentile(h, 95), h50=np.median(h), h05=np.percentile(h, 5), hstd=h.std(),
                roof_std=h[top].std() if top.sum() > 2 else 0.0, dens=len(h) / max(cells * 0.25, 0.25),
                i_mean=it.mean(), i_std=it.std(), i_p90=np.percentile(it, 90), cx=c[0], cn=c[1])


CELL, H_LO, H_HI = 0.4, 0.7, 2.3


def split_cars(x, n, car_l=4.8, car_w=2.2, lloyd=True):
    """Labels 0..k-1 cutting a cluster bigger than one car (cars parked close together) into car-sized parts: as many
    parts as round(L / car_l) x round(W / car_w) on its principal axes, a grid start then 10 Lloyd steps (deterministic,
    the same in main() and apply()). One part when it is car-sized or too big to be a few cars."""
    P = np.c_[x, n]; c = P.mean(0)
    if len(P) < 30:
        return np.zeros(len(P), int)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False); q = (P - c) @ vt.T
    L, W = np.ptp(q[:, 0]), np.ptp(q[:, 1])
    nl, nw = max(1, int(round(L / car_l))), max(1, int(round(W / car_w)))
    if nl * nw < 2 or nl * nw > 12:
        return np.zeros(len(P), int)
    if not lloyd:   # plain grid on the principal axes (trucks side by side: Lloyd would cut them across their length)
        i0 = np.minimum(((q[:, 0] - q[:, 0].min()) / max(L, 1e-6) * nl).astype(int), nl - 1)
        i1 = np.minimum(((q[:, 1] - q[:, 1].min()) / max(W, 1e-6) * nw).astype(int), nw - 1)
        return i0 * nw + i1
    g0 = q[:, 0].min() + (np.arange(nl) + 0.5) * L / nl; g1 = q[:, 1].min() + (np.arange(nw) + 0.5) * W / nw
    C = np.array([[a, b] for a in g0 for b in g1])
    for _ in range(10):
        lab = np.argmin(((q[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
        C = np.array([q[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(len(C))])
    return np.argmin(((q[:, None, :] - C[None]) ** 2).sum(-1), axis=1)


def other_mask(names, ni, h):
    return np.isin(names, ["_other", ""])[ni] & (h > H_LO) & (h < H_HI)


def objects():
    rows = []
    for ch in chunks():
        nm_ = ch["file"][:-4]
        z = np.load(STAGE / f"{nm_}.npz", allow_pickle=True)
        names, ni = z["names"], z["name"]
        x = z["X"] * 0.01 - OX; n = z["Y"] * 0.01 - OY; h = z["hag"] * 0.1; it = z["inten"].astype(float)
        o = np.argsort(ni, kind="stable"); s = ni[o]
        b = np.searchsorted(s, np.arange(len(names))); e = np.searchsorted(s, np.arange(len(names)), "right")
        for k, nm in enumerate(names):
            kind = nm.split("_")[0]
            if kind not in ("Vehicle", "Shrub", "Tree", "Wall") or e[k] - b[k] < 15:
                continue
            idx = o[b[k]:e[k]]
            if kind == "Tree" and np.percentile(h[idx], 95) > 5:
                continue
            f = features(x[idx], n[idx], h[idx], it[idx]); f.update(name=nm, kind=kind, chunk=nm_)
            rows.append(f)
        # unassigned points at car-body height (0.7-2.3 m), connected on a 0.4 m grid: fine enough to keep cars
        # parked side by side apart, and to leave out signs, fences and kiosks above or below (2026-10-09: the first
        # 1 m grid over 0.5-3.5 m merged whole rows of cars into one cluster that no longer looked like a car)
        oth = other_mask(names, ni, h)
        if oth.sum() > 15:
            from scipy import ndimage
            xo, no, ho, io = x[oth], n[oth], h[oth], it[oth]
            gi = np.floor((xo - xo.min()) / CELL).astype(int); gj = np.floor((no - no.min()) / CELL).astype(int)
            g = np.zeros((gi.max() + 1, gj.max() + 1), bool); g[gi, gj] = True
            lab, nl = ndimage.label(g, np.ones((3, 3), bool))
            cl = lab[gi, gj]
            for c in range(1, nl + 1):
                mi = np.nonzero(cl == c)[0]
                if len(mi) < 15:
                    continue
                parts = split_cars(xo[mi], no[mi])          # cars parked close together: one part per car
                for k in range(parts.max() + 1):
                    m = mi[parts == k]
                    if len(m) < 15:
                        continue
                    f = features(xo[m], no[m], ho[m], io[m]); f.update(name=f"other@{nm_}#{c}.{k}", kind="other", chunk=nm_)
                    rows.append(f)
        print(f"{nm_}: {len(rows):,} objects so far", flush=True)
    return pd.DataFrame(rows)


def main():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import cross_val_predict
    df = objects()
    feats = ["n", "L", "W", "LW", "area", "fill", "h95", "h50", "h05", "hstd", "roof_std", "dens", "i_mean", "i_std", "i_p90"]
    lab = df[df.kind.isin(["Vehicle", "Shrub", "Tree", "Wall"])]   # small trees and walls are negatives too
    y = (lab.kind == "Vehicle").astype(int).values
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0)
    oof = cross_val_predict(clf, lab[feats].values, y, cv=5, method="predict_proba")[:, 1]
    df.loc[lab.index, "p_car"] = oof
    clf.fit(lab[feats].values, y)
    rest = df.kind.isin(["other"])
    df.loc[rest, "p_car"] = clf.predict_proba(df.loc[rest, feats].values)[:, 1]
    df["dist"] = np.hypot(df.cx, df.cn)
    print("vehicles scored as car (oof > 0.5):", f"{(oof[y == 1] > 0.5).mean():.1%};",
          "other labelled objects scored as car:", f"{(oof[y == 0] > 0.5).mean():.1%}")
    df[df.dist < 300].round(3).to_json(STAGE / "car_scores_core.json", orient="records", indent=0)   # for review
    cand = df[(df.kind != "Vehicle") & (df.p_car > 0.7)].sort_values("p_car", ascending=False)
    print(cand.groupby("kind").size().to_dict(), "candidates (p > 0.7);",
          "within 250 m:", cand[cand.dist < 250].groupby("kind").size().to_dict())
    out = STAGE / "car_candidates.json"
    cand[["name", "kind", "chunk", "p_car", "n", "L", "W", "h95", "roof_std", "bump", "cx", "cn", "dist"]].round(3).to_json(out, orient="records", indent=0)
    print(f"-> {out}")
    # accepted as cars: car-sized, enough points, and a car profile (cabin above bonnet / boot), a flat van roof, or a
    # sedan-sized flat roofline (2026-10-09, checked on side profiles with the user's parking-lot review)
    ok = cand[cand.L.between(3, 7) & cand.W.between(1.3, 3.5) & cand.h95.between(1.1, 2.4) & (cand.n >= 25)
              & (cand.p_car >= 0.7) & ((cand.bump >= 0.1) | ((cand.h95 >= 1.7) & (cand.roof_std < 0.25))
                                       # sedan-sized with a flat or one-sided roofline (hatchbacks, SUVs; sparse points)
                                       | (cand.L.between(3.5, 5.5) & cand.W.between(1.5, 2.6) & (cand.h95 >= 1.4)
                                          & (cand.roof_std < 0.15)))]
    print(f"accepted {len(ok):,} of {len(cand):,}:", ok.groupby("kind").size().to_dict(),
          "within 250 m:", ok[ok.dist < 250].groupby("kind").size().to_dict(), f"{int(ok.n.sum()):,} points")
    ok[["name", "kind", "chunk", "p_car", "n", "L", "W", "h95", "bump", "cx", "cn", "dist"]].round(3).to_json(
        STAGE / "car_accepted.json", orient="records", indent=0)


def car_indices(z, rows):
    """Point indices of the accepted unassigned car clusters (rows of car_accepted.json) in one raw chunk."""
    from scipy import ndimage
    names, ni = z["names"], z["name"]
    x = z["X"] * 0.01 - OX; n = z["Y"] * 0.01 - OY; h = z["hag"] * 0.1
    sel = np.nonzero(other_mask(names, ni, h))[0]
    if not len(rows) or not len(sel):
        return np.zeros(0, int)
    xo, no = x[sel], n[sel]
    gi = np.floor((xo - xo.min()) / CELL).astype(int); gj = np.floor((no - no.min()) / CELL).astype(int)
    g = np.zeros((gi.max() + 1, gj.max() + 1), bool); g[gi, gj] = True
    lab, _ = ndimage.label(g, np.ones((3, 3), bool)); cl = lab[gi, gj]
    out = []
    for r in rows.itertuples():
        c, k = (int(v) for v in r.name.split("#")[1].split("."))
        mi = np.nonzero(cl == c)[0]; out.append(sel[mi[split_cars(xo[mi], no[mi]) == k]])
    return np.concatenate(out)


# trucks and vans (user, 2026-10-09: the flat 2.5 m blocks in the parking lots are trucks - treat them alike)
TRUCK = dict(L=(5.0, 10.5), W=(1.9, 3.2), h95=(2.2, 3.4), roof_std=0.15, n=30)


def is_truck(f, unassigned=True):
    """A truck / van: its size, a flat roof, and most points on the roof (a hard roof; LiDAR goes into a clipped hedge,
    so flat-topped hedges have far fewer roof points - stricter for objects that Houdini called shrub or wall)."""
    return (f["roof_frac"] >= (0.6 if unassigned else 0.8) and TRUCK["L"][0] <= f["L"] <= TRUCK["L"][1] and TRUCK["W"][0] <= f["W"] <= TRUCK["W"][1]
            and TRUCK["h95"][0] <= f["h95"] <= TRUCK["h95"][1] and f["roof_std"] < TRUCK["roof_std"] and f["n"] >= TRUCK["n"])


def truck_parts(z, exclude):
    """Unassigned points 0.7-3.4 m above ground (minus the car points in exclude), clustered on the 0.4 m grid and
    cut into truck-sized parts: [(name, point indices)]."""
    from scipy import ndimage
    names, ni = z["names"], z["name"]
    x = z["X"] * 0.01 - OX; n = z["Y"] * 0.01 - OY; h = z["hag"] * 0.1
    m = np.isin(names, ["_other", ""])[ni] & (h > H_LO) & (h < 3.4)
    m[exclude] = False
    sel = np.nonzero(m)[0]
    if len(sel) < 30:
        return []
    xo, no = x[sel], n[sel]
    gi = np.floor((xo - xo.min()) / CELL).astype(int); gj = np.floor((no - no.min()) / CELL).astype(int)
    g = np.zeros((gi.max() + 1, gj.max() + 1), bool); g[gi, gj] = True
    lab, nl = ndimage.label(g, np.ones((3, 3), bool)); cl = lab[gi, gj]
    order = np.argsort(cl, kind="stable"); sc = cl[order]
    b = np.searchsorted(sc, np.arange(nl + 1)); e = np.searchsorted(sc, np.arange(nl + 1), "right")
    out = []
    for c in range(1, nl + 1):
        mi = order[b[c]:e[c]]
        if len(mi) < 30:
            continue
        parts = split_cars(xo[mi], no[mi], car_l=7.5, car_w=2.6, lloyd=False)
        for k in range(parts.max() + 1):
            if (parts == k).sum() >= 30:
                out.append((f"#{c}.{k}", sel[mi[parts == k]]))
    return out


def trucks():
    """Trucks and vans (flat roof 2.2-3.4 m, 5-10.5 m long, 1.9-3.2 m wide) among unassigned points, walls and shrubs,
    not inside a LARIAC building outline -> work/stage/truck_accepted.json (applied by apply())."""
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree
    HZ = STAGE.parent.parent
    fps = [shape(f["geometry"]).buffer(0.5) for f in json.load(open(HZ / "in" / "lariac_3km.geojson"))["features"]]
    tree = STRtree(fps)
    inside = lambda cx, cn: len(tree.query(Point(cx + OX, cn + OY), predicate="intersects")) > 0
    ok = pd.read_json(STAGE / "car_accepted.json")
    taken = set(ok.name)
    rows = []
    for ch in chunks():
        nm_ = ch["file"][:-4]
        z = np.load(STAGE / f"{nm_}.npz", allow_pickle=True)
        names, ni = z["names"], z["name"]
        x = z["X"] * 0.01 - OX; n = z["Y"] * 0.01 - OY; h = z["hag"] * 0.1; it = z["inten"].astype(float)
        for tag, idx in truck_parts(z, car_indices(z, ok[(ok.kind == "other") & (ok.chunk == nm_)])):
            f = features(x[idx], n[idx], h[idx], it[idx])
            if is_truck(f) and not inside(f["cx"], f["cn"]):
                f.update(name=f"truck@{nm_}{tag}", kind="other", chunk=nm_); rows.append(f)
        o = np.argsort(ni, kind="stable"); s = ni[o]
        b = np.searchsorted(s, np.arange(len(names))); e = np.searchsorted(s, np.arange(len(names)), "right")
        for k, nm in enumerate(names):
            if nm.split("_")[0] not in ("Wall", "Shrub") or nm in taken or e[k] - b[k] < 30:
                continue
            idx = o[b[k]:e[k]]
            f = features(x[idx], n[idx], h[idx], it[idx])
            if is_truck(f, unassigned=False) and not inside(f["cx"], f["cn"]):
                f.update(name=nm, kind=nm.split("_")[0], chunk=nm_); rows.append(f)
        print(f"{nm_}: {len(rows):,} trucks so far", flush=True)
    df = pd.DataFrame(rows).drop_duplicates("name")
    df["dist"] = np.hypot(df.cx, df.cn)
    df[["name", "kind", "chunk", "n", "L", "W", "h95", "roof_std", "roof_frac", "cx", "cn", "dist"]].round(3).to_json(
        STAGE / "truck_accepted.json", orient="records", indent=0)
    print(f"{len(df):,} trucks:", df.groupby("kind").size().to_dict(), "within 250 m:",
          df[df.dist < 250].groupby("kind").size().to_dict(), f"{int(df.n.sum()):,} points")


def apply():
    """Write the accepted cars as relabels: objects (Shrub_ / Wall_ / Tree_) -> refine_relabel.json (layer Vehicles,
    name Vehicle_<x>_<z> in dm, like Houdini's names); unassigned clusters -> work/stage/points/<chunk>.npz (point
    indices + new names), which pack_wide.py applies point by point. Run refine_objects.py shrubs afterwards, so the
    shrub patches are rebuilt without these."""
    from scipy import ndimage
    ok = pd.read_json(STAGE / "car_accepted.json")
    rel_path = STAGE / "refine_relabel.json"
    rel = json.load(open(rel_path)) if rel_path.exists() else {}
    rel = {k: v for k, v in rel.items() if not (isinstance(v, dict) and v.get("why") == "car sweep")}
    vname = lambda cx, cn: f"Vehicle_{int(round(cx * 10))}_{int(round(-cn * 10))}"
    for r in ok[ok.kind != "other"].itertuples():
        rel[r.name] = {"layer": "Vehicles", "name": vname(r.cx, r.cn), "why": "car sweep", "p_car": round(r.p_car, 3)}
    json.dump(rel, open(rel_path, "w"), indent=1)
    pdir = STAGE / "points"; pdir.mkdir(exist_ok=True)
    for f in pdir.glob("*.npz"):
        if "__" not in f.stem:          # keep refine_objects.py other's <chunk>__other.npz
            f.unlink()
    oth = ok[ok.kind == "other"]
    point_out = {}
    for ch, grp in oth.groupby("chunk"):
        z = np.load(STAGE / f"{ch}.npz", allow_pickle=True)
        names, ni = z["names"], z["name"]
        x = z["X"] * 0.01 - OX; n = z["Y"] * 0.01 - OY; h = z["hag"] * 0.1
        sel = np.nonzero(other_mask(names, ni, h))[0]
        xo, no = x[sel], n[sel]
        gi = np.floor((xo - xo.min()) / CELL).astype(int); gj = np.floor((no - no.min()) / CELL).astype(int)
        g = np.zeros((gi.max() + 1, gj.max() + 1), bool); g[gi, gj] = True
        lab, _ = ndimage.label(g, np.ones((3, 3), bool)); cl = lab[gi, gj]
        idx, new = [], []
        for r in grp.itertuples():
            c, k = (int(v) for v in r.name.split("#")[1].split("."))
            mi = np.nonzero(cl == c)[0]
            m = sel[mi[split_cars(xo[mi], no[mi]) == k]]
            idx.append(m); new += [vname(r.cx, r.cn)] * len(m)
        point_out[ch] = (idx, new)
    # trucks and vans (truck_accepted.json from trucks())
    trk = pd.read_json(STAGE / "truck_accepted.json") if (STAGE / "truck_accepted.json").exists() else pd.DataFrame()
    if len(trk):
        for r in trk[trk.kind != "other"].itertuples():
            rel[r.name] = {"layer": "Vehicles", "name": vname(r.cx, r.cn), "why": "car sweep", "type": "truck"}
        json.dump(rel, open(rel_path, "w"), indent=1)
        for ch, grp in trk[trk.kind == "other"].groupby("chunk"):
            z = np.load(STAGE / f"{ch}.npz", allow_pickle=True)
            parts = dict(truck_parts(z, car_indices(z, ok[(ok.kind == "other") & (ok.chunk == ch)])))
            idx, new = point_out.get(ch, ([], []))
            for r in grp.itertuples():
                m = parts["#" + r.name.split("#")[1]]; idx.append(m); new += [vname(r.cx, r.cn)] * len(m)
            point_out[ch] = (idx, new)
    for ch, (idx, new) in point_out.items():
        np.savez(pdir / f"{ch}.npz", idx=np.concatenate(idx), name=np.asarray(new, dtype=object), layer="Vehicles")
    print(f"{(ok.kind != 'other').sum():,} objects relabelled as cars, {len(oth):,} unassigned car clusters; "
          f"{len(trk):,} trucks -> {len(list(pdir.glob('*.npz')))} point files")


if __name__ == "__main__":
    {"apply": apply, "trucks": trucks}.get(sys.argv[1] if sys.argv[1:] else "", main)()
