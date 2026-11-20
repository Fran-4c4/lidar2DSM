import json
from pathlib import Path
import sqlite3

import laspy
import numpy as np
from pyproj import CRS
import pytest

from lidar2dsm.repository import (
    GridDefinition,
    RepositoryConfig,
    ingest_repository,
    init_repository,
    load_import_job,
    load_repository_config,
)


def _config(root: Path) -> RepositoryConfig:
    return RepositoryConfig(
        str(root),
        "pnoa",
        GridDefinition(
            "regcan95_utm28_1km_v1", "EPSG:4083", 0, 0, 1000, 0.5,
            "unknown",
        ),
    )


def _write_pnoa(path: Path, *, z=20.0, partial=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([454000.0, 3107000.0, 0.0])
    header.add_crs(CRS.from_epsg(4083))
    cloud = laspy.LasData(header)
    end = 454500.0 if partial else 454999.999
    cloud.x = np.array([454000.0, end, end, 454000.0])
    cloud.y = np.array([3107000.0, 3107000.0, 3107999.999, 3107999.999])
    cloud.z = np.array([z, z, z, z])
    cloud.classification = np.array([2, 2, 2, 2], dtype=np.uint8)
    cloud.write(path)


def test_repository_config_is_strict_and_relative(tmp_path):
    config_path = tmp_path / "repository.json"
    config_path.write_text(json.dumps({
        "repository_root": "repo",
        "source_profile": "pnoa",
        "grid": {
            "grid_id": "regcan95_utm28_1km_v1",
            "horizontal_crs": "EPSG:4083",
            "origin_x_m": 0,
            "origin_y_m": 0,
            "tile_size_m": 1000,
            "resolution_m": 0.5,
            "vertical_reference": "unknown"
        }
    }))
    config = load_repository_config(config_path)
    assert config.root == (tmp_path / "repo").resolve()
    assert config.grid.tile_id_template == "E{xmin}_N{ymin}"

    data = json.loads(config_path.read_text())
    data["grid"]["pixel_size"] = 1
    config_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Unknown grid"):
        load_repository_config(config_path)


def test_import_job_paths_are_relative_and_copy_is_default(tmp_path):
    path = tmp_path / "jobs" / "import.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "repository": "../repository.json",
        "input_directory": "../delivery"
    }))
    job = load_import_job(path)
    assert Path(job.repository) == (tmp_path / "repository.json").resolve()
    assert Path(job.input_directory) == (tmp_path / "delivery").resolve()
    assert job.transfer_mode == "copy"


def test_init_is_idempotent_and_owns_grid_contract(tmp_path):
    config = _config(tmp_path / "repo")
    first = init_repository(config)
    second = init_repository(config)
    assert first["catalog_created"] is True
    assert second["catalog_created"] is False
    assert (config.root / "README.md").exists()
    assert (config.root / "repository.json").exists()
    for product in ("dtm", "dsm", "ndsm"):
        assert (config.root / "products" / product / config.grid.grid_id / "releases").is_dir()
    with sqlite3.connect(config.root / "catalog" / "catalog.gpkg") as db:
        assert db.execute("select count(*) from grid_definition").fetchone()[0] == 1
        assert db.execute("select count(*) from lidar_source").fetchone()[0] == 0


def test_ingest_copy_is_incremental_and_accepts_partial_source(tmp_path):
    config = _config(tmp_path / "repo")
    source = tmp_path / "delivery"
    laz = source / "PNOA_2023_CANAR_454-3108_H28_NPC02.laz"
    _write_pnoa(laz, partial=True)

    messages = []
    result = ingest_repository(config, source, "copy", progress=messages.append)
    assert result["ingested"] == 1
    assert result["duplicates"] == 0
    assert laz.exists()
    destination = config.root / "source" / "pnoa" / "2023" / "canar" / "h28" / "npc02" / laz.name
    assert destination.exists()
    assert any("Reading header and SHA-256" in message for message in messages)
    assert messages[-1].startswith("Import complete:")

    repeated = ingest_repository(config, source, "copy")
    assert repeated["ingested"] == 0
    assert repeated["duplicates"] == 1
    with sqlite3.connect(config.root / "catalog" / "catalog.gpkg") as db:
        row = db.execute(
            "select tile_id,source_coverage,lifecycle_state from lidar_source"
        ).fetchone()
        assert row == ("E454000_N3107000", "partial", "active")

    destination.unlink()
    repaired = ingest_repository(config, source, "copy")
    assert repaired["ingested"] == 0
    assert repaired["duplicates"] == 1
    assert repaired["copied_files"] == 1
    assert destination.exists()


def test_new_campaign_supersedes_active_source_and_move_removes_input(tmp_path):
    config = _config(tmp_path / "repo")
    first_dir = tmp_path / "first"
    first = first_dir / "PNOA_2023_CANAR_454-3108_H28_NPC02.laz"
    _write_pnoa(first, z=20)
    ingest_repository(config, first_dir, "copy")

    second_dir = tmp_path / "second"
    second = second_dir / "PNOA_2025_CANAR_454-3108_H28_NPC02.laz"
    _write_pnoa(second, z=21)
    result = ingest_repository(config, second_dir, "move")
    assert result["ingested"] == 1
    assert result["superseded"] == 1
    assert result["removed_inputs"] == 1
    assert not second.exists()
    with sqlite3.connect(config.root / "catalog" / "catalog.gpkg") as db:
        rows = db.execute(
            "select campaign,lifecycle_state from lidar_source order by campaign"
        ).fetchall()
        assert rows == [("2023", "superseded"), ("2025", "active")]


def test_ingest_rejects_provider_name_that_contradicts_header(tmp_path):
    config = _config(tmp_path / "repo")
    source = tmp_path / "delivery"
    wrong = source / "PNOA_2023_CANAR_455-3108_H28_NPC02.laz"
    _write_pnoa(wrong)
    with pytest.raises(ValueError, match="token contradicts"):
        ingest_repository(config, source, "copy")
    assert not (config.root / "source" / "pnoa" / "2023").exists()
