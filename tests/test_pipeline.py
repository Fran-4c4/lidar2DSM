"""Analytic outputs, grid invariants, provenance and error behaviour."""
from dataclasses import replace
import json
from pathlib import Path

import laspy
import numpy as np
import pytest
from pyproj import CRS
import rasterio
from rasterio.windows import Window

from lidar2dsm.cli import main
from lidar2dsm.config import Config, load_config
from lidar2dsm.demo import create_demo
from lidar2dsm.engine import raster_window, run
from lidar2dsm.grid import Grid, inspect


def write_cloud(path, xyz, classes=None, crs="EPSG:32628", withheld=None):
    points = np.asarray(xyz, dtype=float)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001] * 3)
    header.offsets = np.r_[points[0, :2], 0.0]
    if crs:
        header.add_crs(CRS.from_user_input(crs))
    cloud = laspy.LasData(header)
    cloud.x, cloud.y, cloud.z = points.T
    cloud.classification = np.array(classes if classes is not None else [2] * len(points), dtype="uint8")
    if withheld is not None:
        cloud.withheld = np.array(withheld, dtype="uint8")
    cloud.write(path)


def read(path):
    with rasterio.open(path) as raster:
        return raster.read(1), raster.transform, raster.crs


def test_demo_analytic_rasters_and_alignment(tmp_path):
    create_demo(tmp_path / "demo")
    config = load_config(tmp_path / "demo/config.json")
    result = run(config, tmp_path / "out", progress=lambda _: None)
    dtm, affine, crs = read(tmp_path / "out/dtm.tif")
    dsm, dsmaffine, dsmcrs = read(tmp_path / "out/dsm.tif")
    ndsm, ndsmaffine, ndsmcrs = read(tmp_path / "out/ndsm.tif")
    assert dtm.shape == (8, 8)
    assert affine.a == 0.5 and affine.e == -0.5
    assert affine == dsmaffine == ndsmaffine
    assert crs == dsmcrs == ndsmcrs
    np.testing.assert_array_equal(dtm, 25)
    expected = np.zeros((8, 8), dtype="float32")
    expected[2:6, 2:6] = 4
    np.testing.assert_array_equal(ndsm, expected)
    np.testing.assert_array_equal(dsm, expected + 25)
    assert result["status"] == "complete"
    assert result["outputs"]["dtm"]["coverage_fraction"] == 1
    assert result["points"]["read"] == 80
    assert not list((tmp_path / "out").glob(".work-*"))


@pytest.mark.parametrize("resolution", [0.25, 0.5, 1.0, 2.0])
def test_requested_resolution_is_not_clamped(tmp_path, resolution):
    create_demo(tmp_path / "demo")
    config = replace(load_config(tmp_path / "demo/config.json"), resolution_m=resolution, radius_m=2)
    run(config, tmp_path / "out", progress=lambda _: None)
    for name in ("dtm", "dsm", "ndsm"):
        array, affine, _ = read(tmp_path / f"out/{name}.tif")
        assert affine.a == resolution
        assert affine.e == -resolution
        assert array.shape == (round(4 / resolution), round(4 / resolution))


def test_exact_ground_duplicates_and_idw_weighting():
    grid = Grid(0, 1, 1, 1, 1)
    config = Config(("unused.las",), radius_m=2)
    points = np.array([[0.25, 0.5, 10, 2], [1, 0.5, 20, 2], [0.5, 0.5, 99, 6]])
    products = raster_window(points, Window(0, 0, 1, 1), grid, config)
    assert products["dtm"][0, 0] == pytest.approx(12.0)
    assert products["dtm_support"][0, 0] == 2
    assert products["dsm"][0, 0] == 99
    points = np.r_[points, [[0.5, 0.5, 13, 2], [0.5, 0.5, 17, 2]]]
    products = raster_window(points, Window(0, 0, 1, 1), grid, config)
    assert products["dtm"][0, 0] == 15


def test_no_extrapolation_and_negative_ndsm_preserved():
    grid = Grid(0, 2, 1, 2, 2)
    config = Config(("unused.las",), mode="ndsm", radius_m=0.1, dsm_classes=(6,))
    points = np.array([[0.5, 1.5, 10, 2], [0.5, 1.5, 8, 6]])
    products = raster_window(points, Window(0, 0, 2, 2), grid, config)
    assert products["ndsm"][0, 0] == -2
    assert np.isnan(products["ndsm"][1, 1])
    assert products["dtm_support"][1, 1] == 0


def test_tile_halos_and_chunking_do_not_change_results(tmp_path):
    cols, rows = np.meshgrid(np.arange(17), np.arange(13))
    xyz = np.column_stack((500000.13 + cols.ravel() * 0.5,
                           3100000.17 + rows.ravel() * 0.5,
                           20 + cols.ravel() * 0.1 + rows.ravel() * 0.2))
    write_cloud(tmp_path / "points.las", xyz)
    config = Config((str(tmp_path / "points.las"),), mode="ndsm", radius_m=0.9)
    run(config, tmp_path / "large", progress=lambda _: None)
    run(replace(config, tile_pixels=3, chunk_points=7), tmp_path / "small", progress=lambda _: None)
    for name in ("dtm", "dsm", "ndsm", "ground_count", "point_count", "dsm_count", "dtm_support"):
        a, t1, _ = read(tmp_path / f"large/{name}.tif")
        b, t2, _ = read(tmp_path / f"small/{name}.tif")
        assert t1 == t2
        np.testing.assert_allclose(a, b, atol=1e-6, equal_nan=True)


def test_outside_bounds_ground_support_and_withheld_exclusion(tmp_path):
    write_cloud(tmp_path / "points.las", [[500000.25, 3100000.25, 29],
        [500000.25, 3100000.25, 90], [499999.75, 3100000.25, 25]], [6, 6, 2], withheld=[0, 1, 0])
    config = Config((str(tmp_path / "points.las"),), mode="ndsm", radius_m=0.6,
                    bounds=(500000, 3100000, 500000.5, 3100000.5))
    result = run(config, tmp_path / "out", progress=lambda _: None)
    assert read(tmp_path / "out/ndsm.tif")[0][0, 0] == 4
    assert read(tmp_path / "out/ground_count.tif")[0][0, 0] == 0
    assert read(tmp_path / "out/dtm_support.tif")[0][0, 0] == 1
    assert result["points"]["withheld_excluded"] == 1


def test_multiple_files_are_combined_and_header_maxima_included(tmp_path):
    write_cloud(tmp_path / "a.las", [[500000, 3100000, 25]])
    write_cloud(tmp_path / "b.las", [[500001, 3100001, 29]], [6])
    config = Config((str(tmp_path),), mode="ndsm", radius_m=2)
    result = run(config, tmp_path / "out", progress=lambda _: None)
    assert result["points"]["read"] == 2
    assert read(tmp_path / "out/point_count.tif")[0].sum() == 2
    assert result["outputs"]["dsm"]["valid_cells"] == 2


@pytest.mark.parametrize("crs", ["EPSG:4326", "EPSG:3857", "EPSG:2263"])
def test_unsuitable_crs_rejected(tmp_path, crs):
    write_cloud(tmp_path / "in.las", [[1, 1, 1]], crs=crs)
    with pytest.raises(ValueError, match="projected CRS in metres"):
        inspect(Config((str(tmp_path / "in.las"),)))


def test_missing_mixed_and_contradictory_crs(tmp_path):
    write_cloud(tmp_path / "a.las", [[500000, 3100000, 25]], crs=None)
    with pytest.raises(ValueError, match="Missing CRS"):
        inspect(Config((str(tmp_path / "a.las"),)))
    config = Config((str(tmp_path / "a.las"),), crs_if_missing="EPSG:32628")
    assert inspect(config)[1].to_epsg() == 32628
    write_cloud(tmp_path / "b.las", [[500000, 3100000, 25]], crs="EPSG:32629")
    with pytest.raises(ValueError, match="contradicts"):
        inspect(replace(config, inputs=(str(tmp_path / "b.las"),)))
    write_cloud(tmp_path / "a.las", [[500000, 3100000, 25]], crs="EPSG:32628")
    with pytest.raises(ValueError, match="Mixed"):
        inspect(Config((str(tmp_path),)))


def test_failure_manifest_no_ground_and_no_overwrite(tmp_path):
    write_cloud(tmp_path / "points.las", [[500000.25, 3100000.25, 29]], [6])
    config = Config((str(tmp_path / "points.las"),), mode="dtm")
    with pytest.raises(ValueError, match="No supported cells in dtm"):
        run(config, tmp_path / "out", progress=lambda _: None)
    assert json.loads((tmp_path / "out/run.json").read_text())["status"] == "failed"
    with pytest.raises(ValueError, match="already exists"):
        run(config, tmp_path / "out", progress=lambda _: None)


def test_explicit_memory_and_grid_limits(tmp_path):
    write_cloud(tmp_path / "points.las", [[500000.1, 3100000.1, 1], [500000.2, 3100000.2, 2]])
    config = Config((str(tmp_path / "points.las"),), mode="dsm")
    with pytest.raises(ValueError, match="max_tile_points"):
        run(replace(config, max_tile_points=1), tmp_path / "out", progress=lambda _: None)
    with pytest.raises(ValueError, match="max_cells"):
        inspect(replace(config, bounds=(500000, 3100000, 500010, 3100010), max_cells=2))


@pytest.mark.parametrize("mode,expected", [("dtm", {"dtm"}), ("dsm", {"dsm"}),
    ("dsm_and_dtm", {"dtm", "dsm"}), ("ndsm", {"dtm", "dsm", "ndsm"})])
def test_modes(tmp_path, mode, expected):
    create_demo(tmp_path / "demo")
    config = replace(load_config(tmp_path / "demo/config.json"), mode=mode)
    report = run(config, tmp_path / "out", progress=lambda _: None)
    assert set(report["outputs"]) & {"dtm", "dsm", "ndsm"} == expected


def test_cli_smoke_and_errors(tmp_path, capsys):
    assert main(["demo", "--output", str(tmp_path / "demo")]) == 0
    assert main(["validate", str(tmp_path / "demo/config.json")]) == 0
    assert main(["run", str(tmp_path / "demo/config.json"), "--output", str(tmp_path / "out")]) == 0
    assert main(["run", str(tmp_path / "demo/config.json"), "--output", str(tmp_path / "out")]) == 2
    assert "already exists" in capsys.readouterr().err


def test_non_utm_crs_roundtrip_and_environment_restored(tmp_path):
    import os
    from rasterio._env import get_proj_data_search_paths
    from lidar2dsm.native import raster_environment
    environment = {name: os.environ.get(name) for name in ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA")}
    previous = get_proj_data_search_paths()
    write_cloud(tmp_path / "rd.las", [[84808.25, 447412.75, 3]], crs="EPSG:28992")
    run(Config((str(tmp_path / "rd.las"),), mode="dtm"), tmp_path / "out", progress=lambda _: None)
    with raster_environment():
        _, _, crs = read(tmp_path / "out/dtm.tif")
        assert CRS.from_user_input(crs).equals(CRS.from_epsg(28992))
    assert get_proj_data_search_paths() == previous
    assert {name: os.environ.get(name) for name in environment} == environment


def test_laz_compression_roundtrip(tmp_path):
    create_demo(tmp_path / "demo")
    cloud = laspy.read(tmp_path / "demo/points.las")
    cloud.write(tmp_path / "demo/points.laz")
    config = replace(load_config(tmp_path / "demo/config.json"), inputs=(str(tmp_path / "demo/points.laz"),))
    report = run(config, tmp_path / "out", progress=lambda _: None)
    assert report["points"]["read"] == 80
    assert read(tmp_path / "out/ndsm.tif")[0].max() == 4


def test_corrupt_las_is_a_cli_error(tmp_path, capsys):
    (tmp_path / "bad.las").write_bytes(b"not a LAS file")
    (tmp_path / "config.json").write_text('{"inputs": ["bad.las"]}')
    assert main(["validate", str(tmp_path / "config.json")]) == 2
    assert "error" in capsys.readouterr().err.lower()
