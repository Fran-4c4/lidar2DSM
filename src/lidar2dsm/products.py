"""Generate versioned grid tiles from a repository product-job contract."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
from uuid import uuid4

from pyproj import CRS, Transformer
import rasterio
from rasterio.shutil import copy as copy_raster

from .config import Config
from .engine import run
from .repository import (
    RepositoryConfig,
    _coordinate_token,
    _sha256,
    _unique_keys,
    init_repository,
    load_repository_config,
)


PRODUCT_ORDER = ("dtm", "dsm", "ndsm")
_PRODUCT_SETS = {
    ("dtm",): "dtm",
    ("dsm",): "dsm",
    ("dtm", "dsm"): "dsm_and_dtm",
    ("dtm", "dsm", "ndsm"): "ndsm",
}
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TILE_ID = re.compile(r"^E(?P<x>-?\d+(?:\.\d+)?)_N(?P<y>-?\d+(?:\.\d+)?)$")
_PROCESSING_FIELDS = {
    "radius_m", "idw_power", "ground_classes", "dsm_classes", "chunk_points",
    "tile_pixels", "max_tile_points", "max_cells", "overview_min_size",
}


@dataclass(frozen=True)
class ProductSelection:
    """Exactly one tile selector.

    all_tiles: true selects every canonical tile with an active source.
    tile_ids: explicit canonical lower-left IDs.
    bbox: finite [xmin,ymin,xmax,ymax], interpreted in bbox_crs and expanded
        outward to complete repository cells. snap only accepts ``outward``.
    """

    all_tiles: bool = False
    tile_ids: tuple[str, ...] | None = None
    bbox: tuple[float, float, float, float] | None = None
    bbox_crs: str | None = None
    snap: str = "outward"

    def __post_init__(self):
        if type(self.all_tiles) is not bool:
            raise ValueError("selection.all must be true or false")
        selectors = int(self.all_tiles) + int(self.tile_ids is not None) + int(self.bbox is not None)
        if selectors != 1:
            raise ValueError("selection requires exactly one of all, tile_ids or bbox")
        if self.tile_ids is not None:
            if not self.tile_ids or len(set(self.tile_ids)) != len(self.tile_ids):
                raise ValueError("selection.tile_ids must be a nonempty distinct array")
            if any(not isinstance(value, str) or not _TILE_ID.fullmatch(value) for value in self.tile_ids):
                raise ValueError("selection.tile_ids contains an invalid canonical tile ID")
            if self.bbox_crs is not None:
                raise ValueError("selection.bbox_crs is only valid with bbox")
        if self.bbox is not None:
            if (
                len(self.bbox) != 4
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in self.bbox)
                or self.bbox[0] >= self.bbox[2]
                or self.bbox[1] >= self.bbox[3]
            ):
                raise ValueError("selection.bbox must be finite with positive area")
            if not isinstance(self.bbox_crs, str) or not self.bbox_crs.strip():
                raise ValueError("selection.bbox_crs is required with bbox")
            CRS.from_user_input(self.bbox_crs)
        elif self.bbox_crs is not None:
            raise ValueError("selection.bbox_crs is only valid with bbox")
        if self.snap != "outward":
            raise ValueError("selection.snap must be outward")


@dataclass(frozen=True)
class ProductJob:
    """Versioned product request; processing defaults remain owned by Config.

    repository: repository JSON path resolved relative to this job file.
    release_id: immutable, path-safe release identity. Existing releases are
        never overwritten.
    products: one supported closed set: DTM; DSM; DTM+DSM; or all three. nDSM
        requires both parents and is never generated alone.
    selection: cells to generate.
    processing: explicit Config overrides excluding inputs, bounds, mode,
        resolution, CRS assignment and vertical reference. Omitted values use
        Config's authoritative defaults; grid resolution/reference come from
        repository.json.
    """

    repository: str
    release_id: str
    products: tuple[str, ...]
    selection: ProductSelection
    processing: dict

    def __post_init__(self):
        if not isinstance(self.repository, str) or not self.repository.strip():
            raise ValueError("repository must be a nonempty path")
        if not isinstance(self.release_id, str) or not _RELEASE_ID.fullmatch(self.release_id):
            raise ValueError("release_id must be 1-128 path-safe letters, digits, dot, underscore or dash")
        if self.products not in _PRODUCT_SETS:
            supported = "; ".join("+".join(values) for values in _PRODUCT_SETS)
            raise ValueError(f"products must be one of: {supported}")
        unknown = set(self.processing) - _PROCESSING_FIELDS
        if unknown:
            raise ValueError(f"Unknown processing keys: {', '.join(sorted(unknown))}")
        _validated_processing(self.processing, _PRODUCT_SETS[self.products])


def _validated_processing(values: dict, mode: str) -> Config:
    data = dict(values)
    for name in ("ground_classes", "dsm_classes"):
        if name in data and data[name] is not None:
            if not isinstance(data[name], (list, tuple)):
                raise ValueError(f"processing.{name} must be an array or null")
            data[name] = tuple(data[name])
    return Config(inputs=("repository-placeholder.laz",), mode=mode, **data)


def _parse_selection(data) -> ProductSelection:
    if not isinstance(data, dict):
        raise ValueError("selection must be a JSON object")
    allowed = {"all", "tile_ids", "bbox", "bbox_crs", "snap"}
    if unknown := set(data) - allowed:
        raise ValueError(f"Unknown selection keys: {', '.join(sorted(unknown))}")
    tile_ids = data.get("tile_ids")
    bbox = data.get("bbox")
    if tile_ids is not None:
        if not isinstance(tile_ids, list):
            raise ValueError("selection.tile_ids must be a JSON array")
        tile_ids = tuple(tile_ids)
    if bbox is not None:
        if not isinstance(bbox, list):
            raise ValueError("selection.bbox must be a JSON array")
        bbox = tuple(bbox)
    values = {"tile_ids": tile_ids, "bbox": bbox}
    if "all" in data:
        values["all_tiles"] = data["all"]
    if "bbox_crs" in data:
        values["bbox_crs"] = data["bbox_crs"]
    if "snap" in data:
        values["snap"] = data["snap"]
    return ProductSelection(**values)


def load_product_job(path: Path) -> ProductJob:
    """Load strict product JSON and resolve repository relative to the job."""
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    if not isinstance(data, dict):
        raise ValueError("Product job must be a JSON object")
    allowed = {f.name for f in fields(ProductJob)}
    if unknown := set(data) - allowed:
        raise ValueError(f"Unknown product job keys: {', '.join(sorted(unknown))}")
    required = {"repository", "release_id", "products", "selection"}
    if missing := required - set(data):
        raise ValueError(f"Missing product job keys: {', '.join(sorted(missing))}")
    repository = Path(data["repository"])
    if not repository.is_absolute():
        repository = (path.parent / repository).resolve()
    products = data["products"]
    if not isinstance(products, list) or not products or len(set(products)) != len(products):
        raise ValueError("products must be a nonempty distinct JSON array")
    if any(product not in PRODUCT_ORDER for product in products):
        raise ValueError("products contains an unsupported value")
    products = tuple(product for product in PRODUCT_ORDER if product in products)
    processing = data.get("processing", {})
    if not isinstance(processing, dict):
        raise ValueError("processing must be a JSON object")
    return ProductJob(
        str(repository), data["release_id"], products,
        _parse_selection(data["selection"]), processing,
    )


def _tile_id(x: float, y: float, config: RepositoryConfig) -> str:
    return config.grid.tile_id_template.format(
        xmin=_coordinate_token(x), ymin=_coordinate_token(y)
    )


def _tile_bounds(tile_id: str, config: RepositoryConfig) -> tuple[float, float, float, float]:
    match = _TILE_ID.fullmatch(tile_id)
    if not match:
        raise ValueError(f"Invalid tile ID: {tile_id}")
    x = float(match.group("x"))
    y = float(match.group("y"))
    grid = config.grid
    column = (x - grid.origin_x_m) / grid.tile_size_m
    row = (y - grid.origin_y_m) / grid.tile_size_m
    if not math.isclose(column, round(column), abs_tol=1e-9, rel_tol=0):
        raise ValueError(f"Tile X is not aligned to grid: {tile_id}")
    if not math.isclose(row, round(row), abs_tol=1e-9, rel_tol=0):
        raise ValueError(f"Tile Y is not aligned to grid: {tile_id}")
    return x, y, x + grid.tile_size_m, y + grid.tile_size_m


def _selected_tiles(job: ProductJob, config: RepositoryConfig, db: sqlite3.Connection) -> list[str]:
    selection = job.selection
    if selection.all_tiles:
        rows = db.execute(
            "SELECT DISTINCT tile_id FROM lidar_source WHERE grid_id=? AND lifecycle_state='active' ORDER BY tile_id",
            (config.grid.grid_id,),
        )
        tiles = [row[0] for row in rows]
    elif selection.tile_ids is not None:
        tiles = list(selection.tile_ids)
    else:
        source_crs = CRS.from_user_input(selection.bbox_crs)
        target_crs = CRS.from_user_input(config.grid.horizontal_crs)
        if source_crs.equals(target_crs):
            xmin, ymin, xmax, ymax = selection.bbox
        else:
            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
            xmin, ymin, xmax, ymax = transformer.transform_bounds(*selection.bbox, densify_pts=21)
        grid = config.grid
        col_min = math.floor((xmin - grid.origin_x_m) / grid.tile_size_m)
        col_max = math.ceil((xmax - grid.origin_x_m) / grid.tile_size_m) - 1
        row_min = math.floor((ymin - grid.origin_y_m) / grid.tile_size_m)
        row_max = math.ceil((ymax - grid.origin_y_m) / grid.tile_size_m) - 1
        tiles = [
            _tile_id(
                grid.origin_x_m + column * grid.tile_size_m,
                grid.origin_y_m + row * grid.tile_size_m,
                config,
            )
            for row in range(row_min, row_max + 1)
            for column in range(col_min, col_max + 1)
        ]
    if not tiles:
        raise ValueError("Product selection contains no tiles")
    for tile in tiles:
        _tile_bounds(tile, config)
    return sorted(tiles)


def _source_rows(
    db: sqlite3.Connection, config: RepositoryConfig,
    bounds: tuple[float, float, float, float], halo: float,
) -> list[dict]:
    xmin, ymin, xmax, ymax = bounds
    cursor = db.execute(
        """SELECT source_id,relative_path,sha256,xmin,ymin,xmax,ymax
           FROM lidar_source
           WHERE grid_id=? AND horizontal_crs=? AND lifecycle_state='active'
             AND xmax >= ? AND xmin <= ? AND ymax >= ? AND ymin <= ?
           ORDER BY source_id""",
        (config.grid.grid_id, CRS.from_user_input(config.grid.horizontal_crs).to_string(),
         xmin - halo, xmax + halo, ymin - halo, ymax + halo),
    )
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _effective_config(
    job: ProductJob, repository: RepositoryConfig, inputs: list[str],
    bounds: tuple[float, float, float, float],
) -> Config:
    processing = _validated_processing(job.processing, _PRODUCT_SETS[job.products])
    values = processing.to_dict()
    for key in ("inputs", "mode", "resolution_m", "vertical_reference", "bounds"):
        values.pop(key)
    return Config(
        inputs=tuple(inputs), mode=_PRODUCT_SETS[job.products],
        resolution_m=repository.grid.resolution_m,
        vertical_reference=repository.grid.vertical_reference,
        bounds=bounds, **values,
    )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.incoming")
    try:
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_remove_work(path: Path, repository_root: Path) -> None:
    work_root = (repository_root / "work").resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(work_root)
    except ValueError as error:
        raise RuntimeError(f"Refusing to remove a path outside repository work: {resolved}") from error
    if resolved.exists():
        shutil.rmtree(resolved)


def _write_cog(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.incoming")
    try:
        with rasterio.open(source) as dataset:
            copy_raster(
                dataset, temporary, driver="COG", BLOCKSIZE=512,
                COMPRESS="DEFLATE", BIGTIFF="IF_SAFER",
                OVERVIEWS="AUTO", RESAMPLING="AVERAGE",
            )
        with rasterio.open(temporary) as result:
            if not result.profile.get("tiled") or result.crs is None:
                raise RuntimeError(f"COG validation failed: {destination.name}")
            layout = result.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
            if layout not in (None, "COG"):
                raise RuntimeError(f"Unexpected GeoTIFF layout: {layout}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _register_assets(
    catalog: Path, job: ProductJob, config: RepositoryConfig, tile_id: str,
    sources: list[dict], effective: Config, manifest: dict, paths: dict[str, Path],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    lineage = json.dumps([row["source_id"] for row in sources], separators=(",", ":"))
    effective_values = effective.to_dict()
    effective_values.pop("inputs")
    effective_json = json.dumps(effective_values, separators=(",", ":"))
    with sqlite3.connect(catalog) as db:
        db.execute("BEGIN IMMEDIATE")
        for product, path in paths.items():
            asset_id = f"{product}:{config.grid.grid_id}:{tile_id}:{job.release_id}"
            if db.execute("SELECT 1 FROM derived_asset WHERE asset_id=?", (asset_id,)).fetchone():
                raise ValueError(f"Derived asset already exists: {asset_id}")
            db.execute(
                """UPDATE derived_asset SET lifecycle_state='superseded'
                   WHERE product_type=? AND grid_id=? AND tile_id=? AND lifecycle_state='active'""",
                (product, config.grid.grid_id, tile_id),
            )
            relative = path.relative_to(config.root).as_posix()
            coverage = manifest["outputs"][product]["coverage_fraction"]
            db.execute(
                """INSERT INTO derived_asset(
                     asset_id,product_type,grid_id,tile_id,release_id,relative_path,
                     sha256,source_lineage_json,effective_config_json,coverage_fraction,
                     lifecycle_state,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (asset_id, product, config.grid.grid_id, tile_id, job.release_id,
                 relative, _sha256(path), lineage, effective_json, coverage, "active", now),
            )
        db.commit()


def generate_products(job_path: Path, progress=print) -> dict:
    """Generate immutable COG tiles and register successful assets."""
    job_path = job_path.resolve()
    job = load_product_job(job_path)
    repository = load_repository_config(Path(job.repository))
    init_repository(repository)
    root = repository.root.resolve()
    catalog = root / "catalog" / "catalog.gpkg"
    release_root = root / "products" / "releases" / repository.grid.grid_id / job.release_id
    release_manifest = release_root / "release.json"
    if release_root.exists():
        raise ValueError(f"Release already exists; choose a new release_id: {release_root}")
    release_root.mkdir(parents=True)
    with sqlite3.connect(catalog) as db:
        tiles = _selected_tiles(job, repository, db)
    release = {
        "schema_version": 1,
        "status": "running",
        "release_id": job.release_id,
        "grid_id": repository.grid.grid_id,
        "job_file": str(job_path),
        "products": list(job.products),
        "selected_tiles": tiles,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "tiles": {},
    }
    _write_json(release_manifest, release)
    try:
        for index, tile_id in enumerate(tiles, start=1):
            progress(f"[{index}/{len(tiles)}] {tile_id}: selecting sources")
            bounds = _tile_bounds(tile_id, repository)
            processing = _validated_processing(job.processing, _PRODUCT_SETS[job.products])
            with sqlite3.connect(catalog) as db:
                sources = _source_rows(db, repository, bounds, processing.radius_m)
            if not sources:
                release["tiles"][tile_id] = {"status": "skipped_no_sources", "bounds": bounds}
                _write_json(release_manifest, release)
                continue
            input_paths = [str(root / Path(row["relative_path"])) for row in sources]
            for path, source in zip(input_paths, sources):
                if not Path(path).is_file():
                    raise ValueError(f"Catalogued source is missing: {source['relative_path']}")
            effective = _effective_config(job, repository, input_paths, bounds)
            work = root / "work" / "generate" / job.release_id / tile_id
            if work.exists():
                raise ValueError(f"Work directory already exists: {work}")
            progress(f"[{index}/{len(tiles)}] {tile_id}: generating {', '.join(job.products)}")
            try:
                manifest = run(
                    effective, work,
                    progress=lambda message: progress(f"  {message}"),
                )
            except (ValueError, OSError, RuntimeError) as tile_error:
                release["tiles"][tile_id] = {
                    "status": "failed",
                    "bounds": bounds,
                    "sources": [row["source_id"] for row in sources],
                    "error": str(tile_error),
                    "work": work.relative_to(root).as_posix(),
                }
                _write_json(release_manifest, release)
                progress(f"[{index}/{len(tiles)}] {tile_id}: failed: {tile_error}")
                continue
            output_paths = {}
            for product in job.products:
                destination = (
                    root / "products" / product / repository.grid.grid_id /
                    "releases" / job.release_id / f"{tile_id}.cog.tif"
                )
                if destination.exists():
                    raise ValueError(f"Product already exists: {destination}")
                _write_cog(work / f"{product}.tif", destination)
                output_paths[product] = destination
            qa = root / "products" / "qa" / repository.grid.grid_id / "releases" / job.release_id / tile_id
            qa.mkdir(parents=True, exist_ok=False)
            for name in ("run.json", "point_count.tif", "ground_count.tif", "dsm_count.tif", "dtm_support.tif"):
                source = work / name
                if source.exists():
                    shutil.copy2(source, qa / name)
            _register_assets(catalog, job, repository, tile_id, sources, effective, manifest, output_paths)
            release["tiles"][tile_id] = {
                "status": "complete", "bounds": bounds,
                "sources": [row["source_id"] for row in sources],
                "outputs": {name: path.relative_to(root).as_posix() for name, path in output_paths.items()},
                "qa": qa.relative_to(root).as_posix(),
            }
            _write_json(release_manifest, release)
            _safe_remove_work(work, root)
        failed = sum(
            1 for tile in release["tiles"].values()
            if tile.get("status") == "failed"
        )
        release["status"] = "partial" if failed else "complete"
        release["failed_tiles"] = failed
        release["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(release_manifest, release)
        progress(f"Release complete: {release_manifest}")
        return release
    except Exception as error:
        release["status"] = "failed"
        release["error"] = str(error)
        release["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(release_manifest, release)
        raise
