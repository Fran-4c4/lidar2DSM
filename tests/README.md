# Tests

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

The suite creates original LAS fixtures in temporary directories and checks:
known elevations, IDW and coincident points, requested resolution, common grids,
window-size independence, support outside crops, classes and withheld flags,
NaN, negative nDSM, multiple files, CRS, limits, failures and overwrite protection.
Repository tests also cover strict grid contracts, idempotent initialization,
incremental copy, verified move, partial provider coverage, duplicate detection
and campaign supersession.
Product-job tests cover closed product sets, immutable releases, repository
selection, COG serialization, QA output and `derived_asset` registration.
Docker, PDAL, networking, databases and other checkouts are not required.

External real-data checks are additional. Record provenance, parameters and
evidence in a dedicated report under `docs/validation/` without adding large
datasets to Git, then link it from `docs/validation.md`.
