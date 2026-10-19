"""Download what keeps people out of Y-1 and what lets them in, from OpenStreetMap, for the Free view's questions.

The Free view asks the model questions instead of switching layers (user, 2026-10-18): "Who walks past here?" needs
Angels Knoll's fence, "What keeps people out?" every fence, wall, gate and entrance round Y-1. The walking network
the population model uses (site-model/population/data/osm.json) has the ways people walk on, steps, elevators,
escalators, bridges and Angels Flight, but no barriers, so they come from here: every barrier (fence, wall, hedge,
gate, turnstile, bollard ...), entrance and park within RADIUS_M of Y-1's centre, with their tags and geometry.

The point cloud has no fence class (airborne LiDAR returns almost nothing from a chain-link fence: 2026-10-18, about
one point a metre along Angels Knoll's fence at fence height, most of them trees), so the fences are drawn from these
lines (q_passing.py).

  python fetch_barriers.py        -> data/barriers.json (OpenStreetMap, ODbL; small, committed)
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
OUT.mkdir(parents=True, exist_ok=True)
OX, OY = 384580, 3768520                  # the site origin (UTM 11N), as everywhere in the site model
Y1 = (-1.9, -4.2)                          # Y-1's centre, scene-local metres east / north (population.json y1)
RADIUS_M = 350                             # the questions look about 300 m round Y-1; a margin for the ways that cross
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "sci-arc-studio-fall2026 site model (github.com/RuiW0211/sci-arc-studio-fall2026)"}

ll = Transformer.from_crs(26911, 4326, always_xy=True)
lo0, la0 = ll.transform(OX + Y1[0] - RADIUS_M, OY + Y1[1] - RADIUS_M)
lo1, la1 = ll.transform(OX + Y1[0] + RADIUS_M, OY + Y1[1] + RADIUS_M)
bb = f"({la0:.6f},{lo0:.6f},{la1:.6f},{lo1:.6f})"
q = f"""[out:json][timeout:120];
(
  nwr["barrier"]{bb};
  node["entrance"]{bb};
  nwr["leisure"~"^(park|garden|playground|pitch)$"]{bb};
);
out body geom;"""
r = requests.post(OVERPASS, data={"data": q}, headers=UA, timeout=180)
r.raise_for_status()
osm = r.json()
osm["source"] = "OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright), via Overpass API"
osm["fetched"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
osm["query"] = {"centre_local_m": Y1, "radius_m": RADIUS_M, "bbox_lat_lon": [la0, lo0, la1, lo1]}
(OUT / "barriers.json").write_text(json.dumps(osm, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
kinds = {}
for e in osm["elements"]:
    t = e.get("tags", {})
    k = t.get("barrier") or ("entrance" if "entrance" in t else t.get("leisure"))
    kinds[k] = kinds.get(k, 0) + 1
print(f"{len(osm['elements'])} elements -> data/barriers.json:", dict(sorted(kinds.items(), key=lambda kv: -kv[1])))
