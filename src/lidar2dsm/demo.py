"""Small original synthetic fixture: known flat terrain and a four-metre roof."""
import json
from pathlib import Path

import laspy
import numpy as np
from pyproj import CRS


def create_demo(output: Path):
    if output.exists():
        raise ValueError("Demo directory already exists; choose a new directory")
    output.mkdir(parents=True)
    # 8x8 half-metre cells. All ground is 25 m; central 4x4 roof is 29 m.
    cols, rows = np.meshgrid(np.arange(8), np.arange(8))
    x = 500000 + (cols.ravel() + 0.5) * 0.5
    y = 3100000 + (rows.ravel() + 0.5) * 0.5
    roof = (cols.ravel() >= 2) & (cols.ravel() < 6) & (rows.ravel() >= 2) & (rows.ravel() < 6)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([500000.0, 3100000.0, 0.0])
    header.add_crs(CRS.from_epsg(32628))
    points = laspy.LasData(header)
    points.x, points.y = np.r_[x, x[roof]], np.r_[y, y[roof]]
    points.z = np.r_[np.full(64, 25.0), np.full(int(roof.sum()), 29.0)]
    points.classification = np.r_[np.full(64, 2), np.full(int(roof.sum()), 6)].astype("uint8")
    points.write(output / "points.las")
    config = {"inputs": ["points.las"], "mode": "ndsm", "resolution_m": 0.5,
              "radius_m": 0.6, "vertical_reference": "synthetic_local_metres",
              "bounds": [500000, 3100000, 500004, 3100004]}
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (output / "truth.json").write_text(json.dumps({"ground_m": 25, "roof_m": 29,
        "building_height_m": 4, "grid_cells": 64, "roof_cells": 16,
        "note": "Synthetic test; no real-world vertical datum"}, indent=2) + "\n", encoding="utf-8")
