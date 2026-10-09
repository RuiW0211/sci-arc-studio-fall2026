"""Download LADOT Walk & Bike Count tables, 2023 and 2025 (approved by the user 2026-10-09).

LADOT counts people walking, biking and riding scooters across one street block at about 80 temporary sites,
every second fall: weekdays (Tue-Thu) 7-10 am and 3-6 pm, weekends (Sat or Sun) 11 am-1 pm, one day each. Used only
to check the modeled street flows (prep_population.py); nothing in the model is fitted to them.

  python site-model/population/fetch_walk_counts.py   -> site-model/population/data/raw/walk_bike_count_<year>.json
"""
import json
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
DATASETS = {2023: "6ux4-qj74", 2025: "hiwe-xzrt"}   # data.lacity.org (Socrata) ids
UA = {"User-Agent": "sci-arc-studio-fall2026 population model (research)"}

for year, ds in DATASETS.items():
    r = requests.get(f"https://data.lacity.org/resource/{ds}.json", params={"$limit": 1000}, headers=UA, timeout=120)
    r.raise_for_status()
    rows = r.json()
    out = RAW / f"walk_bike_count_{year}.json"
    out.write_text(json.dumps({"source": f"https://data.lacity.org/d/{ds}", "year": year, "rows": rows}, indent=1), encoding="utf-8")
    print(f"{year}: {len(rows)} sites -> {out.name} ({out.stat().st_size / 1024:.0f} KB)")
