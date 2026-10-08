"""Automatic building entities for the whole site, from LA County Assessor parcels (user, 2026-10-08).

  python site-model/houdini/tools/auto_entities.py

Every building object of the web point cloud (LARIAC parts BLD_*, LiDAR-only structures PC_*) that is not already in a
hand-made entity of annotations/entities.json is put on the assessor "lot" it overlaps most: parcels with the same
outline (stacked condominium / air-rights parcels) count as one lot. All parts on one lot become one entity, named by
the lot's situs address, with the assessor's use, year built, units and floor area. Parts on no parcel (streets, decks)
stay single entities. The results replace the earlier automatic entities (ids A0001 ...); hand-made entities (E...)
are never touched. Entities get "status": "auto" and no Google check; landmarks are then renamed by hand.
Inputs: in/parcels_wide.geojson (tools/fetch_parcels.py 1450 parcels_wide.geojson), in/lariac_3km.geojson,
web/data/lidar_points.laz / .json.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import laspy
import numpy as np
from shapely.geometry import MultiPoint, shape
from shapely.strtree import STRtree

HZ = Path(__file__).resolve().parent.parent
OX, OY = 384580, 3768520
ANN = HZ / "annotations" / "entities.json"


def fmt_address(a):
    a = re.sub(r"\s+", " ", a or "").strip()
    a = re.sub(r" (NO|RM|STE|UNIT|APT|#)\s*\S+(?= LOS ANGELES)", "", a)
    # a unit number after the street ("400 S BROADWAY 3108", "700 W 9TH ST 512"): drop it
    a = re.sub(r"^(\d+\S* (?:[NSEW] )?\S+(?: (?:ST|AVE|BLVD|WAY|DR|PL|PLZ|CT|RD))?) \S*\d\S*(?= LOS ANGELES)", r"\1", a)
    m = re.match(r"(.*) LOS ANGELES CA (\d{5})", a)
    if not m:
        return a.title() if a else ""
    words = [w if w in ("N", "S", "E", "W") else w.capitalize() for w in m.group(1).split()]
    street = " ".join(words).replace(" Street", " St").replace(" Avenue", " Ave")
    return f"{street}, Los Angeles, CA {m.group(2)}"


def main():
    parcels = json.load(open(HZ / "in" / "parcels_wide.geojson"))["features"]
    # lots: parcels with the same outline (stacked condo / air-rights parcels) are one lot
    lots, lot_of_key = [], {}
    for f in parcels:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"]).buffer(0)
        if g.is_empty:
            continue
        key = (round(g.centroid.x, 1), round(g.centroid.y, 1), round(g.area))
        if key not in lot_of_key:
            lot_of_key[key] = len(lots); lots.append({"geom": g, "parcels": []})
        lots[lot_of_key[key]]["parcels"].append(f["properties"])
    tree = STRtree([lt["geom"] for lt in lots])
    print(f"{len(parcels):,} parcels -> {len(lots):,} lots")

    meta = json.load(open(HZ.parents[1] / "web" / "data" / "lidar_points.json"))
    names, layers = meta["attributes"]["object"]["names"], meta["attributes"]["object"]["layers"]
    las = laspy.read(HZ.parents[1] / "web" / "data" / "lidar_points.laz")
    ob = np.asarray(las["object"]); X = np.asarray(las.x) + OX; Y = np.asarray(las.y) + OY; Z = np.asarray(las.z)
    fp = {"BLD_" + str(f["properties"]["BLD_ID"]): shape(f["geometry"]).buffer(0)
          for f in json.load(open(HZ / "in" / "lariac_3km.geojson"))["features"]}

    ann = json.load(open(ANN))
    manual = [e for e in ann["entities"] if not e["id"].startswith("A")]
    # parts added automatically to a hand-made entity on an earlier run are recomputed (auto_parts)
    for e in manual:
        if e.get("auto_parts"):
            e["parts"] = [p for p in e["parts"] if p not in set(e["auto_parts"])]
            e.pop("auto_parts")
    taken = {p for e in manual for p in e["parts"]}
    # a lot that holds a hand-made entity (its assessor parcels): new parts on it join that entity (e.g. the LiDAR-only
    # links between the Angelus Plaza towers), instead of becoming a second, automatic entity
    manual_of_apn = {}
    for e in manual:
        for a_ in (e.get("parcel") or {}).get("apn", []):
            manual_of_apn.setdefault(a_, e)
    order = np.argsort(ob, kind="stable"); so = ob[order]
    lo = np.searchsorted(so, np.arange(len(names))); hi = np.searchsorted(so, np.arange(len(names)), "right")

    groups = defaultdict(list)       # lot index (or ("solo", name)) -> parts
    info = {}
    for k, nm in enumerate(names):
        if not (nm.startswith("BLD_") or nm.startswith("PC_")) or nm in taken or hi[k] == lo[k]:
            continue
        idx = order[lo[k]:hi[k]]
        g = fp.get(nm)
        if g is None or g.is_empty:
            pts = np.c_[X[idx], Y[idx]]
            g = MultiPoint(pts[:: max(1, len(pts) // 3000)]).convex_hull
        best, best_a = None, 0.0
        for j in tree.query(g):
            a = lots[j]["geom"].intersection(g).area
            if a > best_a:
                best, best_a = j, a
        share = best_a / g.area if g.area > 0 else 0
        key = best if (best is not None and share >= 0.3) else ("solo", nm)
        groups[key].append(nm)
        info[nm] = {"top": float(np.percentile(Z[idx], 99)), "base": float(np.percentile(Z[idx], 2)),
                    "c": (float(X[idx].mean()), float(Y[idx].mean())), "layer": layers[k]}

    autos = []
    joined = 0
    for key in list(groups):
        if isinstance(key, tuple):
            continue
        if any("Parking" in (p.get("UseDescription") or "") for p in lots[key]["parcels"]):
            continue                       # a parking lot holds many small buildings: no joining there
        hit = [manual_of_apn[p["APN"]] for p in lots[key]["parcels"] if p.get("APN") in manual_of_apn]
        if hit:
            e = hit[0]; e["parts"] = e["parts"] + groups[key]; e["auto_parts"] = e.get("auto_parts", []) + groups[key]
            joined += len(groups.pop(key))
    print(f"{joined:,} parts joined to hand-made entities on the same lot")
    for key, parts in groups.items():
        parts.sort(key=lambda p: -info[p]["top"])
        height = max(info[p]["top"] for p in parts) - min(info[p]["base"] for p in parts)
        cx = np.mean([info[p]["c"][0] for p in parts]); cy = np.mean([info[p]["c"][1] for p in parts])
        e = {"parts": parts, "status": "auto", "source": "automatic: LA County Assessor lot of its LiDAR parts",
             "height_m": round(height, 1), "dist_m": round(float(np.hypot(cx - OX, cy - OY)))}
        if isinstance(key, tuple):          # on no parcel (street, deck): its own entity
            e["name"] = "Structure (no parcel)" if parts[0].startswith("PC_") else "Building (no parcel)"
            e["use"] = "unknown"
        else:
            ps = lots[key]["parcels"]
            withaddr = [p for p in ps if (p.get("SitusFullAddress") or "").strip()]
            best = max(withaddr or ps, key=lambda p: p.get("SQFTmain1") or 0)
            addr = fmt_address(best.get("SitusFullAddress"))
            uses = Counter(p.get("UseDescription") for p in ps if p.get("UseDescription"))
            use = uses.most_common(1)[0][0] if uses else None
            yb = best.get("YearBuilt1"); yb = yb if yb and yb != "0000" else None
            units = sum((p.get("Units1") or 0) for p in ps) or None
            e["name"] = addr.split(",")[0] if addr else f"Building on {use or 'unaddressed'} parcel"
            e["use"] = (use or "unknown").lower()
            if addr:
                e["address"] = addr
            e["parcel"] = {"apn": sorted({p["APN"] for p in ps})[:12], "n_parcels": len(ps), "use": use,
                           "year_built": yb, "units": units, "floor_area_sqft": best.get("SQFTmain1") or None}
            if (best.get("AgencyName") or "").strip():
                e["parcel"]["agency"] = best["AgencyName"].strip()
        autos.append(e)
    autos.sort(key=lambda e: e["dist_m"])
    for i, e in enumerate(autos, 1):
        e["id"] = f"A{i:04d}"
    # keep hand renames of earlier automatic entities (matched by their parts)
    old = {tuple(sorted(e["parts"])): e for e in ann["entities"] if e["id"].startswith("A") and e.get("renamed")}
    for e in autos:
        o = old.get(tuple(sorted(e["parts"])))
        if o:
            for k in ("name", "use", "renamed", "note", "landmark"):
                if k in o:
                    e[k] = o[k]
    ann["entities"] = manual + [{"id": e.pop("id"), **e} for e in autos]
    json.dump(ann, open(ANN, "w"), indent=1)
    n_parts = sum(len(e["parts"]) for e in autos)
    print(f"{len(autos):,} automatic entities from {n_parts:,} parts "
          f"({sum(1 for e in autos if 'address' in e):,} with an address, "
          f"{sum(1 for e in autos if len(e['parts']) > 1):,} with several parts); {len(manual)} hand-made kept")


if __name__ == "__main__":
    main()
