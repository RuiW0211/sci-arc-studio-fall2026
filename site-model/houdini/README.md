# Houdini

All 3D work in this project is done in **Houdini** (since 2026-10-05). The website shows what this pipeline makes: the
2023 LiDAR point cloud with every point labelled, the building entities, and everyone's designs on top.

Two kinds of work happen here:

| | Who | What you need |
|---|---|---|
| **Design** | everyone | Houdini Apprentice, this repository. You model your design against the site and export it to the website. No data pipeline. |
| **Site pipeline** | Rui | Rebuilds the site from the raw 2023 LiDAR: point labels, building entities, the web point cloud, the hand-off files. Needs the raw downloads (about 7 GB of staging), so it runs on one machine. |

Install: [docs/SETUP.md §6–7](../../docs/SETUP.md#6-houdini). Day-to-day: [docs/WORKFLOW.md §3](../../docs/WORKFLOW.md#3-make-the-change).

## Designing

1. Make your scene once: in Houdini, **Windows → Python Shell**, paste (with your own path to the repository):

   ```python
   p = "/Users/you/GitHub/sci-arc-studio-fall2026/site-model/houdini/tools/new_design_scene.py"; exec(open(p).read(), {"__file__": p, "hou": hou})
   ```

   It asks for your name and saves `site-model/houdini/designs/<name>.hipnc`. Or ask Claude: *"make my Houdini design
   scene, my name is clark"*.
2. The scene has:
   - `/obj/Site_context`: the site point cloud (`web/data/lidar_points.laz`, grey by return intensity), for
     reference only. It is not exported.
   - `/obj/Design_<name>`: model here. Wire your nodes into **your_geometry**. A primitive attribute `name` makes
     separate objects (each one clickable on the website); `layer` makes your own layer toggles, e.g. `Clark_OptionA`
     (default `Design_<name>`).
   - `/out/export_design`: **Render** writes `site-model/exports/design_<name>.glb`.
3. Preview with `python3 web/serve.py`. Your file loads on top of the site, in both Point cloud and Mesh mode, with its
   own layer toggles. Nothing else needs changing.
4. Commit only your `design_<name>.glb` (and any scripts). The `.hipnc` is not stored in git: keep your own backup.

Each person writes only their own `design_<name>.glb`, so merging one person's pull request never overwrites someone
else's work. Only the site pipeline writes the point cloud.

**Frame:** Houdini's axes are the website's: x = east, y = up, z = −north, metres, heights NAVD88 (the street at Y-1 is
about 90 m), from the site origin E 384580 / N 3768520. Model at real heights next to the point cloud.

## Files

| Path | In git | What |
|---|---|---|
| `tools/` | yes | Python scripts of the pipeline (each one documents itself at the top), the design-scene script |
| `vex/seg_forest.vfl` | yes | the building / tree classifier, written by `tools/train_seg_forest.py` |
| `annotations/entities.json` | yes | building entities: which LiDAR objects form one building, its name, address and LA County Assessor data |
| `handoff/` | yes | buildings (stepped prisms with names, addresses, use) and terrain for analysis layers, from `tools/export_handoff.py` |
| `thinning.json`, `TUNING.md` | yes | how the web point cloud thins with distance |
| `y1_lidar.hipnc` | no | the pipeline scene (Rui) |
| `designs/*.hipnc` | no | design scenes, one per person |
| `in/`, `work/`, `out/` | no | raw downloads, chunk staging (~7 GB), outputs; rebuilt by the tools |

## Site pipeline (order)

Python 3.10+ with `pip install -r site-model/requirements.txt`; run from the repository root.

1. Downloads: `tools/fetch_lidar_tiles.py` (9 USGS tiles), `tools/fetch_lariac_wide.py` (building outlines),
   `tools/fetch_parcels.py` (Assessor parcels).
2. `tools/split_chunks.py`: 500 m chunks; then `y1_lidar.hipnc` labels each chunk (`/obj/lidar`).
3. `tools/merge_chunks.py` checks, `tools/pack_wide.py stage`.
4. Refinements: `tools/car_sweep.py`, `car_sweep.py trucks`, `car_sweep.py apply`, `tools/refine_objects.py shrubs`,
   `refine_objects.py other`.
5. `tools/pack_wide.py pack`: the website's point cloud `web/data/lidar_points.laz` / `.json` (see `TUNING.md`).
6. `tools/auto_entities.py`: building entities for the whole site.
7. `tools/export_handoff.py`: `handoff/`.

Preview: `python web/serve.py` (port 8766).

## Sources

USGS 3DEP `CA_LosAngeles_B23` 2023 LiDAR (public domain); LA County LARIAC 2020 building outlines and Assessor parcels;
OpenStreetMap (MOCA outline, ODbL). Building names were checked by eye against map labels; no map imagery or map data is
stored here.
