"""Use Rasterio's bundled data without changing user/machine environment."""
from contextlib import contextmanager
import os
from pathlib import Path

import rasterio
from rasterio._env import (
    GDALDataFinder, PROJDataFinder, get_proj_data_search_paths,
    set_proj_data_search_path,
)


@contextmanager
def raster_environment():
    """Scope a wheel's matching PROJ/GDAL databases to this sequential run.

    Desktop GIS/PostGIS can export incompatible PROJ_DATA/PROJ_LIB paths.
    Rasterio 1.x exposes these helpers in its own env implementation. Restore
    its search paths afterwards; never rewrite os.environ or user settings.
    Source/Conda installs without wheel data keep their configured defaults.
    The PROJ search-path API is process-global: concurrent embedded calls to
    run() are unsupported. Independent CLI processes are safe.
    """
    previous = get_proj_data_search_paths()
    proj = PROJDataFinder().search_wheel()
    gdal = GDALDataFinder().search_wheel()
    try:
        with rasterio.Env(**({"GDAL_DATA": gdal} if gdal else {})):
            # Env.start() can reapply inherited PROJ paths; select bundled data
            # after it starts, before opening any raster or resolving a CRS.
            if proj and (Path(proj) / "proj.db").is_file():
                set_proj_data_search_path(proj)
            yield
    finally:
        if proj:
            set_proj_data_search_path(os.pathsep.join(previous))
