# sci-arc-studio-fall2026

Work for the Syracuse Visiting Studio, Fall 2026 (Prof. David Ruy): **Angels Knoll / Bunker Hill Parcel Y-1**,
NW corner of 4th and Hill Streets, Downtown Los Angeles.

Live site: https://ruiw0211.github.io/sci-arc-studio-fall2026/

**Join the project:** [docs/SETUP.md](docs/SETUP.md) (install on macOS) and
[docs/WORKFLOW.md](docs/WORKFLOW.md) (branch → pull request → discuss → merge).

> **Already have a copy from before 2026-10-08?** This project was started again for the Houdini workflow. Delete your
> old `sci-arc-studio-fall2026` folder and clone it again ([SETUP §3](docs/SETUP.md#3-get-the-project)). The earlier
> Blender version is archived, read-only, at
> [RuiW0211/sci-arc-studio-fall2026-blender](https://github.com/RuiW0211/sci-arc-studio-fall2026-blender).

## What is here

| Folder | Contents |
|---|---|
| `web/` | The public website (GitHub Pages serves this folder). `viewer.html` is the site viewer: the 2023 LiDAR point cloud, every point labelled with its building, tree, shrub or vehicle, with everyone's designs on top. |
| `web/data/` | The point cloud (`lidar_points.laz` + `.json`, written by the Houdini pipeline). |
| `web/research/` | The Y-1 research database: `data.json` holds every finding (sources, status, confidence); `index.html` searches and filters it. Link to one finding with `research/#<id>`. |
| `site-model/houdini/` | The Houdini work: the LiDAR pipeline (`tools/`), building entities (`annotations/entities.json`), the design-scene script, hand-off files for analysis layers. See its [README](site-model/houdini/README.md). |
| `site-model/exports/` | `design_<name>.glb`: one design file per person, shown on top of the point cloud. |
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
staging, so it runs on one machine (Rui's). Designers don't run it.

## Data sources and licences

- USGS 3DEP 2023 LiDAR (`CA_LosAngeles_B23`, 9 tiles around the site): public domain.
- LA County GIS: LARIAC 2020 building outlines, Assessor parcels (addresses, use, year built, floor area).
- OpenStreetMap (MOCA outline): © OpenStreetMap contributors, ODbL.
- Building names were checked by eye against map labels; no map imagery or map data is stored here.
- Reference drawings and photographs used while modelling (EIR appendices, press and archive images) are
  **not** in this repository and must not be added; see `.gitignore`.

## Working together

Branch, commit, open a pull request; the owner merges after discussion. See [CONTRIBUTING.md](CONTRIBUTING.md),
[docs/WORKFLOW.md](docs/WORKFLOW.md) and `CLAUDE.md`.
