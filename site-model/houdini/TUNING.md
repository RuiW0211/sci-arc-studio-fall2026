# Tuning the wide LiDAR point cloud

Two separate sets of settings. The first decides **what is in the data file**; the second decides **how the viewer draws it**.

## 1. Data: `site-model/houdini/thinning.json` → `tools/pack_wide.py`

Edit a value in `thinning.json`, then run (a few minutes, no Houdini needed):

```
python site-model/houdini/tools/pack_wide.py pack
```

This rewrites the website's point cloud, `web/data/lidar_points.laz` / `.json`. For a one-off trial, flags override the file:
`--r0 250 --power 2.7 --density 0.8 --keep-min 0.015 --edge-end 1230 --mist 0.005 --mist-end 1230`.
`python site-model/houdini/tools/pack_wide.py plan` estimates the point count without writing anything.

| Setting | Now | What it changes |
|---|---|---|
| `full_density_radius_m` | 250 | every return within this radius of Y-1; the fade starts here |
| `falloff_power` | 2.7 | how fast objects thin beyond it: share ≈ (radius / distance)^power; larger = sparser sooner |
| `density` | 1.0 | overall amount beyond the radius (0.7 = 30 % fewer points, same fade shape) |
| `density_inside_too` | false | true = `density` also thins the centre |
| `keep_min` | 0.015 | objects whose share falls below this are left out; sets how ragged the edge is |
| `edge_end_m`, `edge_width_m` | 1230, 300 | outer taper to nothing (±12 % noise), before the square edge of the 9-tile data (~1.42 km east) |
| `object_jitter` | 0.18 | each object's own random stretch of its distance (±); larger = more ragged fade |
| `noise_amplitude`, `noise_wavelength_m` | 0.22, 350 | large-scale wobble of the fade, so it is not a circle |
| `ground_patch_m` | 60 | patch size of the fade for ground / other / street furniture (not objects) |
| `mist`, `mist_end_m` | 0, 1230 | optional faint haze beyond the fade (e.g. 0.005); 0 = off |

Keep the LAZ under 50 MB (repo rule): about 10 M points at most.

## 2. Display: the viewer's "Display settings" section, or `web/config.json` → `"lidar"`

In the viewer's left panel, open **Display settings** (shown in Point cloud mode; every section of the panel folds
open / closed). Spacing, cap and size change live; **Apply** reloads with the values (needed for Density
contrast); **Reset** goes back to the values in `web/config.json`. To make values the default for everyone, write them
into `web/config.json` → `"lidar"`. URL `?px= ?keep= ?cap= ?size=` set them for one page only. New settings
go into the `DISPLAY` list in `web/js/viewer.js`.

| Setting (config.json key / URL) | Now | What it changes |
|---|---|---|
| `lodPixels` / `?px=` | 1.2 | target on-screen gap between points; smaller = denser everywhere, heavier |
| `lodKeepDensity` / `?keep=` | 0.8 | how much of the data's dense-to-sparse fade survives on screen (0 = flat, 1 = as in the data); matters where the viewer thins (dense centre and mid zone) |
| `pointCap` / `?cap=` | 6 000 000 | most points drawn at once; above it the spacing widens automatically |
| `size` / `?size=` | 0.25 | LiDAR point disk size in metres (replaces the old Point size slider) (≈ the average LiDAR spacing, 1 / √15.5 pts/m², so points just touch) |
| `lodCell` | 120 | chunk size in metres (organisation / culling only; no visible effect since the per-point LOD) |
