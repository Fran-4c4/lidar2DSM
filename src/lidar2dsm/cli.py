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
    repository = commands.add_parser("repository", help="Initialize and ingest a tiled LiDAR repository")
    repository_commands = repository.add_subparsers(dest="repository_command", required=True)
    repository_init = repository_commands.add_parser("init", help="Create or validate repository folders and catalogue")
    repository_init.add_argument("config", type=Path, help="Repository JSON configuration")
    repository_ingest = repository_commands.add_parser("ingest", help="Copy or move a LAS/LAZ directory into the repository")
    repository_ingest.add_argument("config", type=Path, help="Repository JSON configuration")
    repository_ingest.add_argument("input", type=Path, help="Input directory searched recursively")
    repository_ingest.add_argument("--mode", choices=("copy", "move"), default=None,
                                   help="copy keeps inputs; move removes them only after verification (default: copy)")
    repository_import = repository_commands.add_parser("import", help="Run a reproducible import job JSON")
    repository_import.add_argument("job", type=Path, help="Import job JSON configuration")
    repository_generate = repository_commands.add_parser("generate", help="Generate a versioned DTM/DSM/nDSM product job")
    repository_generate.add_argument("job", type=Path, help="Product job JSON configuration")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            from .demo import create_demo
            create_demo(args.output)
            print(f"Demo created: {args.output / 'config.json'}")
        elif args.command == "repository":
            from .repository import ingest_repository, init_repository, load_repository_config, run_import_job
            if args.repository_command == "init":
                config = load_repository_config(args.config)
                result = init_repository(config)
            elif args.repository_command == "ingest":
                from .repository import DEFAULT_TRANSFER_MODE
                config = load_repository_config(args.config)
                result = ingest_repository(
                    config, args.input, args.mode or DEFAULT_TRANSFER_MODE,
                    progress=print,
                )
            elif args.repository_command == "import":
                result = run_import_job(args.job, progress=print)
            else:
                from .products import generate_products
                result = generate_products(args.job)
            print(json.dumps(result, indent=2))
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
