"""Download LA County Assessor parcels around Y-1 (public, LA County GIS), for building addresses and facts.

  python site-model/houdini/tools/fetch_parcels.py [half-width m, default 400] [out name]

-> site-model/houdini/in/parcels_core.geojson (400 m) or in/<out name> (the whole site: 1450 parcels_wide.geojson) (EPSG:32611): APN, situs address, use, year built, units, floor area.
Approved by the user 2026-10-08 (addresses for the building entity table come from here, not from Google).
"""
import json
import sys
from pathlib import Path

import requests

HZ = Path(__file__).resolve().parent.parent
OX, OY = 384580, 3768520
URL = "https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query"
FIELDS = ("APN,AIN,SitusHouseNo,SitusFraction,SitusDirection,SitusUnit,SitusStreet,SitusAddress,SitusCity,SitusZIP,"
          "SitusFullAddress,AgencyName,UseType,UseDescription,YearBuilt1,EffectiveYear1,Units1,SQFTmain1,"
          "DesignType1,ParcelTypeCode,Roll_Year")


def main(half=400.0, name="parcels_core.geojson"):
    env = json.dumps({"xmin": OX - half, "ymin": OY - half, "xmax": OX + half, "ymax": OY + half,
                      "spatialReference": {"wkid": 32611}})
    feats, offset = [], 0
    while True:
        r = requests.get(URL, params={"geometry": env, "geometryType": "esriGeometryEnvelope", "inSR": 32611,
                                      "spatialRel": "esriSpatialRelIntersects", "outFields": FIELDS, "outSR": 32611,
                                      "resultOffset": offset, "resultRecordCount": 1000, "f": "geojson"}, timeout=120)
        r.raise_for_status()
        batch = r.json().get("features", [])
        feats += batch
        if len(batch) < 1000:
            break
        offset += len(batch)
    out = HZ / "in" / name
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats,
                               "source": URL, "extent_m": [OX - half, OY - half, OX + half, OY + half]}))
    print(f"{len(feats):,} parcels -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 400.0, sys.argv[2] if len(sys.argv) > 2 else "parcels_core.geojson")
