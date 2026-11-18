# Validation

Validation combines deterministic automated tests, distribution checks and
optional case studies with external point clouds. These layers answer different
questions and must not be treated as interchangeable evidence.

## Automated tests

The test suite creates its own LAS fixtures in temporary directories. It checks:

- known DTM, DSM and nDSM elevations;
- IDW support, coincident points and unsupported cells;
- 0.25, 0.5, 1 and 2 metre resolutions;
- common CRS, transform and dimensions across outputs;
- class filters, withheld points, NoData and negative nDSM values;
- window and read-batch independence, including crop halos;
- multiple inputs, configuration errors and overwrite protection.

Run it from a development installation:

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

GitHub Actions runs the same suite with Python 3.12 on Windows and Linux. The
tests verify numerical and serialization invariants, but they do not certify
the accuracy, classification or vertical reference of an external survey.

## Distribution and container checks

Build a wheel and install it into a fresh environment to detect accidental
imports from the repository root:

```bash
python -m pip wheel --no-deps . --wheel-dir dist
python -m pip install dist/lidar2dsm-*.whl
lidar2dsm --version
```

The Docker image should build from public inputs and run the synthetic example
without network access:

```bash
docker build -t lidar2dsm:local .
docker run --rm --network none -v "$PWD:/data" \
  lidar2dsm:local demo --output /data/work/docker-demo
docker run --rm --network none -v "$PWD:/data" \
  lidar2dsm:local run /data/work/docker-demo/config.json \
  --output /data/outputs/docker-demo
```

Inspect the resulting GeoTIFF CRS, transform, dimensions, NoData values,
elevations and `run.json`; an exit code alone is insufficient evidence.

## External-data case studies

Real datasets are optional integration evidence. They are not part of the test
suite and are not distributed with this repository. Each report records source,
parameters, observed results and the limits of the conclusions:

- [Delft 3dfier sample](validation/delft-3dfier.md)
- [PNOA coastal urban tiles](validation/pnoa-coastal-urban.md)

These reports demonstrate that particular files were read and rasterized under
specific parameters. They do not establish national-scale performance, survey
accuracy, correct ground classification or a certified vertical datum.

## Evidence still missing

The project has not yet established national-scale processing, spatial use of
the COPC index, automatic ground classification, datum correction, certified
COG output or macOS CI. Dependency versions used for the main Python 3.12 checks
are recorded in [`constraints/python312.txt`](../constraints/python312.txt).
