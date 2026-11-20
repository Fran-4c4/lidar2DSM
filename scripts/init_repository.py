"""Create or validate a lidar2DSM repository from its JSON contract."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lidar2dsm.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["repository", "init", *sys.argv[1:]]))
