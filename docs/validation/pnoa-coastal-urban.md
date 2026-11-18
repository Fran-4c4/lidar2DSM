# PNOA coastal urban tiles

Observed on Windows on 2026-11-14 using seven local PNOA 2023 Canarias NPC02
LAZ tiles from the [official CNIG catalogue](https://centrodedescargas.cnig.es/CentroDescargas/lidar-tercera-cobertura).
The files were processed without cropping or decimation. They and the generated
outputs are not distributed with this repository.

The headers declare REGCAN95 / UTM zone 28N, EPSG:4083. The derived DTM retains
the source Z values in metres; no vertical transformation or independent datum
certification was performed.

## Parameters and observed results

| Measure | Result |
|---|---|
| Points read | 40,268,191 |
| Ground-class records | 8,825,489 |
| Withheld points excluded | 0 |
| Output | DTM, ground counts, point counts and DTM support |
| Parameters | 0.5 m pixels, 1 m radius, IDW power 2, ground class 2 |
| Grid | 6,000 × 6,001 pixels |
| Supported DTM cells | 7,915,060 (21.98% of the rectangular extent) |
| DTM range | −3.2725 to 98.7703 m |
| Observed elapsed time | 243.98 s on the test machine; not a performance guarantee |

An independent calculation queried the original class-2 observations around
130 serialized valid-cell centres. The maximum difference from the float32 DTM
was 0.00000366 m. Another 130 sampled NoData cells had no eligible observations
within the 1 m radius. All four written rasters retained EPSG:4083, the same
grid and resolution when read with matching native CRS data.

This checks numerical rasterization and unsupported-cell handling for these
inputs, not physical terrain accuracy. Ground coverage must be assessed for the
intended area and cannot be inferred from the total density of all point classes.
