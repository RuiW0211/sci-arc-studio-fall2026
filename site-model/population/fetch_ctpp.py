"""Download CTPP 2017-2021 place-of-work tables for the Census tracts around Y-1 (approved by the user 2026-10-08).

CTPP (Census Transportation Planning Products, AASHTO, from the ACS 2017-2021 5-year sample) tabulates workers by
the tract where they WORK, so commute mode and arrival time describe the people who work Downtown, not City of LA
averages (the earlier population layer used ACS B08601 / B08602 for the whole city).

  B202105  Means of Transportation to Work (18): bus / subway / light rail ... kept apart   site tracts + LA County
  C202216  Time Arriving At Work (4 periods) by Means (drive / other)                        site tracts
  C214208  Means (drive / other) by Industry (5 groups)                                      site tracts
  B202216  Time Arriving At Work (17) by Means of Transportation to Work (11)                City of Los Angeles
  B214208  Means of Transportation to Work (11) by Industry (15)                             City of Los Angeles

CTPP publishes the detailed B202216 / B214208 only down to places; at tract level only their collapsed C versions
exist. The C tables give the Downtown totals, the city B tables only the split inside each collapsed class.
The tracts are the 2020 tracts of the Census blocks inside the site extent (data/blocks.geojson). Estimates and margins of error are kept as delivered (strings with commas and "+/-"
are turned into numbers). 2017-2021 includes 2020 and 2021, when working from home was unusually common: the
"Worked from home" line is kept separate, not treated as a commute.

Needs a free CTPP API key (ctppdata.transportation.org -> Login -> Manage API Keys) in the environment variable
CTPP_API_KEY. The key is never written to a file.

  python site-model/population/fetch_ctpp.py      -> site-model/population/data/ctpp.json
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
API = "https://ctppdata.transportation.org/api"
YEAR = 2021
TRACT, PLACE, CTY = "tract", "place", "county"
TABLES = {"B202105": (TRACT, CTY), "C202216": (TRACT,), "C214208": (TRACT,), "B202216": (PLACE,), "B214208": (PLACE,)}
LA_CITY = "44000"
STATE, COUNTY = "06", "037"


def session():
    key = os.environ.get("CTPP_API_KEY")
    if not key:
        sys.exit("Set CTPP_API_KEY first (see the docstring).")
    s = requests.Session()
    s.headers.update({"x-api-key": key, "Accept": "application/json"})
    return s


def pages(s, url, size=500):
    out, page = [], 1
    while True:
        r = s.get(url, params={"size": size, "page": page}, timeout=180)
        r.raise_for_status()
        j = r.json()
        out += j["data"]
        if len(out) >= j["total"] or not j["data"]:
            return out
        page += 1


def num(v):
    v = str(v).replace(",", "").replace("+/-", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def site_tracts():
    blocks = json.loads((DATA / "blocks.geojson").read_text())
    return sorted({f["properties"]["GEOID"][:11] for f in blocks["features"]})


def main():
    s = session()
    tracts = site_tracts()
    codes = ",".join(t[5:] for t in tracts)
    out = {
        "source": f"CTPP 2017-2021 (ACS 5-year), AASHTO CTPP Data API {API}, place-of-work tables, downloaded by "
                  "site-model/population/fetch_ctpp.py",
        "year": "2017-2021", "geography": "place of work: the site's 2020 tracts, the City of Los Angeles, LA County",
        "tracts": tracts, "tables": {},
    }
    geos = {TRACT: f"for=tract:{codes}&in=county:{COUNTY}&in=state:{STATE}",
            PLACE: f"for=place:{LA_CITY}&in=state:{STATE}",
            CTY: f"for=county:{COUNTY}&in=state:{STATE}"}
    for t, where in TABLES.items():
        labels = {v["name"].lower(): v.get("label", "").strip()
                  for v in pages(s, f"{API}/groups/{t}/variables?year={YEAR}")}
        est = sorted((k for k in labels if re.fullmatch(rf"{t.lower()}_e\d+", k)), key=lambda k: int(k.split("_e")[1]))
        rows = {}
        for geo in where:
            q = geos[geo]
            for rec in pages(s, f"{API}/data/{YEAR}?get=group({t.lower()})&{q}&format=list"):
                gid = rec.get("geoid") or rec.get("GEO_ID") or rec["name"]
                rows[gid] = {"name": rec["name"],
                             "estimate": [num(rec.get(k)) for k in est],
                             "moe": [num(rec.get(k.replace("_e", "_m"))) for k in est]}
        out["tables"][t] = {"labels": [labels[k] for k in est], "geographies": list(where), "rows": rows}
        print(f"{t}: {len(est)} lines, {len(rows)} geographies")
    (DATA / "ctpp.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {DATA / 'ctpp.json'} ({(DATA / 'ctpp.json').stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
