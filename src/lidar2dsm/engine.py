"""Chunked LAS ingestion, disk spatial buckets, windowed metric rasters."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile

import laspy
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from scipy.spatial import cKDTree

from . import __version__
from .config import Config
from .grid import inspect


def _dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _overview_factors(width: int, height: int, minimum_size: int | None) -> list[int]:
    """Return power-of-two display levels without changing the base grid.

    ``minimum_size`` targets the longest side; it is not a crop or a new base
    resolution. None and rasters already within the target produce no levels.
    """
    longest = max(width, height)
    if minimum_size is None or longest <= minimum_size:
        return []
    factors, factor = [], 2
    while factor <= longest:
        factors.append(factor)
        if math.ceil(longest / factor) <= minimum_size:
            break
        factor *= 2
    return factors


def _build_elevation_overviews(path: Path, factors: list[int]) -> None:
    """Append average-resampled internal IFDs for visual clients only."""
    if not factors:
        return
    with rasterio.open(path, "r+") as raster:
        raster.build_overviews(factors, Resampling.average)
        raster.update_tags(ns="rio_overview", resampling="average")


def _spool(paths, grid, config, directory):
    """Store X/Y/Z/class as float64 records in disk buckets; no decimation."""
    counts = {}
    total = used = withheld = 0
    side = config.tile_pixels
    halo = config.radius_m if config.mode != "dsm" else 0
    for path in paths:
        with laspy.open(path) as reader:
            for chunk in reader.chunk_iterator(config.chunk_points):
                total += len(chunk)
                points = np.column_stack((chunk.x, chunk.y, chunk.z, chunk.classification)).astype("<f8")
                if not np.isfinite(points).all():
                    raise ValueError(f"Non-finite point coordinates in {path.name}")
                excluded = np.asarray(chunk.withheld, dtype=bool)
                withheld += int(excluded.sum())
                keep = (~excluded & (points[:, 0] >= grid.left - halo) &
                        (points[:, 0] <= grid.right + halo) &
                        (points[:, 1] >= grid.bottom - halo) &
                        (points[:, 1] <= grid.top + halo))
                points = points[keep]
                used += len(points)
                if not len(points):
                    continue
                col = np.floor((points[:, 0] - grid.left) / grid.resolution / side).astype(np.int64)
                row = np.floor((grid.top - points[:, 1]) / grid.resolution / side).astype(np.int64)
                keys, indices = np.unique(np.column_stack((row, col)), axis=0, return_inverse=True)
                order = np.argsort(indices, kind="stable")
                limits = np.searchsorted(indices[order], np.arange(len(keys) + 1))
                for i, key in enumerate(keys):
                    key = tuple(int(v) for v in key)
                    selected = points[order[limits[i]:limits[i + 1]]]
                    counts[key] = counts.get(key, 0) + len(selected)
                    if counts[key] > config.max_tile_points:
                        raise ValueError("Spatial bucket exceeds max_tile_points; reduce tile_pixels or increase the explicit limit")
                    with (directory / f"{key[0]}_{key[1]}.bin").open("ab") as stream:
                        selected.tofile(stream)
    if not used:
        raise ValueError("No usable points in the requested bounds and support halo")
    return counts, {"read": total, "retained_in_extent_and_halo": used, "withheld_excluded": withheld}


def _window_points(directory, buckets, window, grid, config):
    x0 = grid.left + window.col_off * grid.resolution
    x1 = x0 + window.width * grid.resolution
    y1 = grid.top - window.row_off * grid.resolution
    y0 = y1 - window.height * grid.resolution
    radius = config.radius_m if config.mode != "dsm" else 0
    span = grid.resolution * config.tile_pixels
    c0, c1 = math.floor((x0 - radius - grid.left) / span), math.floor((x1 + radius - grid.left) / span)
    r0, r1 = math.floor((grid.top - y1 - radius) / span), math.floor((grid.top - y0 + radius) / span)
    result, total = [], 0
    for row in range(r0, r1 + 1):
        for col in range(c0, c1 + 1):
            if (row, col) not in buckets:
                continue
            raw = np.memmap(directory / f"{row}_{col}.bin", mode="r", dtype="<f8", shape=(buckets[row, col], 4))
            mask = ((raw[:, 0] >= x0 - radius) & (raw[:, 0] <= x1 + radius) &
                    (raw[:, 1] >= y0 - radius) & (raw[:, 1] <= y1 + radius))
            part = np.array(raw[mask])
            del raw
            total += len(part)
            if total > config.max_tile_points:
                raise ValueError("Window plus support halo exceeds max_tile_points; reduce tile_pixels/radius or increase the explicit limit")
            if len(part):
                result.append(part)
    return np.concatenate(result) if result else np.empty((0, 4))


def _cell_bins(points, window, grid):
    cols = np.floor((points[:, 0] - grid.left) / grid.resolution).astype(np.int64) - int(window.col_off)
    rows = np.floor((grid.top - points[:, 1]) / grid.resolution).astype(np.int64) - int(window.row_off)
    keep = (rows >= 0) & (rows < window.height) & (cols >= 0) & (cols < window.width)
    return keep, rows[keep] * int(window.width) + cols[keep]


def raster_window(points, window, grid, config):
    """DSM=max in exact cells; DTM=IDW of ground within a circular radius.

    Pure numerical kernel. No gap filling, clipping negative nDSM, coordinate
    transforms or thinning. Counts refer to source records, not independent
    observations (overlapping input files may repeat points).
    """
    shape = (int(window.height), int(window.width))
    size = shape[0] * shape[1]
    products = {}
    ground = points[np.isin(points[:, 3], config.ground_classes)]
    keep, bins = _cell_bins(points, window, grid)
    products["point_count"] = np.bincount(bins, minlength=size).astype("uint32").reshape(shape)
    keep_ground, ground_bins = _cell_bins(ground, window, grid)
    products["ground_count"] = np.bincount(ground_bins, minlength=size).astype("uint32").reshape(shape)
    if config.mode != "dtm":
        surface = points if config.dsm_classes is None else points[np.isin(points[:, 3], config.dsm_classes)]
        selected, bins = _cell_bins(surface, window, grid)
        heights = np.full(size, -np.inf)
        np.maximum.at(heights, bins, surface[selected, 2])
        heights[~np.isfinite(heights)] = np.nan
        products["dsm"] = heights.reshape(shape).astype("float32")
        products["dsm_count"] = np.bincount(bins, minlength=size).astype("uint32").reshape(shape)
    if config.mode != "dsm":
        heights = np.full(size, np.nan)
        support = np.zeros(size, dtype="uint32")
        if len(ground):
            # Local coordinates protect sub-metre distances at large eastings.
            origin = np.array([grid.left + window.col_off * grid.resolution,
                               grid.top - window.row_off * grid.resolution])
            xy = ground[:, :2] - origin
            tree = cKDTree(xy)
            cols, rows = np.meshgrid(np.arange(shape[1]) + 0.5, np.arange(shape[0]) + 0.5)
            centres = np.column_stack((cols.ravel(), -rows.ravel())) * grid.resolution
            # Query one centre at a time: no window_size*density neighbour list.
            for i, centre in enumerate(centres):
                indices = tree.query_ball_point(centre, config.radius_m, return_sorted=True)
                if not indices:
                    continue
                support[i] = len(indices)
                distance = np.linalg.norm(xy[indices] - centre, axis=1)
                z = ground[indices, 2]
                exact = distance == 0
                if exact.any():
                    heights[i] = z[exact].mean()
                else:
                    # Scale by nearest distance to avoid overflow near zero.
                    weights = (distance.min() / distance) ** config.idw_power
                    heights[i] = np.dot(weights, z) / weights.sum()
        products["dtm"] = heights.reshape(shape).astype("float32")
        products["dtm_support"] = support.reshape(shape)
    if config.mode == "ndsm":
        products["ndsm"] = products["dsm"] - products["dtm"]
    return products


def _run(config: Config, output: Path, progress=print):
    paths, crs, grid, sources = inspect(config)
    output = output.resolve()
    if output.exists():
        raise ValueError("Output directory already exists; choose a new execution directory")
    output.mkdir(parents=True)
    manifest = {"schema_version": "1.0", "software": "lidar2DSM", "version": __version__,
                "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
                "config": config.to_dict(), "inputs": sources, "grid": grid.to_dict(),
                "crs_wkt": crs.to_wkt(), "z_units": "m",
                "vertical_reference": config.vertical_reference,
                "warnings": [], "outputs": {}}
    if config.vertical_reference == "unknown":
        manifest["warnings"].append("Vertical datum unknown: elevations preserve input Z metres; no geoid/vertical transformation performed")
    manifest["warnings"].append("Input Z metres and a common vertical basis are user declarations; point density is not elevation accuracy")
    manifest["warnings"].append("DSM uses all classes unless dsm_classes is set; overlapping source points are not deduplicated")
    _dump(output / "run.json", manifest)
    try:
        progress("10% Reading points into temporary spatial buckets")
        with tempfile.TemporaryDirectory(prefix=".work-", dir=output) as directory:
            directory = Path(directory)
            buckets, ingestion = _spool(paths, grid, config, directory)
            manifest["points"] = ingestion
            names = ["point_count", "ground_count"]
            if config.mode != "dtm":
                names += ["dsm", "dsm_count"]
            if config.mode != "dsm":
                names += ["dtm", "dtm_support"]
            if config.mode == "ndsm":
                names += ["ndsm"]
            summaries = {name: {"valid_cells": 0, "min": None, "max": None, "sum": 0.0} for name in names}
            total_windows = math.ceil(grid.height / config.tile_pixels) * math.ceil(grid.width / config.tile_pixels)
            done, last_progress = 0, 10
            with ExitStack() as stack:
                writers = {}
                for name in names:
                    elevation = name in ("dtm", "dsm", "ndsm")
                    writer = stack.enter_context(rasterio.open(
                        output / f"{name}.tif", "w", driver="GTiff", width=grid.width,
                        height=grid.height, count=1, dtype="float32" if elevation else "uint32",
                        crs=crs.to_wkt(), transform=grid.transform, nodata=np.nan if elevation else None,
                        tiled=True, blockxsize=256, blockysize=256, compress="deflate",
                        predictor=3 if elevation else 2, BIGTIFF="IF_SAFER"))
                    writer.set_band_description(1, name)
                    writer.update_tags(AREA_OR_POINT="Area", software=f"lidar2DSM {__version__}",
                                       vertical_reference=config.vertical_reference,
                                       units="m" if elevation else "source_records")
                    writers[name] = writer
                for row in range(0, grid.height, config.tile_pixels):
                    for col in range(0, grid.width, config.tile_pixels):
                        window = Window(col, row, min(config.tile_pixels, grid.width - col),
                                        min(config.tile_pixels, grid.height - row))
                        points = _window_points(directory, buckets, window, grid, config)
                        products = raster_window(points, window, grid, config)
                        for name, array in products.items():
                            if np.isinf(array).any():
                                raise ValueError("Elevation exceeds Float32 range")
                            writers[name].write(array, 1, window=window)
                            valid = array[np.isfinite(array)] if array.dtype.kind == "f" else array[array > 0]
                            summary = summaries[name]
                            if valid.size:
                                lo, hi = float(valid.min()), float(valid.max())
                                summary["min"] = lo if summary["min"] is None else min(lo, summary["min"])
                                summary["max"] = hi if summary["max"] is None else max(hi, summary["max"])
                                summary["sum"] += float(valid.sum(dtype=np.float64))
                                summary["valid_cells"] += int(valid.size)
                        done += 1
                        percent = 10 + int(80 * done / total_windows)
                        if percent >= last_progress + 10:
                            progress(f"{percent}% Rasterizing aligned windows")
                            last_progress = percent
            for name, summary in summaries.items():
                count = summary["valid_cells"]
                summary["mean"] = summary.pop("sum") / count if count else None
                summary["coverage_fraction"] = count / (grid.width * grid.height)
                elevation = name in ("dtm", "dsm", "ndsm")
                overview_factors = (_overview_factors(
                    grid.width, grid.height, config.overview_min_size
                ) if elevation else [])
                if elevation:
                    _build_elevation_overviews(output / f"{name}.tif", overview_factors)
                manifest["outputs"][name] = {"file": f"{name}.tif", **summary}
                if elevation:
                    manifest["outputs"][name].update({
                        "overview_factors": overview_factors,
                        "overview_resampling": "average" if overview_factors else None,
                    })
                # Validate the actual serialized product before reporting success.
                with rasterio.open(output / f"{name}.tif") as raster:
                    if (raster.transform != grid.transform or raster.shape != (grid.height, grid.width)
                            or not CRS_equal(raster.crs, crs)):
                        raise ValueError(f"Serialized grid/CRS mismatch in {name}")
                    if raster.overviews(1) != overview_factors:
                        raise ValueError(f"Serialized overview mismatch in {name}")
                if name in ("dtm", "dsm", "ndsm") and not count:
                    raise ValueError(f"No supported cells in {name}; check classes, bounds and radius")
                if name in ("dtm", "dsm", "ndsm") and count < grid.width * grid.height:
                    manifest["warnings"].append(f"{name}: unsupported cells retained as NoData")
        manifest["status"] = "complete"
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _dump(output / "run.json", manifest)
        progress("100% Complete; inspect coverage and vertical-reference warnings in run.json")
        return manifest
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        _dump(output / "run.json", manifest)
        raise


def CRS_equal(a, b):
    from pyproj import CRS
    return CRS.from_user_input(a).equals(b)


def run(config: Config, output: Path, progress=print):
    from .native import raster_environment
    with raster_environment():
        return _run(config, output, progress)
