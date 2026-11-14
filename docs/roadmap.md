# Status and improvements

## Implemented

- Installable package and CLI without services or mandatory containers.
- Sequential LAS/LAZ/COPC-LAZ reading, directories and multiple files.
- Per-cell maximum DSM, ground IDW DTM and nDSM on a common grid.
- Explicit resolution without a 1 m minimum; validated filters and limits.
- Chunked reading, temporary disk buckets and ground-support halos.
- GeoTIFFs, counts, coverage and a manifest retaining vertical uncertainty.
- Original example with analytic expected values, tests and Windows/Linux CI.
- Portable agent instructions and skills, with dependency references.

## Planned

- Measure large-survey performance and resource use; optimize IDW without
  changing results and use COPC spatial indexing for crops.
- Optional, explicit ground classification.
- Other interpolators and gap filling with bounded policies and provenance masks.
- CRS and vertical-datum transformations with traceable operations and grids.
- COGs, overviews and publication profiles.
- Quantify errors against independent ground controls and test surveys of
  different densities; synthetic success does not establish real accuracy.

See [validation](validation.md) for checks actually performed.
