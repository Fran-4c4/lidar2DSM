# Tests

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

The suite creates original LAS fixtures in temporary directories and checks:
known elevations, IDW and coincident points, requested resolution, common grids,
window-size independence, support outside crops, classes and withheld flags,
NaN, negative nDSM, multiple files, CRS, limits, failures and overwrite protection.
Docker, PDAL, networking, databases and other checkouts are not required.

External real-data checks are additional. Record provenance, parameters and
evidence in `docs/validation.md` without adding large datasets to Git.
