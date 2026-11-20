import json
from pathlib import Path
import sqlite3

import laspy
import numpy as np
from pyproj import CRS
import pytest
import rasterio

from lidar2dsm.products import generate_products, load_product_job
from lidar2dsm.repository import GridDefinition, RepositoryConfig, ingest_repository, init_repository


def _write_source(path: Path, classification=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([454000.0, 3107000.0, 0.0])
    header.add_crs(CRS.from_epsg(4083))
    cloud = laspy.LasData(header)
    cloud.x = np.array([454000.0, 454999.999, 454999.999, 454000.0])
    cloud.y = np.array([3107000.0, 3107000.0, 3107999.999, 3107999.999])
    cloud.z = np.array([20.0, 20.0, 20.0, 20.0])
    cloud.classification = np.array([classification] * 4, dtype=np.uint8)
    cloud.write(path)


def _repository(tmp_path: Path, classification=2) -> RepositoryConfig:
    config = RepositoryConfig(
        str(tmp_path / "repo"), "pnoa",
        GridDefinition(
            "regcan95_utm28_1km_test_v1", "EPSG:4083", 0, 0,
            1000, 250, "unknown",
        ),
    )
    init_repository(config)
    delivery = tmp_path / "delivery"
    _write_source(
        delivery / "PNOA_2023_CANAR_454-3108_H28_NPC02.laz",
        classification=classification,
    )
    ingest_repository(config, delivery)
    return config


def test_product_job_contract_rejects_implicit_ndsm_parents(tmp_path):
    path = tmp_path / "job.json"
    path.write_text(json.dumps({
        "repository": "repository.json",
        "release_id": "r1",
        "products": ["ndsm"],
        "selection": {"all": True}
    }))
    with pytest.raises(ValueError, match="products must be one of"):
        load_product_job(path)


def test_generate_repository_products_and_register_assets(tmp_path):
    config = _repository(tmp_path)
    job = config.root / "jobs" / "products.json"
    job.parent.mkdir(exist_ok=True)
    job.write_text(json.dumps({
        "repository": "../repository.json",
        "release_id": "synthetic-r1",
        "products": ["dtm", "dsm", "ndsm"],
        "selection": {"all": True},
        "processing": {
            "radius_m": 1000,
            "overview_min_size": 2,
            "tile_pixels": 2
        }
    }))

    result = generate_products(job, progress=lambda message: None)
    assert result["status"] == "complete"
    tile = "E454000_N3107000"
    for product in ("dtm", "dsm", "ndsm"):
        path = (
            config.root / "products" / product / config.grid.grid_id /
            "releases" / "synthetic-r1" / f"{tile}.cog.tif"
        )
        assert path.exists()
        with rasterio.open(path) as dataset:
            assert dataset.shape == (4, 4)
            assert dataset.profile["tiled"] is True
            assert dataset.crs == CRS.from_epsg(4083)
    release = config.root / "products" / "releases" / config.grid.grid_id / "synthetic-r1" / "release.json"
    assert json.loads(release.read_text())["status"] == "complete"
    with sqlite3.connect(config.root / "catalog" / "catalog.gpkg") as db:
        assert db.execute("select count(*) from derived_asset").fetchone()[0] == 3
        assert db.execute("select count(*) from derived_asset where lifecycle_state='active'").fetchone()[0] == 3
    with pytest.raises(ValueError, match="Release already exists"):
        generate_products(job, progress=lambda message: None)


def test_unsupported_ground_marks_partial_and_water_class_recovers(tmp_path):
    config = _repository(tmp_path, classification=9)
    job = config.root / "jobs" / "water.json"
    request = {
        "repository": "../repository.json",
        "release_id": "water-ground-only-r1",
        "products": ["dtm"],
        "selection": {"all": True},
        "processing": {"radius_m": 1000, "ground_classes": [2]}
    }
    job.write_text(json.dumps(request))
    failed = generate_products(job, progress=lambda message: None)
    assert failed["status"] == "partial"
    assert failed["failed_tiles"] == 1
    assert next(iter(failed["tiles"].values()))["status"] == "failed"

    request["release_id"] = "water-surface-r2"
    request["processing"]["ground_classes"] = [2, 9]
    job.write_text(json.dumps(request))
    recovered = generate_products(job, progress=lambda message: None)
    assert recovered["status"] == "complete"
    assert recovered["failed_tiles"] == 0
    with sqlite3.connect(config.root / "catalog" / "catalog.gpkg") as db:
        assert db.execute("select count(*) from derived_asset").fetchone()[0] == 1
