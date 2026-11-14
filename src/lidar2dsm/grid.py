"""Zero-anchored grids and header-only validation; no implicit reprojection."""
from dataclasses import dataclass
import math
from pathlib import Path

import laspy
from pyproj import CRS
from rasterio.transform import from_origin

from .config import Config


@dataclass(frozen=True)
class Grid:
    """Derived grid: left/top metres, positive pixel size and integer dimensions.

    Half-open cells include their west/north edge and exclude east/south edges.
    Default extent includes points on header maxima by adding one cell when
    necessary. Explicit bounds expand outward, never silently clip support.
    All products consume this same affine transform, shape and CRS.
    """
    left: float
    top: float
    resolution: float
    width: int
    height: int

    @property
    def transform(self):
        return from_origin(self.left, self.top, self.resolution, self.resolution)

    @property
    def right(self):
        return self.left + self.width * self.resolution

    @property
    def bottom(self):
        return self.top - self.height * self.resolution

    def to_dict(self):
        return {"bounds": [self.left, self.bottom, self.right, self.top],
                "width": self.width, "height": self.height,
                "resolution_m": self.resolution, "anchor": [0, 0]}


def discover(config: Config):
    result = []
    for name in config.inputs:
        path = Path(name).resolve()
        if path.is_dir():
            result.extend(sorted(p.resolve() for p in path.rglob("*")
                                 if p.is_file() and p.suffix.lower() in (".las", ".laz")))
        elif path.is_file() and path.suffix.lower() in (".las", ".laz"):
            result.append(path)
        else:
            raise ValueError(f"Not a LAS/LAZ file or directory: {path}")
    if not result:
        raise ValueError("No LAS/LAZ inputs found")
    if len(set(result)) != len(result):
        raise ValueError("Input paths overlap or contain duplicate files")
    return result


def inspect(config: Config):
    paths = discover(config)
    override = CRS.from_user_input(config.crs_if_missing) if config.crs_if_missing else None
    common = None
    records = []
    for path in paths:
        with laspy.open(path) as reader:
            header = reader.header
            crs = header.parse_crs()
            if crs is not None and override is not None and not crs.equals(override):
                raise ValueError(f"crs_if_missing contradicts the declared CRS: {path.name}")
            crs = crs or override
            if crs is None:
                raise ValueError(f"Missing CRS in {path.name}; supply crs_if_missing explicitly")
            horizontal = crs.sub_crs_list[0] if crs.is_compound else crs
            if (not horizontal.is_projected or horizontal.to_epsg() in (3857, 3395) or
                len(horizontal.axis_info) < 2 or
                any(not math.isclose(a.unit_conversion_factor, 1.0) for a in horizontal.axis_info[:2])):
                raise ValueError("Use a suitable projected CRS in metres; geographic/Web Mercator unsupported")
            if len(crs.axis_info) > 2 and not math.isclose(crs.axis_info[2].unit_conversion_factor, 1.0):
                raise ValueError("Declared vertical CRS must use metres; Z is never converted")
            if common is not None and not common.equals(crs):
                raise ValueError("Mixed input CRSs; reproject inputs explicitly before this run")
            common = crs
            if not header.point_count:
                raise ValueError(f"Empty input point cloud: {path.name}")
            bounds = [float(header.mins[0]), float(header.mins[1]),
                      float(header.maxs[0]), float(header.maxs[1])]
            if not all(math.isfinite(v) for v in bounds):
                raise ValueError(f"Non-finite input extent: {path.name}")
            records.append({"file": str(path), "points": int(header.point_count), "bounds": bounds,
                            "bytes": path.stat().st_size, "crs_from_header": header.parse_crs() is not None})
    r = config.resolution_m
    if config.bounds is None:
        xmin = min(p["bounds"][0] for p in records)
        ymin = min(p["bounds"][1] for p in records)
        xmax = max(p["bounds"][2] for p in records)
        ymax = max(p["bounds"][3] for p in records)
        left = math.floor(xmin / r) * r
        right = (math.floor(xmax / r) + 1) * r
        bottom = (math.ceil(ymin / r) - 1) * r
        top = math.ceil(ymax / r) * r
    else:
        xmin, ymin, xmax, ymax = config.bounds
        left, bottom = math.floor(xmin / r) * r, math.floor(ymin / r) * r
        right, top = math.ceil(xmax / r) * r, math.ceil(ymax / r) * r
    width, height = round((right - left) / r), round((top - bottom) / r)
    if width < 1 or height < 1 or width * height > config.max_cells:
        raise ValueError(f"Grid has {width * height:,} cells; max_cells={config.max_cells:,}. Use bounds or a coarser resolution")
    return paths, common, Grid(left, top, r, width, height), records
