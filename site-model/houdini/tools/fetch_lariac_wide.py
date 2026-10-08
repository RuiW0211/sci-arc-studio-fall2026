"""Download LA County LARIAC 2020 building outlines for the 3 x 3 km LiDAR block (the 9 USGS tiles E 383-386 km,
N 3767-3770 km, EPSG:26911) and write them for Houdini in the same local frame as in/lariac_footprints.obj.
Same service as site-model/scripts/fetch_data.py; the 800 m originals in site-model/data/ are left untouched.

Outputs (site-model/houdini/in/, gitignored):
  lariac_3km.geojson          the features as delivered (HEIGHT / ELEV in feet)
  lariac_footprints_3km.obj   x = E - 384580, y = 0, z = -(N - 3768520); one group per outline, "BLD_<BLD_ID>"
                              (outlines without an ID get "BLD_noid<OBJECTID>"); outer rings only, like the 800 m file

  python site-model/houdini/tools/fetch_lariac_wide.py
"""
import json
from pathlib import Path

import requests

HZ = Path(__file__).resolve().parent.parent
OX, OY = 384580, 3768520
URL = "https://public.gis.lacounty.gov/public/rest/services/LACounty_Dynamic/LARIAC_Buildings_2020/MapServer/0/query"
ENV = {"xmin": 383000, "ymin": 3767000, "xmax": 386000, "ymax": 3770000, "spatialReference": {"wkid": 26911}}


def query_all(params):
    feats, offset = [], 0
    while True:
        r = requests.get(URL, params=dict(params, resultOffset=offset, resultRecordCount=1000, f="geojson"), timeout=180)
        r.raise_for_status()
        batch = r.json().get("features", [])
        feats += batch
        print(f"\r{len(feats)} outlines", end="", flush=True)
        if len(batch) < 1000:
            print()
            return feats
        offset += len(batch)


feats = query_all({"geometry": json.dumps(ENV), "geometryType": "esriGeometryEnvelope", "inSR": 26911,
                   "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "outSR": 26911})
(HZ / "in" / "lariac_3km.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

verts, groups, holes = [], [], 0
for f in feats:
    g, p = f["geometry"], f["properties"]
    if not g:
        continue
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    name = f"BLD_{p['BLD_ID']}" if p.get("BLD_ID") else f"BLD_noid{p['OBJECTID']}"
    faces = []
    for rings in polys:
        holes += len(rings) - 1
        ring = rings[0][:-1] if rings[0][0] == rings[0][-1] else rings[0]
        start = len(verts) + 1
        verts += [(x - OX, -(y - OY)) for x, y in ring]
        faces.append(range(start, start + len(ring)))
    groups.append((name, faces))

with open(HZ / "in" / "lariac_footprints_3km.obj", "w") as o:
    o.write("# LARIAC 2020 footprints, 3 x 3 km (in/lariac_3km.geojson), local frame: x = E - 384580, y = 0, "
            "z = -(N - 3768520); one group per BLD_ID\n")
    for x, z in verts:
        o.write(f"v {x:.3f} 0.000 {z:.3f}\n")
    for name, faces in groups:
        o.write(f"g {name}\n")
        for fc in faces:
            o.write("f " + " ".join(map(str, fc)) + "\n")
print(f"{len(groups)} outlines, {len(verts)} vertices, {holes} inner rings skipped -> in/lariac_footprints_3km.obj")
