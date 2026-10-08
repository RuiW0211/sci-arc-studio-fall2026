# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository. Owner: Rui Wang (GitHub RuiW0211).

## Project

Syracuse Visiting Studio, Fall 2026: Angels Knoll / Bunker Hill Parcel Y-1 (APN 5149-010-951), Los Angeles.
The repo holds the whole semester's work. The current focus is an interactive web site viewer (`web/viewer.html`): the
2023 USGS LiDAR point cloud, every point labelled by Houdini with its object (building, tree, shrub, vehicle …), the
buildings grouped into named entities with LA County Assessor data, and each person's design on top. Long-term goal:
points that carry research attributes and respond to designed buildings. See `site-model/BACKLOG.md`.

The project works in **Houdini** (since 2026-10-05; this repository was started again for it on 2026-10-08). The earlier
Blender version is archived at `RuiW0211/sci-arc-studio-fall2026-blender`; don't bring Blender files or scripts back.

## Collaboration rules (apply to every contributor and every Claude session)

- Never commit or push directly to `main`. Work on a branch named `<your-name>/<topic>` and open a pull request; the owner reviews and merges.
- Never force-push, rewrite published history, or delete branches you did not create.
- Keep a pull request to one topic. Prefer editing files in your own area rather than reformatting shared files.
- Never add copyrighted material: EIR appendices, Getty/press/archive photos, ArchEyes/SubwayNut images, Esri or Google imagery or map data, or anything from `site-model/references/` or `site-model/checks/`. Those stay local (they are git-ignored).
- Never commit Houdini scenes (`.hip` / `.hipnc` / `.hiplc`) or raw LiDAR tiles. Do not add files over 50 MB; ask the owner first.
- Never put credentials, tokens, or personal emails in the repo.

## Layout

- `web/` is the GitHub Pages root. Plain HTML + ES modules; three.js comes from jsDelivr through an import map. There is no build step: run `python web/serve.py` and reload.
- `web/data/`: the point cloud `lidar_points.laz` + `lidar_points.json` (written by `site-model/houdini/tools/pack_wide.py pack`).
- `site-model/houdini/`: `tools/` (the Python pipeline, `new_design_scene.py`, `pythonrc.py`), `vex/`, `annotations/entities.json` (building entities; the hand-made part is checked by hand), `handoff/` (buildings + terrain for analysis layers), `thinning.json` + `TUNING.md`. `in/`, `work/`, `out/` and all scenes are git-ignored. Its README has the pipeline order.
- `site-model/exports/design_<name>.glb`: one design file per person.
- Contributor docs: `docs/SETUP.md` (install, macOS-first) and `docs/WORKFLOW.md` (branch → PR → discuss → owner merges). Keep them in sync when tools or steps change.

## Houdini → web workflow (the current standard; do not change it without the owner's agreement)

1. **The site is the point cloud.** Only the site pipeline (Rui) writes `web/data/lidar_points.*` and `site-model/houdini/annotations/entities.json`. The viewer builds its layer toggles from the point cloud meta; `web/config.json` holds only optional display names, order, colours and default visibility, and unknown layers appear under their raw name. Never hard-code layer lists.
2. **One design file per person.** `site-model/exports/design_<name>.glb` is exported from that person's own scene (`site-model/houdini/designs/<name>.hipnc`, made by `tools/new_design_scene.py`, context = the point cloud) with its ROP `/out/export_design`. Each person commits only their own design file, so merges never overwrite someone else's work.
3. **The viewer loads every design file by itself.** The Pages workflow and `web/serve.py` list `site-model/exports/*.glb` in `assets/models.json`; the viewer draws each `design_*.glb` over the point cloud, with its own layer toggles, and design meshes are clickable.
4. **Layers come from glTF extras.** Every design node carries `extras.layer`; the scene's `web_tags` wrangle sets it from the primitive attribute `layer` (default `Design_<name>`), and `name` makes separate nodes.
5. **One location per file.** Design files live only in `site-model/exports/` and the entities only in `site-model/houdini/annotations/`; the Pages workflow copies them into the deployed site and `web/serve.py` maps them locally. Do not commit second copies under `web/`.
6. **Frame.** Houdini's axes are the viewer's: x = east, y = up, z = −north, metres, NAVD88, from the site origin. Design at real heights against `/obj/Site_context`.
7. **Update path:** model in Houdini → Render `/out/export_design` → branch + PR → owner merges → Pages redeploys in about a minute.
8. **Houdini licence:** everyone uses Houdini Apprentice (`.hipnc`); files from other licence types can't be opened in Apprentice. Claude reaches Houdini through the houdini-mcp server and `hrpyc` on port 18811 (`docs/SETUP.md` §7). The MCP runs code in its own process (no local `import hou`) and Apprentice has no command-line `hython`, so scripts run inside the Houdini session; paths in scenes are `$HIP`-relative.

## Conventions

- One coordinate frame everywhere: EPSG:26911, metres, NAVD88. The local origin is E 384580 / N 3768520. three.js and Houdini: x = east, y = up, z = −north. LAS / LAZ files and the hand-off use x = east, y = north, z = up.
- Pipeline scripts find their folder from `__file__`.
- Every derived dataset records its source in a `source` field or the script docstring. Keep doing that.
- Object names are stable IDs (`MOCA`, `AF_Track_Deck`, `Metro_Canopy_Glass`, `BLD_<LARIAC id>`, `PC_<x>_<z>` for structures not in LARIAC); the viewer, the point-cloud labels and `entities.json` rely on them. Numbered names (`Tree_0042`, `Vehicle_…`, `Shrub_…`, `Wall_…`) change on every rebuild: never reference them from other files.
- Web style: minimal, system font, light/dark via `prefers-color-scheme`, matching the studio site.

## Data provenance

- LiDAR: USGS 3DEP `CA_LosAngeles_B23` (2023), the 3 × 3 tiles 11SLT0383-0385 / 3767-3769 around `USGS_LPC_CA_LosAngeles_B23_11SLT038400376800.laz`, from https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CA_LosAngeles_B23/CA_LosAngeles_1_B23/LAZ/ (public domain).
- Buildings: LA County LARIAC 2020 outlines. Parcels: LA County Assessor (public.gis.lacounty.gov). MOCA outline: OSM way 206463626.
- Building names: checked by eye against map labels and typed by hand; no map imagery or map data is stored.
