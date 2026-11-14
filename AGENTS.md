# lidar2DSM: agent instructions

Read [docs/index.md](docs/index.md) and the relevant component documentation
before making changes. Keep all public documentation, diagrams, examples and
agent instructions in English.

## Independence and data

- The core works locally and offline after dependencies have been installed.
  Do not require another checkout, private registry, secrets, database or authentication.
- Keep this project's documentation independent of specific downstream projects.
  Describe interfaces in terms of files, formats and coordinate references.
- Inputs are read-only. Use a new output directory per run; record failures in `run.json`.
- Keep real datasets and outputs under `data/`, `outputs/` or `work/`, ignored by Git.
  Do not add external datasets without verified provenance and redistribution terms.
- Public documentation must stand on its own, with relative paths and public links.
  Do not include infrastructure notes or internal paths.
- Keep application licensing in `LICENSE` and package metadata. Keep dependency
  notices in `THIRD_PARTY.md`; do not repeat licensing text in usage guides.

## Portable skills

Read the relevant skill before working on its area:

| Work | Skill |
|---|---|
| Rasterization, IDW, counts, windows and nDSM | [raster-pipeline](.agents/skills/raster-pipeline/SKILL.md) |
| CRS, units, elevations and grids | [crs-metric-calculations](.agents/skills/crs-metric-calculations/SKILL.md) |
| Fields, parsers, defaults and validation | [document-contract-fields](.agents/skills/document-contract-fields/SKILL.md) |
| Inspecting data, logs or large trees | [command-output-safety](.agents/skills/command-output-safety/SKILL.md) |

## Invariants

- `Config` owns fields and defaults. Reject invalid values; never silently
  raise the requested pixel size to 1 m.
- DSM, DTM, nDSM and counts share CRS, transform and dimensions.
- NoData is not zero. Do not implicitly fill gaps or clamp negative nDSM values.
- Changing window or read-batch size must not change results. Halos must include
  ground support outside both the window and the requested crop.
- Density, resolution and accuracy are different quantities.
- Do not infer a known vertical datum from a horizontal CRS.
- Verify serialized products, coverage and elevations, not just exit codes.
- Distinguish verified capabilities from planned work.

Run `python -m pytest -q` when changing results and update the relevant contract
documentation. Check provenance and applicable terms before incorporating
third-party code; see [THIRD_PARTY.md](THIRD_PARTY.md).
