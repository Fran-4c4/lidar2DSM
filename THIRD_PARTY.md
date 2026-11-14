# Provenance and dependencies

The code and synthetic fixtures in this repository are original. No code from
3dfier, Ninja or Azul is included. The core uses laspy, NumPy/SciPy and Rasterio
without helpers, images or services from other projects.

Dependencies retain their own licenses. Direct dependencies are declared in `pyproject.toml`:

| Dependency | Main declared license | Source |
|---|---|---|
| NumPy | BSD-3-Clause and additional component notices | [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| SciPy | BSD-3-Clause and component notices | [SciPy](https://github.com/scipy/scipy/blob/main/LICENSE.txt) |
| Rasterio | BSD-3-Clause | [Rasterio](https://github.com/rasterio/rasterio/blob/main/LICENSE.txt) |
| laspy | BSD-2-Clause | [laspy](https://github.com/laspy/laspy/blob/master/LICENSE.txt) |
| lazrs Python bindings | MIT | [laz-rs-python](https://github.com/laz-rs/laz-rs-python/blob/master/LICENSE.txt) |
| pyproj | MIT | [pyproj](https://github.com/pyproj4/pyproj/blob/main/LICENSE) |
| pytest, tests only | MIT | [pytest](https://github.com/pytest-dev/pytest/blob/main/LICENSE) |

These declarations were checked against installed package metadata for the
versions in `constraints/python312.txt`. Their source code and binaries are not
vendored here; dependencies are installed from public packages. Wheels may bundle
GDAL, PROJ, OpenBLAS and other components with their own notices. Preserve the
license files and notices supplied by those packages when distributing images
or binaries. The application license does not replace dependency terms.

The optional image uses official Python on Debian. Python and operating-system
packages retain their respective terms.

BGT/AHN and other external datasets are not distributed here. Public availability
does not establish redistribution rights; check the provider's terms and required
attribution before including data in a repository or release.
