---
name: raster-pipeline
description: Modify DSM, DTM, IDW, counts, grids, partitions or nDSM in lidar2DSM and verify numerical outputs and coverage.
---

# LiDAR raster pipeline

Read `docs/architecture.md` and `docs/outputs.md` before changing algorithms.
`src/lidar2dsm/config.py` owns fields and defaults.

- DSM uses the maximum inside each cell; do not spread points through a hidden radius.
- DTM uses only ground classes and neighbours within the declared radius.
  Average points exactly at a cell centre without dividing by zero.
- DSM, DTM and nDSM share the entire grid. Preserve negative values and NoData.
- Include halos from neighbouring buckets and outside the requested crop.
  Changing partition/read-batch sizes must not change results.
- Keep counts and manifests consistent with filters and retained points.
  Successful processing with interpolated coverage does not establish accuracy.
- Verify changes with analytic elevations and read the produced GeoTIFFs.
  Run `python -m pytest -q`. Do not require private surveys for the suite.

The initial version does not classify ground or fill gaps beyond the radius.
Any extension must expose its policy and provenance explicitly.
