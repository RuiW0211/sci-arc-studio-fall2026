#!/usr/bin/env python3
"""Export the nine plates in index.html as point clouds with depth, into one Rhino 7 model.

Pipeline:
  1. The drawing code is lifted from index.html (the <script id="core"> block) and run with
     macOS JavaScriptCore (osascript -l JavaScript). Each plate is drawn at its default
     proportions with the tint off, so every pixel is one of the plate's neutral greys.
     The paper behind the Folk Victorian gable is set to black so it drops out with the voids.
  2. sips rasterises each SVG.
  3. Every pixel is classified by grey value. Openings and dark shade (darker than halfway
     between g3 and g4) are hollow and take no points. Everything else gets a depth from its
     tone, in the plate's own convention that darkness reads as depth:
         z = 0.09 * (grey - wall grey)   (inches; + toward the viewer)
     so lit mouldings stand about 2 in. proud of the wall and mid greys sit 2 to 5 in. back.
     The Matta-Clark cut is solved as geometry instead: a point inside the cone gets the depth
     at which the oblique cone passes through it. The room behind is hollow, the far wall sits
     10 ft back, and the daylight beyond it is empty.
  4. 1000 points per plate: 60% spread over the solid area (the plain wall at a quarter of the
     density of the element), 40% on edges so the mouldings, tracery and bars read.
  5. rhino3dm writes a Rhino 7 .3dm: one layer and one point cloud per plate, laid out on a
     3 x 3 grid in the XZ plane (Front view), depth along -Y, units inches, points coloured
     with the yellow-tinted greys of the web page, a text dot naming each plate.

Run:  python3 export_pointclouds.py [--points 1000] [--out out/victorian_plates_pointclouds.3dm]
Needs: macOS (osascript, sips), Pillow, numpy, rhino3dm.
"""

import argparse
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import rhino3dm
from PIL import Image, ImageFilter

HERE = Path(__file__).parent
NEUTRAL = dict(wall=223, lit=247, g2=203, g3=169, g4=125, g5=80, white=255)
HOLLOW_BELOW = (NEUTRAL["g3"] + NEUTRAL["g4"]) / 2
DEPTH_PER_GREY = 0.09
RASTER = 1600  # px on the long side


def render_svgs(tmp):
    """Run the page's own drawing code in JavaScriptCore and write one SVG per plate."""
    html = (HERE / "index.html").read_text()
    core = re.search(r'<script id="core">(.*?)</script>', html, re.S).group(1)
    driver = r"""
ObjC.import("Foundation");
NEUTRAL.paper = 0;                                   // background drops out with the voids
const meta = [];
for (const el of ELEMENTS) {
  const p = Object.fromEntries(el.params.map(q => [q.k, q.def]));
  const [W, H] = el.draw(new Scene("probe", palette(0)), p);
  const k = %d / Math.max(W, H), pw = Math.round(W * k), ph = Math.round(H * k);
  let svg = renderPlate(el, p, { px: pw, pxH: ph, tint: 0, margin: 0, prefix: "e" });
  svg = svg.replace("<svg ", `<svg width="${pw}" height="${ph}" `);
  const path = "%s/" + el.id + ".svg";
  $(svg).writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, null);
  meta.push({ id: el.id, name: el.name, style: el.style, W, H, pw, ph, params: p, svg: path });
}
JSON.stringify(meta);
""" % (RASTER, tmp)
    js = Path(tmp) / "export.js"
    js.write_text(core + "\n" + driver)
    out = subprocess.run(["osascript", "-l", "JavaScript", str(js)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def rasterise(svg, png):
    subprocess.run(["sips", "-s", "format", "png", svg, "--out", png], capture_output=True, check=True)
    return np.asarray(Image.open(png).convert("L"), dtype=np.float32)


def cone_depth(px, py, m):
    """Depth (in) at which the Matta-Clark cone passes through (px, py), or None outside the cut."""
    p = m["params"]
    r0, c0 = p["cr"] / 2, (m["W"] * p["cx"] / 100, m["H"] * (1 - p["cy"] / 100))
    taper = min(p["taper"], (r0 - 6) / 6.5)
    dx, dy = math.cos(math.radians(p["dir"])) * p["obl"], -math.sin(math.radians(p["dir"])) * p["obl"]
    ox, oy = px - c0[0], py - c0[1]
    if ox * ox + oy * oy > r0 * r0:
        return None
    # |o - v z| = r0 - t z  ->  (v.v - t^2) z^2 - 2 (o.v - r0 t) z + (o.o - r0^2) = 0, smallest z >= 0
    a = dx * dx + dy * dy - taper * taper
    b = -2 * (ox * dx + oy * dy - r0 * taper)
    c = ox * ox + oy * oy - r0 * r0
    if abs(a) < 1e-9:
        z = -c / b
    else:
        disc = max(0.0, b * b - 4 * a * c)
        roots = sorted(r for r in ((-b - math.sqrt(disc)) / (2 * a), (-b + math.sqrt(disc)) / (2 * a)) if r >= 0)
        z = roots[0] if roots else 99.0
    return z


def sample(grey, m, n, rng):
    h, w = grey.shape
    solid = grey >= HOLLOW_BELOW
    solid[:2, :] = solid[-2:, :] = solid[:, :2] = solid[:, -2:] = False          # frame line
    edges = np.asarray(Image.fromarray(grey.astype(np.uint8)).filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    ys, xs = np.nonzero(solid)
    weights = edges[ys, xs] + 1e-3
    # the plain wall field gets a quarter of the density, so the points go to the element itself
    field = np.where(np.abs(grey[ys, xs] - NEUTRAL["wall"]) < 4, 0.25, 1.0)
    n_edge = int(n * 0.4)
    spread = rng.choice(len(xs), (n - n_edge) * 2, replace=False, p=field / field.sum()).tolist()
    edged = rng.choice(len(xs), n_edge * 3, replace=False, p=weights / weights.sum()).tolist()
    # fill each quota in turn (spares cover points dropped as daylight), then top up from the spares
    quotas = [(spread, n - n_edge), (edged, n)]
    pts, used = [], set()
    for pool, upto in quotas + [(spread + edged, n)]:
        for i in pool:
            if len(pts) >= upto:
                break
            if i in used:
                continue
            used.add(i)
            point = place(xs[i], ys[i], grey, m, w, h, rng)
            if point:
                pts.append(point)
    return pts[:n]


def place(px, py, grey, m, w, h, rng):
    """One pixel to one point (model x, y, depth, grey), or None for daylight."""
    x, y = px + rng.random(), py + rng.random()                               # jitter inside the pixel
    mx, my = x / w * m["W"], y / h * m["H"]
    g = float(grey[py, px])
    z = DEPTH_PER_GREY * (g - NEUTRAL["wall"])
    if m["id"] == "matta-clark":
        zc = cone_depth(mx, my, m)
        if zc is not None:
            if zc <= 6.5:
                z = -zc
            elif g > 250:
                return None                                                   # daylight
            else:
                z = -120.0                                                    # far wall
    return (mx, my, z, g)


def tinted(g):
    return (int(min(255, g + 7)), int(min(255, g + 4)), int(max(0, g - 19)), 255)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--points", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=HERE / "out" / "victorian_plates_pointclouds.3dm")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1874)

    model = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Inches
    with tempfile.TemporaryDirectory() as tmp:
        meta = render_svgs(tmp)
        cell_w = max(m["W"] for m in meta) + 60
        cell_h = max(m["H"] for m in meta) + 60
        for k, m in enumerate(meta):
            grey = rasterise(m["svg"], str(Path(tmp) / f'{m["id"]}.png'))
            pts = sample(grey, m, args.points, rng)
            layer = rhino3dm.Layer()
            layer.Name = f'{m["style"]} - {m["name"]}'
            li = model.Layers.Add(layer)
            attr = rhino3dm.ObjectAttributes()
            attr.LayerIndex = li
            attr.Name = m["id"]
            ox, oz = (k % 3) * cell_w, -(k // 3) * cell_h
            cloud = rhino3dm.PointCloud()
            for x, y, z, g in pts:
                cloud.Add(rhino3dm.Point3d(ox + x, -z, oz + (m["H"] - y)), tinted(g))
            model.Objects.AddPointCloud(cloud, attr)
            model.Objects.Add(rhino3dm.TextDot(f'{m["name"]} ({m["style"]})', rhino3dm.Point3d(ox, 0, oz + m["H"] + 12)), attr)
            zs = [p[2] for p in pts]
            print(f'{m["id"]:14s} {len(pts):5d} points   depth {min(zs):7.1f} to {max(zs):5.1f} in')
    if not model.Write(str(args.out), 7):
        raise SystemExit(f"could not write {args.out}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
