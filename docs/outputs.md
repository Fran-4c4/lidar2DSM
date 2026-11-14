# Outputs and coverage checks

Each execution directory contains `run.json` and the GeoTIFFs for its mode.

| File | Contents |
|---|---|
| `dtm.tif` | Float32 ground elevation in metres, using IDW within the radius. |
| `dsm.tif` | Float32 maximum Z per cell for the configured surface classes. |
| `ndsm.tif` | Float32 surface height above ground; `ndsm` mode only. |
| `point_count.tif` | UInt32 count of all non-withheld source records inside each cell. |
| `ground_count.tif` | UInt32 count of ground-class records inside each cell. |
| `dsm_count.tif` | UInt32 count of records contributing to DSM; modes with DSM. |
| `dtm_support.tif` | UInt32 count of ground neighbours within the cell-centre radius; modes with DTM. |
| `run.json` | Effective parameters, sources, grid, version, coverage, warnings and status. |

All rasters share CRS, transform and dimensions and use tiled, compressed
GeoTIFF. Unsupported elevations use **NaN as NoData**. Count rasters have no
NoData value: 0 is a valid count meaning no points or no support.

`ground_count=0` with `dtm_support>0` means terrain was computed from neighbours
outside that cell. `dtm_support=0` means DTM NoData. Counts do not measure accuracy
or distinguish duplicate overlapping records from independent observations.

Elevation statistics use finite cells. Count statistics use cells with values
greater than zero. `valid_cells` and `coverage_fraction` follow those definitions.
An elevation of zero **does count** as valid.

## Status and exit codes

- CLI 0: operation completed. `validate` only establishes valid headers.
- CLI 2: configuration, input, dependency or processing failure.
- `run.json.status`: `running`, `complete` or `failed`.

An entirely unsupported elevation product fails the run. Partial coverage is
preserved with warnings; `complete` does not mean full coverage or fitness for
every application. Existing directories are never overwritten, including those
from failed runs.

This version does not produce certified COGs, overviews, terrain tiles or web services.
