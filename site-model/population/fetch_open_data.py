"""City of Los Angeles open data for the population model (user, 2026-10-10, from data.lacity.org via Sam's list).

  python site-model/population/fetch_open_data.py   ->  site-model/population/data/open_data.json

Three tables, only the part inside the model square (+-1250 m around Y-1), queried through the portal's public API
(Socrata SODA, no key):
  new_housing   LADBS building permits (before 2010, 2010-2019, 2020 to present): buildings of at least
                MIN_UNITS dwelling units that got their Certificate of Occupancy after the 2020 Census day, so the
                Census housing-unit counts do not include them (new buildings and conversions)
  offices       EBEWE (Existing Buildings Energy & Water Efficiency) benchmarking: each large office building's
                floor area and self-reported occupancy, the latest year it reported
  businesses    Listing of Active Businesses (Office of Finance): food and drink (NAICS 722) and retail (44-45)
                locations
"""
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from pyproj import Transformer

OUT = Path(__file__).resolve().parent / "data" / "open_data.json"
OX, OY, HALF = 384580, 3768520, 1250
CENSUS_DAY = "2020-04-01"
MIN_UNITS = 10
PERMITS = {"b6ii-mhed": "submitted before 2010", "dyxf-7hc4": "issued 2010-2019", "pi9x-tg5x": "issued 2020 to present"}
EBEWE, BUSINESSES = "9yda-i4ya", "6rrh-rzua"
API = "https://data.lacity.org/resource/{}.json"

to_ll = Transformer.from_crs(26911, 4326, always_xy=True).transform
W, S = to_ll(OX - HALF, OY - HALF)
E, N = to_ll(OX + HALF, OY + HALF)
IN_BOX = f"lat::number between {S:.5f} and {N:.5f} and lon::number between {W:.5f} and {E:.5f}"


def soda(ds, **q):
    q.setdefault("$limit", 50000)
    url = API.format(ds) + "?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


# ---- new housing since the Census: one record per address, the latest Certificate of Occupancy
housing = {}
for ds, label in PERMITS.items():
    rows = soda(ds, **{"$select": "permit_nbr, primary_address, apn, permit_type, permit_sub_type, du_changed, height, "
                                  "issue_date, cofo_date, status_desc, lat, lon",
                       "$where": f"{IN_BOX} and du_changed::number >= {MIN_UNITS} and cofo_date >= '{CENSUS_DAY}'"})
    for r in rows:
        key = (r.get("primary_address") or "").split(" 1-")[0].strip()
        rec = {"address": key, "units": int(float(r["du_changed"])), "cofo": r["cofo_date"][:10],
               "permit": r["permit_nbr"], "type": r.get("permit_type"), "lat": float(r["lat"]), "lon": float(r["lon"]),
               "height_ft": float(r["height"]) if r.get("height") else None, "table": label}
        if key not in housing or rec["cofo"] > housing[key]["cofo"]:
            housing[key] = rec
print("new housing:", len(housing), "buildings,", sum(h["units"] for h in housing.values()), "units")

# ---- office buildings: floor area and occupancy, latest reporting year per building
rows = soda(EBEWE, **{"$select": "building_id, building_address, postal_code, primary_property_1, property_gfa_1, "
                                 "occupancy, year_built, program_year",
                      "$where": "primary_property_1 in ('Office', 'Mixed Use Property', 'Bank Branch', 'Financial Office') "
                                "and postal_code in ('90012', '90013', '90014', '90015', '90017', '90021', '90071')"})
offices = {}
for r in rows:
    if not r.get("occupancy"):
        continue
    k = r["building_id"]
    if k not in offices or r["program_year"] > offices[k]["year"]:
        offices[k] = {"address": " ".join(r["building_address"].upper().split()), "zip": r["postal_code"],
                      "type": r["primary_property_1"], "gfa_sqft": float(r.get("property_gfa_1") or 0),
                      "occupancy": float(r["occupancy"]) / 100, "year": r["program_year"]}
print("office buildings:", len(offices))

# ---- businesses: food and drink, and shops
box = f"within_box(location_1, {N:.5f}, {W:.5f}, {S:.5f}, {E:.5f})"
rows = soda(BUSINESSES, **{"$select": "business_name, dba_name, street_address, naics, primary_naics_description, "
                                      "location_start_date, location_1",
                           "$where": f"{box} and (naics like '722%' or naics like '44%' or naics like '45%')"})
businesses = []
for r in rows:
    loc = r.get("location_1") or {}            # {"latitude", "longitude"} as text, 4 decimals (about 10 m)
    if not loc.get("latitude"):
        continue
    businesses.append({"name": (r.get("dba_name") or r.get("business_name") or "").title(), "naics": r.get("naics"),
                       "what": r.get("primary_naics_description"), "since": (r.get("location_start_date") or "")[:10],
                       "address": r.get("street_address"), "lon": float(loc["longitude"]), "lat": float(loc["latitude"])})
print("businesses:", len(businesses))

OUT.write_text(json.dumps({
    "fetched": date.today().isoformat(),
    "source": "City of Los Angeles open data, data.lacity.org (SODA API): LADBS building permits "
              + ", ".join(PERMITS) + f"; EBEWE {EBEWE}; Listing of Active Businesses {BUSINESSES}",
    "box_lonlat": [round(W, 5), round(S, 5), round(E, 5), round(N, 5)],
    "new_housing": sorted(housing.values(), key=lambda h: h["cofo"]),
    "offices": sorted(offices.values(), key=lambda o: o["address"]),
    "businesses": businesses}, indent=1), encoding="utf-8")
print("wrote", OUT, f"{OUT.stat().st_size / 1e6:.2f} MB")
