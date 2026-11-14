# Configuration contract

Use a JSON object with no unknown or duplicate keys. [Config](../src/lidar2dsm/config.py)
is the authoritative owner of fields, defaults and invariants. This table
describes that contract; examples do not define competing defaults.

| Field | Meaning / behaviour when omitted |
|---|---|
| `inputs` | Required nonempty array of LAS/LAZ files or recursively searched directories. Paths are relative to the JSON file. Duplicate files from overlapping paths are rejected. |
| `mode` | `dtm`, `dsm`, `dsm_and_dtm` or `ndsm`. Default: `dsm_and_dtm`. `ndsm` also writes DSM and DTM. |
| `resolution_m` | Positive finite pixel size in metres. Default: 0.5. Identical across products; never changed based on density or clamped to 1 m. |
| `radius_m` | Positive horizontal DTM IDW radius. Default: 1 m. Does not affect DSM, which uses exact cell binning. |
| `idw_power` | Positive finite IDW exponent. Default: 2. |
| `ground_classes` | Nonempty array of distinct integer ASPRS codes, 0–255. Default: `[2]`. |
| `dsm_classes` | `null` uses all classes (default); a nonempty array filters by codes. No implicit noise removal. |
| `crs_if_missing` | Default: `null`. Assigns a CRS only to headers without one. Must agree with any declared header CRS. Does not transform coordinates. |
| `vertical_reference` | Nonempty provenance label for Z metres. Default `unknown` preserves uncertainty and produces a warning. Does not verify or convert the datum. |
| `bounds` | `null` uses the combined header extent; otherwise `[xmin,ymin,xmax,ymax]` in the input CRS. Expanded outward to the grid anchored at `(0,0)`. |
| `chunk_points` | Positive integer; default 500000. Read batch size, with no numerical effect. |
| `tile_pixels` | Positive integer; default 256. Bucket/window edge length, without changing results. |
| `max_tile_points` | Positive integer; default 2000000. Limit per bucket and per window including halo; exceeding it is an explicit error. |
| `max_cells` | Positive integer; default 100000000. Width × height limit checked before processing. |

Booleans in numeric fields, NaN, infinities and out-of-domain values are rejected.
Withheld points are always excluded; other flags do not filter points.
Overlapping flight strips or files are not automatically deduplicated.

## Spatial references

All files must share a projected CRS suitable for the area, with horizontal
units in metres. Geographic coordinates, Web Mercator and feet are rejected.
If the CRS declares vertical units, they must be metres; otherwise the provider
is responsible for confirming Z metres. A datum label does not prove that
different surveys are compatible. No horizontal or vertical transformations
or geoid corrections are performed.

`validate` inspects headers, paths, CRS and expected grid size. Only `run` reads
points and checks classes, memory limits and resulting coverage.

## Resolution and density

0.5 m/pixel means 4 cells/m²; 5 points/m² describes a different sampling quantity.
DTM support depends on **ground** density rather than all returns. A fine grid
may have many interpolated or NoData cells. Use `ground_count` and `dtm_support`
to inspect that distinction.
