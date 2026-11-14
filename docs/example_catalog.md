# Example datasets

## Included original synthetic example

`python -m lidar2dsm demo --output work/demo` generates small, reproducible data:
64 ground points at 25 m and 16 roof points at 29 m. See the
[first-run instructions](../README.md). The example does not simulate buildings
with no ground returns beneath their roofs or establish real-survey accuracy.

## Delft: public 3dfier example

The [official tutorial](https://tudelft3d.github.io/3dfier/first_run.html) describes
`BGT_Delft_Example.zip`. The [repository](https://github.com/tudelft3d/3dfier)
contains `example_data/ahn3/ahn3_cropped_1.laz` and `ahn3_cropped_2.laz`, Delft BGT
polygons and reference outputs. The package does not contain a raster DTM.

Point `inputs` at a local copy of those LAZ files and select `dtm` or `ndsm`.
Check their actual CRS, classes and vertical reference before processing; do not
choose an EPSG code from the city name alone. For subsequent reconstruction
comparisons, convert the footprints to the receiving tool's input format.

External datasets are not redistributed here. Check BGT/AHN provider conditions
before publishing copies. Reference outputs from another reconstruction tool
are useful for comparing tools, but are not independent elevation ground truth.

For testing visualization software, [CityJSON datasets](https://www.cityjson.org/datasets/)
provide reconstructed models rather than paired footprint and LiDAR inputs.
