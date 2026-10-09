"""Download the inputs for the modeled day/night population layer, clipped to the site extent.

Ported from Clark Amenudo's script (archived Blender project) 2026-10-08: the extent is now the whole point cloud
(+-HALF_M around the site origin, the cloud fades out by ~1.23 km), the Assessor parcels come from the Houdini
download (site-model/houdini/in/parcels_wide.geojson, tools/fetch_parcels.py), and the workplace tables (B08601,
B08602) are no longer needed: workers' modes and arrival times come from CTPP (fetch_ctpp.py).

Outputs to data/ (small, committed) and data/raw/ (git-ignored cache):
  blocks.geojson     2020 Census blocks touching the extent, with POP100 / HU100 (2020 Census counts)
  lodes.json         LEHD LODES8 2022 jobs by workplace block (WAC), workers by home block (RAC),
                     and in-commuters by home tract (OD main; home blocks inside the site are kept
                     as blocks), for the blocks above
  tracts_ll.json     lat/lon of every home tract that sends workers to the site (2020 Gazetteer)
  parcels.geojson    LA County Assessor parcels in the extent: use, floor area (SQFTmain1-5), units
  osm.json           OpenStreetMap ways/nodes: walkable network, food, transit, parking (ODbL)
  acs.json           ACS 2019-2023 5-year: departure time (B08302) and means of transport (B08301)
                     for the site's tracts; arrival time (B08602) and means of transport (B08601) for
                     people who WORK in the City of Los Angeles; household size (B25010)
  nhts.json          NHTS 2022 (FHWA): weighted trip start-time distributions by purpose, large metros

Every file keeps a "source" field. All sources are public domain except OSM (ODbL, attribution).
The Census API needs a key, so ACS comes from the keyless table-based summary files instead.
"""
import csv
import gzip
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import requests
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
OX, OY, HALF_M = 384580, 3768520, 1250
xmin, ymin, xmax, ymax = OX - HALF_M, OY - HALF_M, OX + HALF_M, OY + HALF_M
PARCELS_WIDE = HERE.parent / "houdini" / "in" / "parcels_wide.geojson"
UA = {"User-Agent": "sci-arc-studio-fall2026 site model (github.com/RuiW0211/sci-arc-studio-fall2026)"}

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/2/query"
LODES = "https://lehd.ces.census.gov/data/lodes/LODES8/ca"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_gaz_tracts_06.txt"
PCL = "https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query"
OVERPASS = "https://overpass-api.de/api/interpreter"
ACS = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y2023-{}.dat"
NHTS = "https://nhts.ornl.gov/assets/2022/download/csv.zip"
LODES_YEAR = 2022
LA_CITY = "1600000US0644000"
LA_COUNTY = "0500000US06037"

envelope = json.dumps({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax, "spatialReference": {"wkid": 26911}})


def cached(url, name):
    """Download once into raw/ (git-ignored)."""
    p = RAW / name
    if not p.exists():
        print("download", url)
        with requests.get(url, headers=UA, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(p, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    return p


def arcgis(url, params):
    feats, offset = [], 0
    while True:
        p = dict(params, resultOffset=offset, resultRecordCount=1000, f="geojson")
        r = requests.get(url, params=p, headers=UA, timeout=180)
        r.raise_for_status()
        batch = r.json().get("features", [])
        feats += batch
        if len(batch) < 1000:
            return feats
        offset += len(batch)


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, separators=(",", ":")))
    print("wrote", name, (OUT / name).stat().st_size // 1024, "KB")


# 1. 2020 Census blocks (geometry + 2020 counts); LODES8 uses 2020 blocks
blocks = arcgis(TIGER, {"geometry": envelope, "geometryType": "esriGeometryEnvelope", "inSR": 26911,
                        "spatialRel": "esriSpatialRelIntersects", "outFields": "GEOID,POP100,HU100,AREALAND",
                        "outSR": 26911})
write("blocks.geojson", {"type": "FeatureCollection", "source": TIGER + " (2020 Census Blocks)", "features": blocks})
bids = {f["properties"]["GEOID"] for f in blocks}
tracts = sorted({b[:11] for b in bids})
print(len(bids), "blocks in", len(tracts), "tracts")

# 2. LODES: WAC (jobs at work block), RAC (workers living in block), OD main (home block -> work block)
def lodes_rows(kind, fname):
    with gzip.open(cached(f"{LODES}/{kind}/{fname}", fname), "rt") as f:
        yield from csv.DictReader(f)

lodes = {"source": f"{LODES} LODES8 {LODES_YEAR}, JT00 (all jobs), S000", "year": LODES_YEAR,
         "fields": "C000 total; CNS01-20 NAICS sectors; CE01-03 earnings; CA01-03 age", "wac": {}, "rac": {}}
for row in lodes_rows("wac", f"ca_wac_S000_JT00_{LODES_YEAR}.csv.gz"):
    if row["w_geocode"] in bids:
        lodes["wac"][row["w_geocode"]] = {k: int(v) for k, v in row.items() if k[:1] in "CS" and v.isdigit()}
for row in lodes_rows("rac", f"ca_rac_S000_JT00_{LODES_YEAR}.csv.gz"):
    if row["h_geocode"] in bids:
        lodes["rac"][row["h_geocode"]] = {k: int(v) for k, v in row.items() if k[:1] in "CS" and v.isdigit()}
# OD: who works in the site blocks, by home tract (block-level OD is synthetic noise; tracts are stable)
od = defaultdict(lambda: defaultdict(int))
for row in lodes_rows("od", f"ca_od_main_JT00_{LODES_YEAR}.csv.gz"):
    if row["w_geocode"] in bids:
        # home blocks inside the site stay as blocks: those workers walk from a building we model
        h = row["h_geocode"]
        od[row["w_geocode"]][h if h in bids else h[:11]] += int(row["S000"])
lodes["od_by_home_tract"] = {w: dict(h) for w, h in od.items()}
lodes["note"] = "OD main covers in-state home locations only; out-of-state workers are a small share."
write("lodes.json", lodes)

# 3. Home tract centroids (Gazetteer) for commute direction and distance
home_tracts = {t[:11] for h in od.values() for t in h}
gz = cached(GAZ, "2020_Gaz_tracts_06.txt")
tll = {}
with open(gz, encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        row = {k.strip(): v.strip() for k, v in row.items()}
        if row["GEOID"] in home_tracts or row["GEOID"] in tracts:
            tll[row["GEOID"]] = [float(row["INTPTLAT"]), float(row["INTPTLONG"])]
write("tracts_ll.json", {"source": GAZ, "tracts": tll})

# 4. Assessor parcels with building floor area and units: the Houdini download (EPSG:32611; within a metre of the
#    EPSG:26911 frame here), clipped to the extent. It has the first building's floor area and units of each parcel.
from shapely.geometry import box, shape   # noqa: E402
ext = box(xmin, ymin, xmax, ymax)
pw = json.loads(PARCELS_WIDE.read_text(encoding="utf-8"))
KEEP_FIELDS = ("APN", "SitusFullAddress", "UseType", "UseDescription", "SQFTmain1", "Units1", "YearBuilt1")   # what prep reads


def slim(f):
    """Only the fields the model reads; coordinates to 0.1 m (the Assessor outlines are not more accurate)."""
    def r(c):
        return [round(c[0], 1), round(c[1], 1)] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {"type": "Feature", "properties": {k: f["properties"].get(k) for k in KEEP_FIELDS},
            "geometry": {"type": f["geometry"]["type"], "coordinates": r(f["geometry"]["coordinates"])}}


pcl = [slim(f) for f in pw["features"] if f.get("geometry") and shape(f["geometry"]).intersects(ext)]
# stacked parcels (each condominium unit is its own parcel with the building's outline) -> one record per outline:
# floor area and units summed (prep_population.py sums them over a building anyway), use of the largest, every APN
stack = {}
for f in pcl:
    k = json.dumps(f["geometry"]["coordinates"])
    if k not in stack:
        stack[k] = f
        f["properties"]["APNs"] = [f["properties"]["APN"]]
        continue
    a, b = stack[k]["properties"], f["properties"]
    if (b["SQFTmain1"] or 0) > (a["SQFTmain1"] or 0):
        a.update(UseType=b["UseType"], UseDescription=b["UseDescription"], YearBuilt1=b["YearBuilt1"])
    a["SQFTmain1"] = (a["SQFTmain1"] or 0) + (b["SQFTmain1"] or 0)
    a["Units1"] = (a["Units1"] or 0) + (b["Units1"] or 0)
    a["APNs"].append(b["APN"])
    a["SitusFullAddress"] = a["SitusFullAddress"] or b["SitusFullAddress"]
pcl = list(stack.values())
write("parcels.geojson", {"type": "FeatureCollection", "features": pcl,
                          "source": PCL + " (LA County Assessor), via site-model/houdini/tools/fetch_parcels.py"})

# 5. OpenStreetMap: everything a pedestrian can use, plus destinations and entry points
ll = Transformer.from_crs(26911, 4326, always_xy=True)
lo0, la0 = ll.transform(xmin - 60, ymin - 60)
lo1, la1 = ll.transform(xmax + 60, ymax + 60)
bb = f"({la0},{lo0},{la1},{lo1})"
q = f"""[out:json][timeout:300];
(
  way["highway"]{bb};
  way["railway"="funicular"]{bb};
  node["railway"="subway_entrance"]{bb};
  node["highway"="bus_stop"]{bb};
  nwr["amenity"~"^(restaurant|cafe|fast_food|food_court|bar|pub|marketplace)$"]{bb};
  nwr["amenity"="parking"]{bb};
  nwr["tourism"~"^(hotel|museum)$"]{bb};
  nwr["amenity"~"^(theatre|arts_centre|concert_hall|school|college|university|courthouse|townhall)$"]{bb};
);
out body geom;"""
raw_osm = RAW / "overpass.json"  # Overpass is often busy: keep the last good answer
if not raw_osm.exists():
    r = requests.post(OVERPASS, data={"data": q}, headers=UA, timeout=360)
    r.raise_for_status()
    raw_osm.write_bytes(r.content)
osm = json.loads(raw_osm.read_text(encoding="utf-8"))
osm["source"] = "OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright), via Overpass API"
write("osm.json", osm)

# 6. ACS table-based summary files (pipe-delimited, one file per table, every geography)
def acs_table(table, geos):
    p = cached(ACS.format(table), f"acs5y2023-{table}.dat")
    out = {}
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.reader(f, delimiter="|")
        head = next(rd)
        for row in rd:
            if row[0] in geos:
                out[row[0]] = {h: (float(v) if v not in ("", "null") else None) for h, v in zip(head[1:], row[1:])
                               if "_E" in h}
    return out

tract_geos = {f"1400000US{t}" for t in tracts}
acs = {"source": ACS.format("<table>") + " (ACS 2019-2023 5-year, table-based summary file)",
       "B08302_departure_time_residence": acs_table("b08302", tract_geos | {LA_CITY, LA_COUNTY}),
       "B08301_means_residence": acs_table("b08301", tract_geos | {LA_CITY, LA_COUNTY}),
       "B25010_household_size": acs_table("b25010", tract_geos | {LA_CITY}),
       "geos": {"city": LA_CITY, "county": LA_COUNTY, "tracts": sorted(tract_geos)}}
write("acs.json", acs)

# 7. NHTS 2022: trip start-time and dwell-time distributions by purpose.
# Households in metros of 1M+ (CDIVMSAR ending in 2 or 3; Los Angeles is 93), for enough samples per bin.
# WHYFROM / WHYTO codes: 01 home, 03 work, 13 buy meals, 11 buy goods, 15 recreation, 17 visit friends...
if (OUT / "nhts.json").exists():          # national distributions: the existing file serves any extent
    raise SystemExit("done (nhts.json kept)")
zp = cached(NHTS, "nhts2022_csv.zip")
with zipfile.ZipFile(zp) as z:
    name = next(n for n in z.namelist() if n.lower().endswith("tripv2pub.csv"))
    rows = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))
    start = defaultdict(lambda: [0.0] * 96)   # 15-minute start-time bins
    dwell = defaultdict(lambda: [0.0] * 48)   # 10-minute dwell bins at the destination (0-8 h)
    n = 0
    for row in rows:
        if not row["CDIVMSAR"].endswith(("2", "3")):
            continue
        try:
            t, wt, dw = int(row["STRTTIME"]), float(row["WTTRDFIN"]), int(row["DWELTIME"])
        except ValueError:
            continue
        b = (t // 100) * 4 + (t % 100) // 15
        if wt <= 0 or not 0 <= b < 96:
            continue
        day = "weekend" if row["TDWKND"] == "01" else "weekday"
        for key in (f"{day}|to={row['WHYTO']}", f"{day}|{row['WHYFROM']}>{row['WHYTO']}"):
            start[key][b] += wt
            if 0 <= dw < 480:
                dwell[key][dw // 10] += wt
        n += 1
keep = lambda h: {k: [round(x) for x in v] for k, v in h.items() if sum(v) > 0}
write("nhts.json", {"source": NHTS + " (2022 NHTS public trip file tripv2pub.csv, weight WTTRDFIN)",
                    "filter": "CDIVMSAR ends in 2 or 3: metro areas of 1M+", "trips": n,
                    "start_bins": "96 x 15 min from 00:00 (STRTTIME)", "dwell_bins": "48 x 10 min (DWELTIME)",
                    "codes": {"01": "home", "02": "work from home", "03": "work", "04": "work-related",
                              "08": "school", "11": "buy goods", "12": "buy services", "13": "buy meals",
                              "15": "recreation", "16": "exercise", "17": "visit friends", "97": "other"},
                    "start": keep(start), "dwell": keep(dwell)})
