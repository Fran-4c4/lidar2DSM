# Installation and CLI

Python 3.12+ on Windows, Linux or macOS. Geospatial dependencies are installed
from public packages; wheel availability depends on the platform. Offline use
requires installing those dependencies beforehand.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -c constraints/python312.txt -e ".[test]"
.venv\Scripts\python -m lidar2dsm --help
```

On Linux/macOS, replace `.venv\Scripts\python` with `.venv/bin/python`.
To install without tests: `python -m pip install .`. After installation,
`lidar2dsm` and `python -m lidar2dsm` expose the same CLI.

| Command | Purpose |
|---|---|
| `demo --output NEW_DIRECTORY` | Generate synthetic LAS, configuration and expected values. |
| `validate CONFIG.json` | Check headers, paths, CRS and the expected grid. |
| `run CONFIG.json --output NEW_DIRECTORY` | Generate rasters and the report. |
| `--version` | Display the package version. |

`inputs` paths are relative to the JSON file; `--output` is relative to the
calling directory. See the [configuration contract](configuration.md).

## Optional Docker

Build from the public Python base image, without private registries:

```bash
docker build -t lidar2dsm:local .
docker run --rm -v "$PWD:/data" lidar2dsm:local demo --output /data/work/docker-demo
docker run --rm -v "$PWD:/data" lidar2dsm:local run /data/work/docker-demo/config.json --output /data/outputs/docker-demo
```

These volume examples use Bash. In PowerShell, use `${PWD}` for the volume path.
For real data, mount inputs/configuration read-only and only the output location
read-write. Conversion needs no network. Building downloads the base image and
dependencies. See [validation](validation.md) for the verification strategy.

## Troubleshooting

- **No ground points:** check classification. Do not substitute roof minima;
  classify ground first or obtain a suitable DTM from another source.
- **Missing CRS:** use `crs_if_missing` only when the actual CRS is known.
- **Large NoData areas:** review ground density, radius and extent. A larger
  radius does not necessarily improve accuracy.
- **Point limit exceeded:** reduce `tile_pixels`, crop with `bounds`, or increase
  the explicit limit after assessing memory and disk requirements.
- **Directory already exists:** choose a different execution name.
- **LAZ decompression unavailable:** install all declared dependencies, including `lazrs`.
