"""Download the 3 x 3 block of 2023 USGS 3DEP LiDAR tiles around the site (the centre tile plus its 8 neighbours) into
site-model/data/lidar/ (gitignored; public domain). Same source as site-model/scripts/fetch_lidar.py. Safe to re-run:
complete files are kept, partial downloads go to *.part first.

  python site-model/houdini/tools/fetch_lidar_tiles.py
"""
from pathlib import Path

import requests

BASE = ("https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CA_LosAngeles_B23/"
        "CA_LosAngeles_1_B23/LAZ/")
OUT = Path(__file__).resolve().parents[2] / "data" / "lidar"
OUT.mkdir(parents=True, exist_ok=True)

for e in (383, 384, 385):            # tile south-west corners, km (UTM 11N): E 383-385, N 3767-3769
    for n in (3767, 3768, 3769):
        name = f"USGS_LPC_CA_LosAngeles_B23_11SLT{e:04d}00{n:04d}00.laz"
        dst = OUT / name
        size = int(requests.head(BASE + name, allow_redirects=True, timeout=60).headers.get("content-length", 0))
        if dst.exists() and size and dst.stat().st_size == size:
            print(f"already there: {name} ({size / 1e6:.1f} MB)", flush=True)
            continue
        tmp = dst.with_suffix(".part")
        with requests.get(BASE + name, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        if size and tmp.stat().st_size != size:
            raise SystemExit(f"{name}: got {tmp.stat().st_size} bytes, expected {size}")
        tmp.replace(dst)
        print(f"saved {name} ({size / 1e6:.1f} MB)", flush=True)
print("done")
