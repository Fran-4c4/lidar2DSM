# Grid-aligned LiDAR repositories

A long-lived LiDAR collection needs two independent spatial organisations:

- source files retain the provider's original names and acquisition metadata;
- derived products use a project-owned, stable metric grid.

This separation allows a source survey to be replaced without changing DTM,
DSM or nDSM tile identities. It also avoids using city names as storage keys.

Repository initialization, incremental PNOA ingestion and grid-aligned product
generation are implemented. The CLI validates headers, copies or moves verified
sources, expands BBOX requests to complete cells, writes one COG per product
tile and maintains source/product lineage in the GeoPackage catalogue.

## Repository layout

```text
lidar/
├── README.md
├── repository.json
├── catalog/
│   └── catalog.gpkg
├── source/
│   └── <provider>/<campaign>/<region>/<zone>/<classification>/
│       └── original-provider-name.laz
├── products/
│   ├── dtm/<grid_id>/releases/<release_id>/...
│   ├── dsm/<grid_id>/releases/<release_id>/...
│   └── ndsm/<grid_id>/releases/<release_id>/...
└── work/
```

Source files are immutable. A replacement survey is ingested as a new source
record and only becomes active after validation. Product releases are also
immutable; catalogue state selects the active revision.

## Initialize and ingest

Start from [`examples/repository.json`](../examples/repository.json). Review the
destination, horizontal CRS and vertical-reference declaration before running:

```powershell
python -m lidar2dsm repository init path\to\repository.json
python -m lidar2dsm repository ingest path\to\repository.json path\to\delivery
```

`init` is idempotent: it creates missing directories, `README.md`, a portable
`repository.json` and `catalog/catalog.gpkg`, or validates the existing grid
contract. It never replaces an existing catalogue or repository contract.

`ingest` searches the input directory recursively. Its default `--mode copy`
keeps the delivery. `--mode move` first copies and checks every new file,
commits the catalogue transaction, and only then removes the corresponding
input. Exact checksums already present in the catalogue are reported as
duplicates rather than inserted again.

The initial provider profile is `pnoa`. It reads campaign, region, UTM zone and
classification from supported PNOA names, but verifies cell identity and CRS
against the LAS/LAZ header. An unsupported name, missing/contradictory CRS,
multi-cell source or same logical identity with different bytes rejects the
batch before any catalogue insertion.

When a newer campaign covers an active provider cell, the previous record
becomes `superseded`. An older delivery may be retained and catalogued as
`superseded`, but it does not replace the active source.

For a reproducible import, use an import job rather than command-line paths:

```json
{
  "repository": "../repository.json",
  "input_directory": "C:/data/incoming/pnoa",
  "transfer_mode": "copy"
}
```

```powershell
python -m lidar2dsm repository import jobs\import.json
```

## Grid definition contract

Each grid is owned by one `grid_definition` record. `RepositoryConfig` and
`GridDefinition` own parsing, validation and serialized field names; examples
do not define competing defaults.

| Field | Contract |
|---|---|
| `grid_id` | Stable identifier. It includes the horizontal reference, zone, nominal tile size and contract version. |
| `horizontal_crs` | Authority code of the projected, metric processing CRS. Geographic CRS and Web Mercator are not processing grids. |
| `origin_x_m`, `origin_y_m` | Fixed grid origin in CRS metres. Tile indices and boundaries are derived from this origin. |
| `tile_size_m` | Positive tile width and height in metres. It must be an integer multiple of `resolution_m`. |
| `resolution_m` | Positive base pixel size in metres. It determines raster dimensions, not source accuracy or point density. |
| `vertical_reference` | Provenance label for Z. `unknown` is valid and preserves uncertainty; it must never be inferred from the horizontal EPSG code. |
| `tile_id_template` | Stable identity derived from the canonical lower-left boundary. Provider filenames must not define it. |

For the initial Canarias collection the proposed grid is:

```json
{
  "grid_id": "regcan95_utm28_1km_v1",
  "horizontal_crs": "EPSG:4083",
  "origin_x_m": 0,
  "origin_y_m": 0,
  "tile_size_m": 1000,
  "resolution_m": 0.5,
  "vertical_reference": "unknown",
  "tile_id_template": "E{xmin}_N{ymin}"
}
```

Every base raster tile is therefore 2,000 by 2,000 pixels. Its identity uses
the lower-left boundary, for example `E454000_N3107000`.

## CRS and elevation rules

One catalogue may contain many horizontal CRS, but one grid and one processing
job use exactly one projected CRS. Typical grids may include REGCAN95 / UTM 28N
and separate ETRS89 UTM zones.

Ingestion reads the CRS from every LAS/LAZ header and records both its native
bounds and a WGS 84 search footprint. A provider name is only evidence, never
the CRS authority. Missing CRS may be assigned only through an explicit,
recorded override. A declared CRS that contradicts the selected grid is an
error, not an automatic correction.

Horizontal compatibility does not establish vertical compatibility. Each
source records its vertical reference and Z units independently. Sources with
unknown or incompatible vertical references are not mixed silently.

A request may supply a BBOX in another declared CRS, such as EPSG:4326. The
request geometry is transformed to the selected processing grid before tile
enumeration. Elevation models are generated in the native metric grid; an
optional publication copy may subsequently be warped with GDAL.

## From BBOX to complete tiles

Arbitrary crop boundaries are not product boundaries. Given grid origin
`(ox, oy)` and tile size `s`, an input BBOX is expanded outwards:

```text
column_min = floor((xmin - ox) / s)
column_max = ceil((xmax - ox) / s) - 1
row_min    = floor((ymin - oy) / s)
row_max    = ceil((ymax - oy) / s) - 1
```

The client may alternatively request tile identifiers directly. In both
cases, the service returns the normalized BBOX and selected tile identifiers.
Partial repository tiles are never produced.

```json
{
  "grid_id": "regcan95_utm28_1km_v1",
  "bbox": [-15.46, 28.12, -15.41, 28.16],
  "bbox_crs": "EPSG:4326",
  "snap": "outward",
  "product": "dtm"
}
```

`snap` has the closed domain `outward`; other values are rejected. This keeps
product identities stable and prevents a client from creating an overlapping,
incompatible grid.

## Tile generation

Product jobs are immutable release requests.
[`examples/product-job.json`](../examples/product-job.json) contains a BBOX
example; selection may instead use `{"all": true}` or a nonempty `tile_ids`
array.

```powershell
python -m lidar2dsm repository generate jobs\products.json
```

| Field | Contract |
|---|---|
| `repository` | Repository JSON path, relative to the product job. |
| `release_id` | New path-safe immutable release identifier. Existing releases are rejected. |
| `products` | Exactly `dtm`, `dsm`, `dtm+dsm`, or `dtm+dsm+ndsm`; nDSM cannot omit its parents. |
| `selection` | Exactly one of `all`, `tile_ids` or `bbox` plus `bbox_crs`. BBOX uses `snap: outward`. |
| `processing` | Optional explicit `Config` overrides. Grid resolution and vertical reference always come from the repository contract. |

Processing keys are `radius_m`, `idw_power`, `ground_classes`, `dsm_classes`,
`chunk_points`, `tile_pixels`, `max_tile_points`, `max_cells` and
`overview_min_size`. Their validation and omitted defaults remain owned by
`Config`; the product job does not redefine them.

For ASPRS-classified coastal PNOA data, a terrain product normally uses classes
2 (`ground`) and 9 (`water`). Class 9 represents the measured water surface,
not verified bathymetry. Slightly negative or noisy water elevations are kept
as source observations; the generator does not silently clamp them to zero or
claim that they describe the seabed. A water-flattening policy requires an
explicit hydrographic mask and is not part of the current interpolation.

For every selected output tile:

1. Query source footprints intersecting the tile plus the configured DTM halo.
2. Require a compatible horizontal CRS, Z units and vertical-reference policy.
3. Read points from every selected source without modifying those files.
4. Interpolate using the halo so border pixels have the same support rules as
   interior pixels.
5. Crop exactly to the canonical tile boundary.
6. Write the base-resolution raster with the grid CRS, transform and NoData.
7. Build internal overviews and validate dimensions, alignment and coverage.
8. Register lineage, configuration hash, source checksums and output checksum.

Elevation outputs are written under
`products/<type>/<grid>/releases/<release>/<tile>.cog.tif`. Count rasters and
the per-tile `run.json` are retained below `products/qa/`. A release-level
`release.json` records selected, completed, skipped and failed cells. A failed
tile retains its work evidence and does not stop subsequent tiles. The release
finishes as `partial` when any tile fails. A release is never silently
overwritten; use a new release identifier after changing its configuration.

Using identical boundaries is necessary but not sufficient to avoid seams:
neighbouring jobs must also use the same radius, interpolation contract and
source revisions.

## Catalogue contract

The GeoPackage contains three logical tables:

### `grid_definition`

Owns the grid fields above. A `grid_id` is immutable after products exist; a
changed origin, resolution or tile size requires a new versioned identifier.

### `lidar_source`

One record per immutable source file. It stores provider, campaign,
classification, original filename, relative path, checksum, point count,
native CRS and bounds, WGS 84 footprint, vertical-reference status and lifecycle
state. `source_coverage` distinguishes a full provider cell from a partial
coastal or boundary delivery; partial coverage is valid and does not change the
canonical output extent. Lifecycle values are `staged`, `active`, `superseded`,
`quarantined` and `archived`.

Only one source revision may be active for a provider/cell/product combination.
Invalid or contradictory metadata is quarantined rather than normalized.

### `derived_asset`

One record per product tile revision. It stores product type, grid, tile ID,
release, path, checksum, source lineage, effective parameters, coverage and
state. Lifecycle values are `building`, `active`, `superseded` and `failed`.

When a newer source becomes active, every intersecting product tile is stale.
Tiles touching the changed source through the DTM halo are stale as well. New
files are built and verified before the catalogue switches the active revision;
an active file is never overwritten in place. Product lineage is already stored
for every generated asset. Automatic regeneration scheduling after a newer
source campaign is activated remains a future orchestration feature.

## Provider tile names

Provider naming conventions are retained as metadata, not reused as canonical
tile IDs. For example, a PNOA source token such as `454-3108` may describe a
file whose header extent is X 454,000–455,000 and Y 3,107,000–3,108,000. The
repository therefore derives `E454000_N3107000` from the verified header extent.

This rule makes ingestion robust across providers, campaigns and future naming
changes.
