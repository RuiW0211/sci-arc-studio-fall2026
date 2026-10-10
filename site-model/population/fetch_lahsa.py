"""LAHSA 2025 street count for the site's census tracts (download approved by the user 2026-10-09).

Source: LAHSA 2025 Greater Los Angeles Homeless Count, "2025 Street Count by Census Tract" (raw volunteer tally),
as published in the Economic Roundtable's homeless count data library. The file counts tract subdivisions
("206201_qj1" ...); they are summed to the 2020 tract. Tract land areas come from the Census Gazetteer
(data/raw/2020_Gaz_tracts_06.txt, downloaded by fetch_population.py).

  python site-model/population/fetch_lahsa.py   -> site-model/population/data/lahsa_tracts.json
"""
import json
from collections import defaultdict
from pathlib import Path

import openpyxl
import requests

HERE = Path(__file__).resolve().parent
DATA, RAW = HERE / "data", HERE / "data" / "raw" / "lahsa"
RAW.mkdir(parents=True, exist_ok=True)
URL = "https://economicrt.org/wp-content/uploads/2025/08/2025-Street-Count-by-Census-Tract.xlsx"
XLSX = RAW / "2025-Street-Count-by-Census-Tract.xlsx"
if not XLSX.exists():
    XLSX.write_bytes(requests.get(URL, headers={"User-Agent": "sci-arc-studio-fall2026 research"}, timeout=120).content)

tracts = {f["properties"]["GEOID"][5:11] for f in json.loads((DATA / "blocks.geojson").read_text())["features"]}
aland = {}
for line in (HERE / "data" / "raw" / "2020_Gaz_tracts_06.txt").read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
    c = line.split("\t")
    if c[1].startswith("06037") and c[1][5:11] in tracts:
        aland[c[1][5:11]] = float(c[2])

ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)["Counts"]
rows = ws.iter_rows(values_only=True)
H = {h: i for i, h in enumerate(next(rows))}
PEOPLE = ("totStreetSingAdult", "totStreetFamMem")
DWELL = ("totCars", "totVans", "totCampers", "totTents", "totEncamp")
out = defaultdict(lambda: defaultdict(int))
for r in rows:
    t = str(r[H["Tract_Split"]])[:6]
    if t in tracts:
        o = out[t]
        o["people"] += sum(int(r[H[k]] or 0) for k in PEOPLE)
        o["dwellings"] += sum(int(r[H[k]] or 0) for k in DWELL)
        for k in DWELL + ("totSheltPeople",):
            o[k] += int(r[H[k]] or 0)
res = {t: {**dict(v), "aland_m2": aland.get(t, 0)} for t, v in sorted(out.items())}
(DATA / "lahsa_tracts.json").write_text(json.dumps({
    "source": "LAHSA 2025 Greater Los Angeles Homeless Count, 2025 Street Count by Census Tract (raw tally), via "
              "Economic Roundtable data library " + URL + "; tract land area: 2020 Census Gazetteer",
    "note": "people = unsheltered people counted; dwellings = cars + vans + RVs (campers) + tents + makeshift shelters (encampments). Raw tallies, not LAHSA's published estimates.",
    "tracts": res}, indent=1), encoding="utf-8")
print(len(res), "tracts:", sum(v["people"] for v in res.values()), "people,", sum(v["dwellings"] for v in res.values()), "dwellings")
