# sci-arc-studio-fall2026

Work for the Syracuse Visiting Studio, Fall 2026 (Prof. David Ruy): **Angels Knoll / Bunker Hill Parcel Y-1**,
NW corner of 4th and Hill Streets, Downtown Los Angeles.

Live site: https://ruiw0211.github.io/sci-arc-studio-fall2026/

The earlier Blender version is archived, read-only, at
[RuiW0211/sci-arc-studio-fall2026-blender](https://github.com/RuiW0211/sci-arc-studio-fall2026-blender).

## What is here

| Folder | Contents |
|---|---|
| `web/` | The public website (GitHub Pages serves this folder). `viewer.html` is the site viewer: the 2023 LiDAR point cloud, every point labelled with its building, tree, shrub or vehicle, with design files on top. |
| `web/data/` | The point cloud (`lidar_points.laz` + `.json`, written by the Houdini pipeline). |
| `web/research/` | The Y-1 research database. `data.json` holds every finding (sources, status, confidence). Two views: `index.html` (Network: the entries in 3D, height for date, links from `connections.json`, built by `docs/connections_build.py`) and `list/index.html` (List: search, filters, sources). Link to one finding with `research/#<id>` (Network) or `research/list/#<id>` (List). `web/connections/` and `web/timeline/` only redirect here (Timeline was removed 2026-10-13; git tag `timeline-v1` keeps it). |
| `web/proposal/` | The project proposal (English), laid out like Methods: contents, text, and the sources each paragraph cites in the margin. Built by `docs/proposal_build.py` from `docs/proposal/proposal_en.md`; edit the Markdown and rerun the script, not the HTML. |
| `site-model/houdini/` | The Houdini work: the LiDAR pipeline (`tools/`), building entities (`annotations/entities.json`), hand-off files for analysis layers. See its [README](site-model/houdini/README.md). |
| `site-model/exports/` | `design_<name>.glb`: design files, shown on top of the point cloud. |
| `site-model/BACKLOG.md` | To-do list and plans (in Chinese). |

All geometry shares one frame: **EPSG:26911 (NAD83 / UTM 11N), metres, NAVD88 heights**, with local origin
**E 384580, N 3768520**. In Houdini and the web viewer (three.js), x = east, y = up, z = −north.

## Previewing the website locally

```
python web/serve.py
```

Then open http://localhost:8766/ . `serve.py` serves the design files and the building entities exactly as the Pages
deploy does, so the viewer loads the same files locally and online.

## Rebuilding the site

The pipeline (Houdini plus Python scripts) and its order are in
[site-model/houdini/README.md](site-model/houdini/README.md#site-pipeline-order). It needs about 7 GB of downloads and
staging.

## Data sources and licences

- USGS 3DEP 2023 LiDAR (`CA_LosAngeles_B23`, 9 tiles around the site): public domain.
- LA County GIS: LARIAC 2020 building outlines, Assessor parcels (addresses, use, year built, floor area).
- OpenStreetMap (MOCA outline): © OpenStreetMap contributors, ODbL.
- Building names were checked by eye against map labels; no map imagery or map data is stored here.
- Reference drawings and photographs used while modelling (EIR appendices, press and archive images) are
  **not** in this repository and must not be added; see `.gitignore`.
