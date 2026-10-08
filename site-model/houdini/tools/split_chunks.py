"""Cut the 9 USGS LiDAR tiles (site-model/data/lidar/) into processing chunks for Houdini.

Chunk grid in the local frame (x = E - 384580, z = -(N - 3768520), metres): square cores of 500 m centred on multiples of
500 m from Y-1, kept when the core touches the 1.4 km circle around Y-1 and the 3 x 3 km tile block. Each chunk file holds
its core plus a 50 m buffer (the points the core needs for shape features, ground and crowns), raw records as delivered
(LAS 1.4, point format 6, 1 cm, UTM), so /obj/lidar/laz_points reads it exactly like a tile.

Output: site-model/houdini/work/chunks/c_<i>_<j>.laz (+ chunks.json: centre, half, buffer, point count per chunk)
  python site-model/houdini/tools/split_chunks.py
"""
import json
from pathlib import Path

import laspy
import numpy as np

HZ = Path(__file__).resolve().parent.parent
LIDAR = HZ.parent / "data" / "lidar"
OUT = HZ / "work" / "chunks"
OUT.mkdir(parents=True, exist_ok=True)
OX, OY = 384580, 3768520
HALF, BUF, STEP, RADIUS = 250.0, 50.0, 500.0, 1400.0
TILES = sorted(LIDAR.glob("USGS_LPC_CA_LosAngeles_B23_11SLT*.laz"))
XMIN, XMAX, NMIN, NMAX = 383000 - OX, 386000 - OX, 3767000 - OY, 3770000 - OY   # data block, local x / north


def tile_box(p):
    s = p.stem.split("11SLT")[1]                       # e.g. 038400376800 -> E 384 km, N 3768 km
    e, n = int(s[:4]) * 1000, int(s[6:10]) * 1000
    return e - OX, e + 1000 - OX, n - OY, n + 1000 - OY


chunks = []
for i in range(-3, 4):
    for j in range(-3, 4):
        cx, cn = i * STEP, j * STEP                      # core centre: x, north
        x0, x1, n0, n1 = cx - HALF, cx + HALF, cn - HALF, cn + HALF
        if x1 <= XMIN or x0 >= XMAX or n1 <= NMIN or n0 >= NMAX:
            continue
        dx, dn = max(x0, min(0, x1)), max(n0, min(0, n1))   # nearest core point to Y-1
        if np.hypot(dx, dn) > RADIUS:
            continue
        chunks.append((i, j, cx, cn))
print(f"{len(chunks)} chunks")

ref = laspy.open(TILES[0]).header
meta = []
for i, j, cx, cn in chunks:
    x0, x1, n0, n1 = cx - HALF - BUF, cx + HALF + BUF, cn - HALF - BUF, cn + HALF + BUF
    parts = []
    for t in TILES:
        tx0, tx1, tn0, tn1 = tile_box(t)
        if tx1 <= x0 or tx0 >= x1 or tn1 <= n0 or tn0 >= n1:
            continue
        with laspy.open(t) as f:
            h = f.header
            assert h.point_format.id == ref.point_format.id and np.allclose(h.scales, ref.scales) and np.allclose(h.offsets, ref.offsets), t.name
            for pts in f.chunk_iterator(4_000_000):
                x, y = np.asarray(pts.x) - OX, np.asarray(pts.y) - OY
                m = (x >= x0) & (x < x1) & (y >= n0) & (y < n1)
                if m.any():
                    parts.append(pts.array[m])
    arr = np.concatenate(parts) if parts else np.zeros(0, ref.point_format.dtype())
    hdr = laspy.LasHeader(version=ref.version, point_format=ref.point_format)
    hdr.scales, hdr.offsets = ref.scales, ref.offsets
    hdr.vlrs = ref.vlrs
    las = laspy.LasData(hdr)
    las.points = laspy.ScaleAwarePointRecord(arr, ref.point_format, ref.scales, ref.offsets)
    name = f"c_{i}_{j}.laz"
    las.write(OUT / name)
    meta.append({"file": name, "i": i, "j": j, "center": [cx, -cn], "half": HALF, "buffer": BUF, "points": int(len(arr))})
    print(f"{name}: centre x {cx:+.0f} north {cn:+.0f}, {len(arr):,} points", flush=True)
(OUT / "chunks.json").write_text(json.dumps({"frame": "x = E - 384580, z = -(N - 3768520); center = [x, z]",
                                             "chunks": meta}, indent=1))
print("done")
