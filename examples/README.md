# Configuration examples

Generate the self-contained example with `python -m lidar2dsm demo`.
The JSON file in this directory shows how to reference your own data; add LAS/LAZ
files under `data/lidar/` before using it. No third-party datasets are included.

`repository.json` is a separate contract for a persistent, tiled source
repository. Copy it outside the project, change `repository_root`, review its
CRS and vertical reference, and initialize it with:

```powershell
python -m lidar2dsm repository init path\to\repository.json
python -m lidar2dsm repository ingest path\to\repository.json path\to\delivery --mode copy
```

`copy` is the default and keeps the delivery. Use `move` only when successfully
verified inputs should be removed after catalogue commit.

The same operation can be recorded with `import-job.json`. Use
`product-job.json` to select a BBOX and generate an immutable DTM/DSM/nDSM COG
release. From a source checkout, `start_lidar2dsm.cmd` on Windows or
`python start_lidar2dsm.py` on Linux/macOS guides users through creating these
JSON files and executing them.
