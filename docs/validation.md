# Validation performed

Local checks on 2026-11-14, version 0.1.0:

| Check | Result |
|---|---|
| Python 3.12 suite on Windows, fresh virtual environment | 51 tests passed. |
| Same suite in a Linux container | 51 tests passed; pytest cache warning from read-only test mount. |
| Docker image from digest-pinned public Python base | Built successfully, without private images. |
| Synthetic Docker conversion with networking disabled | Correct DTM/DSM/nDSM; no connection required. |
| Wheel installed into a fresh environment from another directory | demo/validate/run checked with isolated Python. |
| Four local skills | Frontmatter and structure checked with the skill validator. |
| Real LAZ files from the 3dfier Delft example | Both crops converted at 0.5 m; details below. |

Synthetic tests check known elevations, IDW, sub-metre resolution, multiple
files, filters, NoData, non-UTM CRS, compressed LAZ reading, GIS environment
restoration and consistency across window/read-batch sizes.

## Delft

External inputs: `ahn3_cropped_1.laz` and `ahn3_cropped_2.laz` from
`example_data/ahn3` in [3dfier](https://github.com/tudelft3d/3dfier).
Neither those files nor real-data outputs are distributed in this repository.

The crop headers do not declare a CRS. `crs_if_missing: "EPSG:28992"` was
explicitly assigned after checking the BGT footprint CRS in the same package
and AHN's RD reference. [Official AHN documentation](https://www.ahn.nl/dataroom)
describes its references. This test retained `vertical_reference: "unknown"`
without certifying the crops' vertical reference or transforming coordinates.

Parameters: `mode=ndsm`, `resolution_m=0.5`, `radius_m=1`, ground class 2,
all classes for DSM, and no subsequent gap filling.

| Measure | Result |
|---|---|
| Points read | 848942 |
| Withheld points excluded | 0 |
| Common grid | 529 × 458 pixels, 0.5 m/pixel |
| Cells with ground points inside the cell | 48.85% |
| DTM coverage with support within 1 m | 61.95% |
| DSM coverage | 88.51% |
| nDSM coverage | 60.49% |
| DTM elevation range | −0.521 to 2.297 m |
| nDSM range | −0.425 to 23.054 m |

Gaps remain NoData: increasing grid density does not create ground observations
beneath buildings. Review support using `ground_count` and `dtm_support`.
Negative nDSM values are retained for inspection. This establishes successful
reading/rasterization, alignment and traceability, **not** vertical accuracy
against independent controls or sufficient support beneath every roof.

## Limits of this evidence

Full large-survey processing, spatial use of the COPC index, ground classification,
datum correction, macOS and COG output have not been tested. GitHub CI is prepared
but will only run there after publication. Main tested versions are recorded in
`constraints/python312.txt`; other platforms need their own validation.
