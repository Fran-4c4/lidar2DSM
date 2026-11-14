"""Public CLI; no environment secrets, task registry or sibling checkouts."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert local LAS/LAZ to DTM, DSM and nDSM GeoTIFFs")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "validate"):
        command = commands.add_parser(name)
        command.add_argument("config", type=Path, help="JSON configuration; relative paths use its directory")
        if name == "run":
            command.add_argument("--output", type=Path, required=True, help="New execution directory")
    demo = commands.add_parser("demo", help="Generate original synthetic LAS, config and truth")
    demo.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            from .demo import create_demo
            create_demo(args.output)
            print(f"Demo created: {args.output / 'config.json'}")
        else:
            from .config import load_config
            config = load_config(args.config.resolve())
            if args.command == "validate":
                from .grid import inspect
                paths, crs, grid, sources = inspect(config)
                print(json.dumps({"status": "headers_valid", "files": len(paths),
                    "points_in_headers": sum(s["points"] for s in sources),
                    "crs": crs.to_string(), "grid": grid.to_dict(),
                    "note": "Header validation only; point classes and coverage checked during run"}, indent=2))
            else:
                from .engine import run
                run(config, args.output)
        return 0
    except (ValueError, OSError, RuntimeError, ImportError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        # Native readers expose different exception families for corrupt LAS,
        # GeoTIFF and CRS data. Keep the CLI exit contract; run() records failure.
        print(f"Processing error ({type(error).__name__}): {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
