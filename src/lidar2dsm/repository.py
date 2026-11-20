"""Persistent source catalogue and grid-aligned repository management.

RepositoryConfig is the sole owner of the repository JSON contract. Processing
Config remains independent: repository ingestion never changes raster defaults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
from typing import Iterable
from uuid import uuid4

import laspy
from pyproj import CRS, Transformer


TRANSFER_MODES = ("copy", "move")
DEFAULT_TRANSFER_MODE = "copy"
SOURCE_PROFILES = ("pnoa",)
PRODUCT_TYPES = ("dtm", "dsm", "ndsm")
_PNOA_NAME = re.compile(
    r"^PNOA_(?P<campaign>\d{4})_(?P<region>[A-Z]+)_"
    r"(?P<east>\d+)-(?P<north>\d+)_H(?P<zone>\d+)_"
    r"(?P<classification>[A-Z0-9]+)\.(?:las|laz)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GridDefinition:
    """Authoritative metric tile grid stored in ``grid_definition``.

    grid_id: immutable versioned identity. Change it when origin, tile size,
        resolution, horizontal CRS or vertical-reference policy changes.
    horizontal_crs: projected CRS authority/user string. It must use metres;
        ingestion rejects missing, geographic, Web Mercator, feet and
        contradictory LAS/LAZ header CRS values. Coordinates are not transformed.
    origin_x_m, origin_y_m: finite grid origin in CRS metres. They define tile
        indices and remain fixed for the lifetime of the grid.
    tile_size_m: positive square tile edge in metres. PNOA ingestion currently
        requires 1,000 m because its filename/cell validation is 1 km based.
    resolution_m: positive base raster pixel size in metres. Tile size must be
        an integer multiple. This is stored for future products; ingestion does
        not rasterize or reinterpret source accuracy.
    vertical_reference: nonempty Z provenance label. ``unknown`` preserves
        uncertainty and is never replaced from the horizontal CRS.
    tile_id_template: fixed ``E{xmin}_N{ymin}`` identity. The lower-left grid
        boundary, not a provider filename or city, owns a tile's identity.
    """

    grid_id: str
    horizontal_crs: str
    origin_x_m: float
    origin_y_m: float
    tile_size_m: float
    resolution_m: float
    vertical_reference: str
    tile_id_template: str = "E{xmin}_N{ymin}"

    def __post_init__(self):
        for name in ("grid_id", "horizontal_crs", "vertical_reference"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"grid.{name} must be a nonempty string")
        for name in ("origin_x_m", "origin_y_m"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"grid.{name} must be finite metres")
        for name in ("tile_size_m", "resolution_m"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"grid.{name} must be positive finite metres")
        pixels = self.tile_size_m / self.resolution_m
        if not math.isclose(pixels, round(pixels), rel_tol=0, abs_tol=1e-9):
            raise ValueError("grid.tile_size_m must be an integer multiple of resolution_m")
        if self.tile_id_template != "E{xmin}_N{ymin}":
            raise ValueError("grid.tile_id_template must be E{xmin}_N{ymin}")
        crs = CRS.from_user_input(self.horizontal_crs)
        if not crs.is_projected or crs.to_epsg() == 3857:
            raise ValueError("grid.horizontal_crs must be a projected non-Web-Mercator CRS")
        units = {axis.unit_name.lower() for axis in crs.axis_info if axis.unit_name}
        if units != {"metre"}:
            raise ValueError("grid.horizontal_crs axes must use metres")


@dataclass(frozen=True)
class RepositoryConfig:
    """Repository JSON contract and change impact.

    repository_root: destination root, resolved relative to the JSON file. Init
        creates its catalogue/source/product/work layout; ingest never searches
        outside an explicitly supplied input directory.
    source_profile: closed provider parser domain. ``pnoa`` validates the PNOA
        filename, LAS/LAZ header, UTM zone and one-kilometre source cell before
        deriving provider/campaign destination folders.
    grid: the single GridDefinition used by this repository configuration.

    Unknown/duplicate keys and contradictory values are rejected. Transfer mode
    is deliberately a CLI operation setting: ``copy`` is the safe default and
    ``move`` removes an input only after its destination and catalogue commit.
    """

    repository_root: str
    source_profile: str
    grid: GridDefinition

    def __post_init__(self):
        if not isinstance(self.repository_root, str) or not self.repository_root.strip():
            raise ValueError("repository_root must be a nonempty path")
        if self.source_profile not in SOURCE_PROFILES:
            raise ValueError(f"source_profile must be one of: {', '.join(SOURCE_PROFILES)}")
        if self.source_profile == "pnoa" and not math.isclose(
            self.grid.tile_size_m, 1000.0, rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError("the pnoa source profile requires grid.tile_size_m = 1000")

    @property
    def root(self) -> Path:
        return Path(self.repository_root)

    def portable_dict(self) -> dict:
        return {
            "repository_root": ".",
            "source_profile": self.source_profile,
            "grid": asdict(self.grid),
        }


@dataclass(frozen=True)
class ImportJob:
    """Reproducible source-ingestion request.

    repository: repository JSON path, resolved relative to this job file.
    input_directory: recursively searched directory outside the repository,
        also resolved relative to the job file.
    transfer_mode: ``copy`` keeps inputs; ``move`` removes each input only after
        destination checksum verification and catalogue commit. Default: copy.
    """

    repository: str
    input_directory: str
    transfer_mode: str = DEFAULT_TRANSFER_MODE

    def __post_init__(self):
        for name in ("repository", "input_directory"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty path")
        if self.transfer_mode not in TRANSFER_MODES:
            raise ValueError(f"transfer_mode must be one of: {', '.join(TRANSFER_MODES)}")


@dataclass(frozen=True)
class _PreparedSource:
    input_path: Path
    destination: Path
    properties: dict
    geometry: bytes


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate repository configuration key: {key}")
        result[key] = value
    return result


def load_repository_config(path: Path) -> RepositoryConfig:
    """Load strict repository JSON; relative root uses the configuration directory."""
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    if not isinstance(data, dict):
        raise ValueError("Repository configuration must be a JSON object")
    allowed = {f.name for f in fields(RepositoryConfig)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown repository keys: {', '.join(sorted(unknown))}")
    if set(data) != allowed:
        missing = allowed - set(data)
        raise ValueError(f"Missing repository keys: {', '.join(sorted(missing))}")
    grid_data = data["grid"]
    if not isinstance(grid_data, dict):
        raise ValueError("grid must be a JSON object")
    grid_allowed = {f.name for f in fields(GridDefinition)}
    unknown_grid = set(grid_data) - grid_allowed
    if unknown_grid:
        raise ValueError(f"Unknown grid keys: {', '.join(sorted(unknown_grid))}")
    required_grid = grid_allowed - {"tile_id_template"}
    missing_grid = required_grid - set(grid_data)
    if missing_grid:
        raise ValueError(f"Missing grid keys: {', '.join(sorted(missing_grid))}")
    root = Path(data["repository_root"])
    if not root.is_absolute():
        root = (path.parent / root).resolve()
    return RepositoryConfig(str(root), data["source_profile"], GridDefinition(**grid_data))


def load_import_job(path: Path) -> ImportJob:
    """Load a strict import job and resolve both paths relative to its JSON."""
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    if not isinstance(data, dict):
        raise ValueError("Import job must be a JSON object")
    allowed = {f.name for f in fields(ImportJob)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown import job keys: {', '.join(sorted(unknown))}")
    required = {"repository", "input_directory"}
    if missing := required - set(data):
        raise ValueError(f"Missing import job keys: {', '.join(sorted(missing))}")
    for name in ("repository", "input_directory"):
        value = Path(data[name])
        if not value.is_absolute():
            value = (path.parent / value).resolve()
        data[name] = str(value)
    return ImportJob(**data)


def run_import_job(path: Path, progress=lambda message: None) -> dict:
    job = load_import_job(path)
    config = load_repository_config(Path(job.repository))
    return ingest_repository(
        config, Path(job.input_directory), job.transfer_mode, progress=progress
    )


def _repository_readme(config: RepositoryConfig) -> str:
    grid = config.grid
    pixels = round(grid.tile_size_m / grid.resolution_m)
    return f"""# Local LiDAR repository

This directory contains immutable source point clouds, a GeoPackage catalogue
and versioned grid-aligned elevation products.

## Structure

```text
catalog/catalog.gpkg             authoritative grids, sources and products
repository.json                  repository and grid contract
jobs/                            reproducible import and product requests
source/<provider>/<campaign>/... immutable LAS/LAZ deliveries
products/dtm/<grid>/releases/    versioned terrain tiles
products/dsm/<grid>/releases/    versioned surface tiles
products/ndsm/<grid>/releases/   versioned height-above-ground tiles
work/                            disposable processing files
```

Source files keep their provider names. Canonical tile IDs come from verified
header bounds and use the lower-left metric boundary, never a city name.

## Active grid

- ID: `{grid.grid_id}`
- Horizontal CRS: `{grid.horizontal_crs}`
- Vertical reference: `{grid.vertical_reference}`
- Tile edge: {grid.tile_size_m:g} m
- Base resolution: {grid.resolution_m:g} m
- Raster dimensions: {pixels} x {pixels} pixels

Use `lidar2dsm repository ingest repository.json <input-directory>` to copy new
deliveries. Add `--mode move` only when the input files should be removed after
their copied bytes and catalogue transaction have both been verified.

For a guided workflow from a source checkout, run `start_lidar2dsm.cmd` on
Windows or `python start_lidar2dsm.py` on Linux/macOS. Import and product jobs
can also be executed non-interactively from JSON files.
"""


def init_repository(config: RepositoryConfig) -> dict:
    """Create or validate an idempotent repository without overwriting content."""
    root = config.root.resolve()
    directories = [root / "catalog", root / "jobs", root / "source", root / "work"]
    directories.extend(
        root / "products" / product / config.grid.grid_id / "releases"
        for product in PRODUCT_TYPES
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(_repository_readme(config), encoding="utf-8")
    local_config = root / "repository.json"
    effective = json.dumps(config.portable_dict(), indent=2) + "\n"
    if not local_config.exists():
        local_config.write_text(effective, encoding="utf-8")
    else:
        local = load_repository_config(local_config)
        if local.source_profile != config.source_profile or local.grid != config.grid:
            raise ValueError("Existing repository.json contradicts the requested repository contract")

    catalog = root / "catalog" / "catalog.gpkg"
    if catalog.exists():
        _validate_catalog(catalog, config.grid)
        created = False
    else:
        temporary = catalog.with_name(f".{catalog.name}.{uuid4().hex}.incoming")
        try:
            _create_catalog(temporary, config.grid)
            os.replace(temporary, catalog)
        finally:
            temporary.unlink(missing_ok=True)
        created = True
    return {
        "status": "initialized",
        "repository": str(root),
        "catalog_created": created,
        "grid_id": config.grid.grid_id,
    }


def _create_catalog(path: Path, grid: GridDefinition) -> None:
    wgs84 = CRS.from_epsg(4326)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA application_id=1196437808")
        db.execute("PRAGMA user_version=10300")
        db.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (
          srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
          organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
          definition TEXT NOT NULL, description TEXT);
        CREATE TABLE gpkg_contents (
          table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
          identifier TEXT UNIQUE, description TEXT DEFAULT '',
          last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (
          table_name TEXT NOT NULL, column_name TEXT NOT NULL,
          geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
          z TINYINT NOT NULL, m TINYINT NOT NULL,
          PRIMARY KEY (table_name, column_name));
        CREATE TABLE grid_definition (
          grid_id TEXT PRIMARY KEY NOT NULL, horizontal_crs TEXT NOT NULL,
          origin_x_m REAL NOT NULL, origin_y_m REAL NOT NULL,
          tile_size_m REAL NOT NULL CHECK(tile_size_m > 0),
          resolution_m REAL NOT NULL CHECK(resolution_m > 0),
          vertical_reference TEXT NOT NULL, tile_id_template TEXT NOT NULL,
          contract_version INTEGER NOT NULL CHECK(contract_version > 0));
        CREATE TABLE lidar_source (
          fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB, source_id TEXT NOT NULL UNIQUE,
          provider TEXT NOT NULL, campaign TEXT NOT NULL, region TEXT NOT NULL,
          utm_zone INTEGER NOT NULL, classification TEXT NOT NULL,
          source_filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
          sha256 TEXT NOT NULL UNIQUE, file_bytes INTEGER NOT NULL,
          point_count INTEGER NOT NULL, horizontal_crs TEXT NOT NULL,
          vertical_reference TEXT NOT NULL, crs_status TEXT NOT NULL,
          grid_id TEXT NOT NULL, tile_id TEXT NOT NULL,
          source_coverage TEXT NOT NULL CHECK(source_coverage IN ('full','partial')),
          xmin REAL NOT NULL, ymin REAL NOT NULL, xmax REAL NOT NULL, ymax REAL NOT NULL,
          zmin REAL NOT NULL, zmax REAL NOT NULL,
          lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN
            ('staged','active','superseded','quarantined','archived')),
          ingested_at TEXT NOT NULL);
        CREATE TABLE derived_asset (
          asset_id TEXT PRIMARY KEY NOT NULL,
          product_type TEXT NOT NULL CHECK(product_type IN ('dtm','dsm','ndsm')),
          grid_id TEXT NOT NULL, tile_id TEXT NOT NULL, release_id TEXT NOT NULL,
          relative_path TEXT NOT NULL, sha256 TEXT,
          source_lineage_json TEXT NOT NULL, effective_config_json TEXT NOT NULL,
          coverage_fraction REAL CHECK(coverage_fraction BETWEEN 0 AND 1),
          lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN
            ('building','active','superseded','failed')),
          created_at TEXT NOT NULL,
          UNIQUE(product_type, grid_id, tile_id, release_id));
        CREATE INDEX ix_lidar_source_bbox ON lidar_source(xmin, xmax, ymin, ymax);
        CREATE UNIQUE INDEX uq_lidar_source_active_cell
          ON lidar_source(provider, grid_id, tile_id, classification)
          WHERE lifecycle_state = 'active';
        CREATE UNIQUE INDEX uq_derived_asset_active
          ON derived_asset(product_type, grid_id, tile_id)
          WHERE lifecycle_state = 'active';
        """)
        db.executemany(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
            [
                ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined Cartesian"),
                ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic"),
                ("WGS 84 geodetic", 4326, "EPSG", 4326, wgs84.to_wkt(), "longitude/latitude search footprints"),
            ],
        )
        now = _utc_now()
        db.executemany(
            "INSERT INTO gpkg_contents(table_name,data_type,identifier,description,last_change,srs_id) VALUES (?,?,?,?,?,?)",
            [
                ("grid_definition", "attributes", "grid_definition", "Authoritative metric processing grids", now, None),
                ("lidar_source", "features", "lidar_source", "Immutable source point-cloud catalogue", now, 4326),
                ("derived_asset", "attributes", "derived_asset", "Versioned grid-aligned elevation products", now, None),
            ],
        )
        db.execute("INSERT INTO gpkg_geometry_columns VALUES ('lidar_source','geom','POLYGON',4326,0,0)")
        _insert_grid(db, grid)
        db.commit()
    finally:
        db.close()


def _grid_values(grid: GridDefinition) -> tuple:
    return (
        grid.grid_id, CRS.from_user_input(grid.horizontal_crs).to_string(),
        float(grid.origin_x_m), float(grid.origin_y_m), float(grid.tile_size_m),
        float(grid.resolution_m), grid.vertical_reference, grid.tile_id_template, 1,
    )


def _insert_grid(db: sqlite3.Connection, grid: GridDefinition) -> None:
    db.execute("INSERT INTO grid_definition VALUES (?,?,?,?,?,?,?,?,?)", _grid_values(grid))


def _validate_catalog(path: Path, grid: GridDefinition) -> None:
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"gpkg_contents", "gpkg_geometry_columns", "grid_definition", "lidar_source", "derived_asset"}
        if missing := required - tables:
            raise ValueError(f"Repository catalogue is missing tables: {', '.join(sorted(missing))}")
        row = db.execute("SELECT * FROM grid_definition WHERE grid_id=?", (grid.grid_id,)).fetchone()
        if row is None:
            raise ValueError(f"Repository catalogue does not define grid {grid.grid_id}")
        expected = _grid_values(grid)
        if tuple(row) != expected:
            raise ValueError("Catalogue grid_definition contradicts repository.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _boundary_ring(minx: float, miny: float, maxx: float, maxy: float, steps: int = 8):
    points = []
    for index in range(steps):
        points.append((minx + (maxx - minx) * index / steps, miny))
    for index in range(steps):
        points.append((maxx, miny + (maxy - miny) * index / steps))
    for index in range(steps):
        points.append((maxx - (maxx - minx) * index / steps, maxy))
    for index in range(steps):
        points.append((minx, maxy - (maxy - miny) * index / steps))
    points.append(points[0])
    return points


def _coordinate_token(value: float) -> str:
    """Stable non-scientific tile token; integral metric grids stay readable."""
    return f"{value:.12f}".rstrip("0").rstrip(".")


def _gpkg_polygon(ring: list[tuple[float, float]], srs_id: int) -> bytes:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    header = b"GP" + bytes((0, 3)) + struct.pack("<i4d", srs_id, min(xs), max(xs), min(ys), max(ys))
    wkb = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring))
    wkb += b"".join(struct.pack("<2d", x, y) for x, y in ring)
    return header + wkb


def _gpkg_envelope(blob: bytes | None):
    if not blob or len(blob) < 40 or blob[:2] != b"GP":
        return None
    endian = "<" if blob[3] & 1 else ">"
    envelope_type = (blob[3] >> 1) & 7
    if envelope_type == 0:
        return None
    return struct.unpack_from(f"{endian}4d", blob, 8)


def _register_spatial_functions(db: sqlite3.Connection) -> None:
    db.create_function("ST_IsEmpty", 1, lambda blob: 1 if not blob else 0)
    db.create_function("ST_MinX", 1, lambda blob: _gpkg_envelope(blob)[0])
    db.create_function("ST_MaxX", 1, lambda blob: _gpkg_envelope(blob)[1])
    db.create_function("ST_MinY", 1, lambda blob: _gpkg_envelope(blob)[2])
    db.create_function("ST_MaxY", 1, lambda blob: _gpkg_envelope(blob)[3])


def _catalog_srs_id(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT srs_id FROM gpkg_geometry_columns WHERE table_name='lidar_source' AND column_name='geom'"
    ).fetchone()
    if row is None:
        raise ValueError("lidar_source geometry contract is missing")
    return int(row[0])


def _discover_sources(input_directory: Path) -> list[Path]:
    if not input_directory.is_dir():
        raise ValueError(f"Input directory does not exist: {input_directory}")
    paths = sorted(
        path.resolve() for path in input_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in (".las", ".laz")
    )
    if not paths:
        raise ValueError(f"Input directory contains no LAS/LAZ files: {input_directory}")
    return paths


def _prepare_pnoa(path: Path, config: RepositoryConfig, srs_id: int) -> _PreparedSource:
    match = _PNOA_NAME.match(path.name)
    if not match:
        raise ValueError(f"PNOA filename does not match the supported contract: {path.name}")
    grid = config.grid
    declared = CRS.from_user_input(grid.horizontal_crs)
    with laspy.open(path) as reader:
        header = reader.header
        source_crs = header.parse_crs()
        if source_crs is None:
            raise ValueError(f"Source header has no CRS: {path.name}")
        if not source_crs.equals(declared):
            raise ValueError(f"Source CRS {source_crs.to_string()} contradicts {declared.to_string()}: {path.name}")
        minx, miny, minz = map(float, header.mins)
        maxx, maxy, maxz = map(float, header.maxs)
        point_count = int(header.point_count)
    zone = int(match.group("zone"))
    crs_zone = source_crs.utm_zone
    if crs_zone and int(re.match(r"\d+", crs_zone).group()) != zone:
        raise ValueError(f"Filename UTM zone H{zone} contradicts source CRS zone {crs_zone}: {path.name}")
    column = math.floor((minx - grid.origin_x_m) / grid.tile_size_m)
    row = math.floor((miny - grid.origin_y_m) / grid.tile_size_m)
    tile_x = grid.origin_x_m + column * grid.tile_size_m
    tile_y = grid.origin_y_m + row * grid.tile_size_m
    tolerance = 0.02
    if maxx > tile_x + grid.tile_size_m + tolerance or maxy > tile_y + grid.tile_size_m + tolerance:
        raise ValueError(f"Source spans more than one canonical tile: {path.name}")
    expected_east = round(tile_x / 1000)
    expected_north = round((tile_y + grid.tile_size_m) / 1000)
    if int(match.group("east")) != expected_east or int(match.group("north")) != expected_north:
        raise ValueError(f"Provider cell token contradicts LAS/LAZ header bounds: {path.name}")
    full = all((
        abs(minx - tile_x) <= tolerance,
        abs(miny - tile_y) <= tolerance,
        abs(maxx - (tile_x + grid.tile_size_m - 0.001)) <= tolerance,
        abs(maxy - (tile_y + grid.tile_size_m - 0.001)) <= tolerance,
    ))
    tile_id = grid.tile_id_template.format(
        xmin=_coordinate_token(tile_x), ymin=_coordinate_token(tile_y)
    )
    campaign = match.group("campaign")
    classification = match.group("classification").upper()
    provider = "PNOA"
    destination = (
        config.root / "source" / provider.lower() / campaign /
        match.group("region").lower() / f"h{zone}" / classification.lower() / path.name
    )
    checksum = _sha256(path)
    transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
    ring = [transformer.transform(x, y) for x, y in _boundary_ring(minx, miny, maxx, maxy)]
    properties = {
        "source_id": f"{provider.lower()}:{campaign}:{declared.to_string().lower().replace(':', '')}:{tile_id}:{classification.lower()}",
        "provider": provider,
        "campaign": campaign,
        "region": match.group("region").upper(),
        "utm_zone": zone,
        "classification": classification,
        "source_filename": path.name,
        "relative_path": destination.relative_to(config.root).as_posix(),
        "sha256": checksum,
        "file_bytes": path.stat().st_size,
        "point_count": point_count,
        "horizontal_crs": declared.to_string(),
        "vertical_reference": grid.vertical_reference,
        "crs_status": "header_verified",
        "grid_id": grid.grid_id,
        "tile_id": tile_id,
        "source_coverage": "full" if full else "partial",
        "xmin": minx, "ymin": miny, "xmax": maxx, "ymax": maxy,
        "zmin": minz, "zmax": maxz,
        "lifecycle_state": "active",
        "ingested_at": _utc_now(),
    }
    return _PreparedSource(path, destination, properties, _gpkg_polygon(ring, srs_id))


def _prepare_sources(
    paths: Iterable[Path], config: RepositoryConfig, srs_id: int,
    progress=lambda message: None,
):
    paths = list(paths)
    prepared = []
    for index, path in enumerate(paths, start=1):
        progress(f"[{index}/{len(paths)}] Reading header and SHA-256: {path.name}")
        prepared.append(_prepare_pnoa(path, config, srs_id))
    identities = [source.properties["source_id"] for source in prepared]
    if len(identities) != len(set(identities)):
        raise ValueError("Input directory contains duplicate logical source identities")
    return prepared


def ingest_repository(
    config: RepositoryConfig, input_directory: Path,
    transfer_mode: str = DEFAULT_TRANSFER_MODE,
    progress=lambda message: None,
) -> dict:
    """Preflight, transfer, checksum and transactionally register a directory."""
    if transfer_mode not in TRANSFER_MODES:
        raise ValueError(f"transfer_mode must be one of: {', '.join(TRANSFER_MODES)}")
    root = config.root.resolve()
    input_directory = input_directory.resolve()
    try:
        input_directory.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("Input directory must be outside the destination repository")
    init_repository(config)
    catalog = root / "catalog" / "catalog.gpkg"
    paths = _discover_sources(input_directory)
    progress(f"Found {len(paths)} LAS/LAZ files. Validating the complete batch before transfer.")
    with sqlite3.connect(catalog) as db:
        srs_id = _catalog_srs_id(db)
    prepared = _prepare_sources(paths, config, srs_id, progress)

    with sqlite3.connect(catalog) as db:
        known_hashes = {
            row[0]: row[1] for row in db.execute("SELECT sha256,relative_path FROM lidar_source")
        }
        known_identities = {
            row[0]: row[1] for row in db.execute("SELECT source_id,sha256 FROM lidar_source")
        }
        active = {
            (row[0], row[1], row[2], row[3]): (row[4], row[5])
            for row in db.execute(
                "SELECT provider,grid_id,tile_id,classification,campaign,source_id FROM lidar_source WHERE lifecycle_state='active'"
            )
        }

    duplicates = []
    additions = []
    for source in prepared:
        props = source.properties
        if props["sha256"] in known_hashes:
            registered = root / Path(known_hashes[props["sha256"]])
            if registered.resolve() != source.destination.resolve():
                raise ValueError(
                    f"Duplicate checksum resolves to a different repository path: {source.input_path.name}"
                )
            duplicates.append(source)
            continue
        previous_hash = known_identities.get(props["source_id"])
        if previous_hash and previous_hash != props["sha256"]:
            raise ValueError(f"Same logical source identity has different bytes: {source.input_path.name}")
        key = (props["provider"], props["grid_id"], props["tile_id"], props["classification"])
        previous = active.get(key)
        if previous and int(props["campaign"]) < int(previous[0]):
            props["lifecycle_state"] = "superseded"
        additions.append(source)

    created_files = []
    try:
        transfers = [*additions, *duplicates]
        for index, source in enumerate(transfers, start=1):
            action = "Copying" if not source.destination.exists() else "Verifying destination"
            progress(f"[{index}/{len(transfers)}] {action}: {source.input_path.name}")
            source.destination.parent.mkdir(parents=True, exist_ok=True)
            if source.destination.exists():
                if _sha256(source.destination) != source.properties["sha256"]:
                    raise ValueError(f"Destination exists with different bytes: {source.destination}")
                continue
            temporary = source.destination.with_name(f".{source.destination.name}.{uuid4().hex}.incoming")
            try:
                shutil.copy2(source.input_path, temporary)
                if _sha256(temporary) != source.properties["sha256"]:
                    raise RuntimeError(f"Transferred checksum differs: {source.input_path.name}")
                os.replace(temporary, source.destination)
                created_files.append(source.destination)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise

    inserted = 0
    activated = 0
    superseded = 0
    try:
        progress(
            f"Updating catalogue: {len(additions)} new, {len(duplicates)} duplicate."
        )
        with sqlite3.connect(catalog) as db:
            _register_spatial_functions(db)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            for source in additions:
                props = source.properties
                if props["lifecycle_state"] == "active":
                    changed = db.execute(
                        """UPDATE lidar_source SET lifecycle_state='superseded'
                           WHERE provider=? AND grid_id=? AND tile_id=? AND classification=?
                             AND lifecycle_state='active' AND CAST(campaign AS INTEGER) < ?""",
                        (props["provider"], props["grid_id"], props["tile_id"],
                         props["classification"], int(props["campaign"])),
                    ).rowcount
                    superseded += changed
                    remaining = db.execute(
                        """SELECT campaign FROM lidar_source
                           WHERE provider=? AND grid_id=? AND tile_id=? AND classification=?
                             AND lifecycle_state='active'""",
                        (props["provider"], props["grid_id"], props["tile_id"], props["classification"]),
                    ).fetchone()
                    if remaining and int(remaining[0]) >= int(props["campaign"]):
                        props["lifecycle_state"] = "superseded"
                    else:
                        activated += 1
                columns = ["geom", *props.keys()]
                values = [sqlite3.Binary(source.geometry), *props.values()]
                placeholders = ",".join("?" for _ in columns)
                db.execute(
                    f"INSERT INTO lidar_source ({','.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                inserted += 1
            db.commit()
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise

    removed_inputs = 0
    move_warnings = []
    if transfer_mode == "move":
        progress("Catalogue committed. Removing verified input files requested by move mode.")
        for source in [*additions, *duplicates]:
            if source.input_path.resolve() == source.destination.resolve():
                continue
            try:
                source.input_path.unlink()
                removed_inputs += 1
            except OSError as error:
                move_warnings.append(f"Could not remove {source.input_path}: {error}")

    result = {
        "status": "complete",
        "repository": str(root),
        "input_directory": str(input_directory),
        "transfer_mode": transfer_mode,
        "discovered": len(prepared),
        "ingested": inserted,
        "duplicates": len(duplicates),
        "activated": activated,
        "superseded": superseded,
        "copied_files": len(created_files),
        "removed_inputs": removed_inputs,
        "warnings": move_warnings,
    }
    progress(
        f"Import complete: {inserted} ingested, {len(duplicates)} duplicate, "
        f"{len(created_files)} copied."
    )
    return result
