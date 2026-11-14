---
name: crs-metric-calculations
description: Review units, CRS, vertical datum and grids when changing LiDAR reading, distances, IDW, crops or georeferencing in lidar2DSM.
---

# Metric references and grids

Check horizontal CRS, XY units, Z units and vertical basis for every source.
Read `docs/configuration.md` and `src/lidar2dsm/grid.py`.

- Assigning a CRS does not transform coordinates. Do not guess it or overwrite headers.
- Use a metric projection appropriate to the data, without a fixed global UTM zone.
  Geographic coordinates and Web Mercator are not this project's measurement grid.
- A horizontal reprojection does not resolve an unknown vertical datum.
  Height differences require Z metres and a compatible reference.
- Preserve explicit anchoring, orientation, edge inclusion and halos.
  Never silently change resolution or treat NoData as zero.
- Subtract a local origin when calculating distances with large coordinates.
- Check points at cell/window boundaries and read the output transform and CRS.
