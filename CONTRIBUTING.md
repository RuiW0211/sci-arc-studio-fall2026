# Contributing

New here? Start with these two guides:

1. **[docs/SETUP.md](docs/SETUP.md)**: install the tools (macOS), get a GitHub account and access, clone the project,
   and connect Claude and Houdini.
2. **[docs/WORKFLOW.md](docs/WORKFLOW.md)**: the day-to-day routine: branch, edit, preview, open a pull request,
   discuss, merge.

The rules in short:

- Don't push to `main`. Every change is a pull request from a branch named `<yourname>/<topic>`, and the owner merges
  it after discussion.
- Your design lives in your own Houdini scene and is exported to your own `site-model/exports/design_<name>.glb`.
  Commit only your own design file.
- Never commit copyrighted references (drawings, photos, PDFs), Houdini scenes (`.hipnc`), raw LiDAR tiles, or secrets.
- Keep everything in EPSG:26911 metres, NAVD88 heights, origin E 384580 / N 3768520. See [CLAUDE.md](CLAUDE.md).
