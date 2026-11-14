from dataclasses import replace
import json

import pytest

from lidar2dsm.config import Config, load_config


def test_defaults_owned_by_config():
    config = Config(("in.las",))
    assert config.resolution_m == 0.5
    assert config.radius_m == 1
    assert config.ground_classes == (2,)
    assert config.dsm_classes is None
    assert config.vertical_reference == "unknown"


@pytest.mark.parametrize("field,value", [
    ("resolution_m", 0), ("resolution_m", -1), ("resolution_m", float("nan")),
    ("resolution_m", True), ("radius_m", float("inf")), ("idw_power", 0),
    ("tile_pixels", 1.5), ("chunk_points", False), ("max_cells", 0),
    ("max_tile_points", -1), ("mode", "DTM"), ("inputs", ()),
    ("inputs", ("",)), ("inputs", "in.las"), ("ground_classes", ()),
    ("ground_classes", (2, 2)), ("ground_classes", (True,)),
    ("dsm_classes", (256,)), ("dsm_classes", ()), ("vertical_reference", ""),
    ("crs_if_missing", ""), ("bounds", (1, 0, 0, 1)),
    ("bounds", (0, 0, float("nan"), 1)), ("bounds", (0, 0, True, 1))])
def test_invalid_values_rejected(field, value):
    with pytest.raises(ValueError):
        replace(Config(("in.las",)), **{field: value})


def test_json_paths_are_relative_to_config_and_unknown_keys_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"inputs": ["data/in.laz"], "resolution_m": 0.25}))
    config = load_config(path)
    assert config.inputs == (str((tmp_path / "data/in.laz").resolve()),)
    assert config.resolution_m == 0.25
    path.write_text('{"inputs": ["in.las"], "resoluton_m": 1}')
    with pytest.raises(ValueError, match="Unknown"):
        load_config(path)
    path.write_text('{"inputs": ["in.las"], "resolution_m": 1, "resolution_m": 0.5}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_config(path)


def test_duplicate_inputs_rejected(tmp_path):
    from lidar2dsm.grid import discover
    (tmp_path / "a.las").touch()
    with pytest.raises(ValueError, match="duplicate"):
        discover(Config((str(tmp_path), str(tmp_path / "a.las"))))
