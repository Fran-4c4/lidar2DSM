# Delft 3dfier sample

This case study used `ahn3_cropped_1.laz` and `ahn3_cropped_2.laz` from
`example_data/ahn3` in [3dfier](https://github.com/tudelft3d/3dfier).
Neither those files nor the generated outputs are distributed with this
repository.

The crop headers do not declare a CRS. `crs_if_missing: "EPSG:28992"` was
explicitly assigned after checking the BGT footprint CRS in the same example
package and AHN's RD reference. [Official AHN documentation](https://www.ahn.nl/dataroom)
describes its references. The run retained `vertical_reference: "unknown"` and
did not certify or transform the crops' vertical reference.

## Parameters

- Mode: `ndsm`
- Resolution: 0.5 m
- DTM radius: 1 m
- Ground class: 2
- DSM classes: all
- Gap filling: none beyond the declared IDW radius

## Observed results

| Measure | Result |
|---|---|
| Points read | 848,942 |
| Withheld points excluded | 0 |
| Common grid | 529 × 458 pixels, 0.5 m/pixel |
| Cells with ground points inside the cell | 48.85% |
| DTM coverage with support within 1 m | 61.95% |
| DSM coverage | 88.51% |
| nDSM coverage | 60.49% |
| DTM elevation range | −0.521 to 2.297 m |
| nDSM range | −0.425 to 23.054 m |

Gaps remain NoData: increasing grid density does not create ground observations
beneath buildings. Support should be reviewed with `ground_count` and
`dtm_support`. Negative nDSM values were retained for inspection.

This establishes successful reading, rasterization, alignment and traceability
for these files. It does not establish vertical accuracy against independent
controls or sufficient terrain support beneath every roof.
