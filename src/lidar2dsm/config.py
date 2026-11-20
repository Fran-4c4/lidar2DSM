"""One owner for the public JSON configuration, validation and defaults."""
from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """JSON keys equal field names; omitted optional keys use ONLY these defaults.

    inputs: nonempty tuple of LAS/LAZ files or directories (recursive); paths
        relative to the configuration file. Expanded paths must be unique.
    mode: dtm | dsm | dsm_and_dtm | ndsm. ndsm also writes both parent rasters.
    resolution_m: positive finite pixel size, identical for every output. Never
        clamped, rounded to 1 m or inferred from the cloud's density.
    radius_m: positive finite horizontal radius of DTM IDW support. DSM uses
        exact cell binning and does not consume this field.
    idw_power: positive finite distance exponent for DTM; coincident points are
        averaged before any division. All neighbours within radius participate.
    ground_classes: nonempty distinct integer ASPRS codes 0..255 for DTM.
    dsm_classes: None means all classes; otherwise distinct nonempty codes.
        No implicit noise removal. Withheld points are always excluded.
    crs_if_missing: optional CRS user input (e.g. EPSG:28992), assignment only
        for missing LAS headers. Must equal any declared CRS; never overrides
        a contradictory header, reprojects coordinates or converts Z units.
    vertical_reference: nonempty provenance label for Z metres. 'unknown' is
        allowed with a report warning; all files must actually share this basis.
        A label is a user declaration, not a verified datum or transformation.
    bounds: optional (xmin,ymin,xmax,ymax), metres in input CRS. Defines the
        requested raster extent; expanded OUTWARD to the zero-anchored grid.
        Ground support within radius outside this extent is retained.
    chunk_points: positive integer LAS read batch; performance only.
    tile_pixels: positive integer spatial bucket/window edge, performance only.
        Neighbour halos must preserve results when this field changes.
    max_tile_points: positive integer safety limit for all points in a window
        plus its DTM halo. Exceeding it fails explicitly, without subsampling.
    max_cells: positive integer limit on raster width*height; fails before work.
    overview_min_size: None disables internal elevation overviews. Otherwise a
        positive integer pixel target; power-of-two levels are generated until
        the longest overview side is at or below this target when possible.
        Overviews use average resampling for display only. They never replace
        or alter base-resolution elevation cells or count rasters.

    All numeric fields reject booleans; every unknown key is an error. Changing
    grid/filters/IDW affects elevations, coverage and downstream building bases;
    update analytic raster tests and docs/configuration.md with such changes.
    Fixed output contract: Float32 metre elevations, NaN NoData; uint32 counts
    (0 means no points/support). No filling beyond the configured DTM radius.
    """

    inputs: tuple[str, ...]
    mode: str = "dsm_and_dtm"
    resolution_m: float = 0.5
    radius_m: float = 1.0
    idw_power: float = 2.0
    ground_classes: tuple[int, ...] = (2,)
    dsm_classes: tuple[int, ...] | None = None
    crs_if_missing: str | None = None
    vertical_reference: str = "unknown"
    bounds: tuple[float, float, float, float] | None = None
    chunk_points: int = 500_000
    tile_pixels: int = 256
    max_tile_points: int = 2_000_000
    max_cells: int = 100_000_000
    overview_min_size: int | None = 512

    def __post_init__(self):
        if not isinstance(self.inputs, tuple) or not self.inputs or any(
            not isinstance(p, str) or not p.strip() for p in self.inputs
        ):
            raise ValueError("inputs must contain nonempty file/directory paths")
        if self.mode not in ("dtm", "dsm", "dsm_and_dtm", "ndsm"):
            raise ValueError("mode must be dtm, dsm, dsm_and_dtm or ndsm")
        for name in ("resolution_m", "radius_m", "idw_power"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("chunk_points", "tile_pixels", "max_tile_points", "max_cells"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.overview_min_size is not None and (
            type(self.overview_min_size) is not int or self.overview_min_size < 1
        ):
            raise ValueError("overview_min_size must be null or a positive integer")
        for name in ("ground_classes", "dsm_classes"):
            values = getattr(self, name)
            if values is None and name == "dsm_classes":
                continue
            if (not isinstance(values, tuple) or not values or
                any(type(v) is not int or not 0 <= v <= 255 for v in values) or
                len(set(values)) != len(values)):
                raise ValueError(f"{name} must contain distinct class codes 0..255")
        if self.crs_if_missing is not None and (
            not isinstance(self.crs_if_missing, str) or not self.crs_if_missing.strip()
        ):
            raise ValueError("crs_if_missing must be null or a nonempty CRS string")
        if not isinstance(self.vertical_reference, str) or not self.vertical_reference.strip():
            raise ValueError("vertical_reference must be a nonempty Z provenance label")
        if self.bounds is not None:
            b = self.bounds
            if (not isinstance(b, tuple) or len(b) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in b) or
                b[0] >= b[2] or b[1] >= b[3]):
                raise ValueError("bounds must be finite [xmin,ymin,xmax,ymax] with positive area")

    def to_dict(self):
        return asdict(self)


def load_config(path: Path) -> Config:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate configuration key: {key}")
            result[key] = value
        return result

    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object")
    unknown = set(data) - {f.name for f in fields(Config)}
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    for name in ("inputs", "ground_classes", "dsm_classes", "bounds"):
        if name in data and data[name] is not None:
            if not isinstance(data[name], list):
                raise ValueError(f"{name} must be a JSON array")
            data[name] = tuple(data[name])
    if "inputs" not in data:
        raise ValueError("inputs is required")
    config = Config(**data)
    from dataclasses import replace
    return replace(config, inputs=tuple(str((path.parent / p).resolve()) for p in config.inputs))
