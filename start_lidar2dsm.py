"""Dependency-aware interactive launcher for a source checkout."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent
REQUIRED_MODULES = ("numpy", "scipy", "rasterio", "laspy", "lazrs", "pyproj")


class ActionCancelled(Exception):
    """A user closed a picker or cancelled an interactive action."""


def _environment_python() -> Path:
    environment = ROOT / ".venv"
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _inside_project_environment() -> bool:
    return Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()


def _run_with_project_python(arguments: list[str]) -> int:
    """Delegate once to .venv while preserving console, action and JSON paths."""
    command = [str(_environment_python()), str(Path(__file__).resolve()), *arguments]
    try:
        return subprocess.run(command).returncode
    except KeyboardInterrupt:
        return 130


def _ensure_runtime(arguments: list[str]) -> tuple[bool, int]:
    """Use the project venv on every run; install only when it is incomplete."""
    python = _environment_python()
    if not _inside_project_environment():
        if python.is_file():
            return False, _run_with_project_python(arguments)
        if sys.version_info < (3, 12):
            print("Python 3.12 or later is required to create .venv.")
            return False, 2
        answer = input(f"Create {ROOT / '.venv'} and install dependencies? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("A project virtual environment is required by this launcher.")
            return False, 2
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
        completed = subprocess.run([str(python), "-m", "pip", "install", "-e", str(ROOT)])
        if completed.returncode != 0:
            print("Dependency installation failed.")
            return False, 2
        return False, _run_with_project_python(arguments)

    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if not missing:
        return True, 0
    print("The project .venv is incomplete: " + ", ".join(missing))
    answer = input("Install the missing project dependencies now? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        return False, 2
    completed = subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(ROOT)])
    if completed.returncode != 0:
        return False, 2
    remaining = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    return (not remaining), (0 if not remaining else 2)


def _path(text: str) -> Path:
    return Path(text.strip().strip('"')).expanduser().resolve()


def _ask_path(prompt: str, default: Path | None = None) -> Path:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if value:
        return _path(value)
    if default is None:
        raise ValueError(f"{prompt} is required")
    return default.resolve()


def _open_json(title: str) -> Path | None:
    """Use a native Windows picker so JSON selection does not depend on stdin."""
    if os.name != "nt":
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(
            parent=root,
            title=title,
            initialdir=str(Path.cwd()),
            filetypes=(("JSON configuration", "*.json"), ("All files", "*.*")),
        )
    finally:
        root.destroy()
    return Path(selected).resolve() if selected else None


def _choose_action() -> str:
    """Read one Windows console key; Enter is not required."""
    if os.name == "nt":
        try:
            import msvcrt
            print("Choose an action (press 1, 2, 3 or 4; no Enter required): ", end="", flush=True)
            while True:
                key = msvcrt.getwch()
                if key == "\x03":
                    raise KeyboardInterrupt
                if key in ("1", "2", "3", "4"):
                    print(key)
                    while msvcrt.kbhit():
                        msvcrt.getwch()
                    return key
        except ImportError:
            pass
    return input("Choose an action: ").strip()


def _write_new_json(path: Path, data: dict) -> None:
    if path.exists():
        raise ValueError(f"File already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Created: {path}")


def _create_repository_job() -> Path:
    config_path = _ask_path("Repository JSON", Path.cwd() / "repository.json")
    if config_path.exists():
        return config_path
    root = _ask_path("Repository destination", config_path.parent / "lidar-repository")
    grid_id = input("Grid ID (for example regcan95_utm28_1km_v1): ").strip()
    horizontal_crs = input("Projected metric CRS (for example EPSG:4083): ").strip()
    if not grid_id or not horizontal_crs:
        raise ValueError("Grid ID and horizontal CRS are required")
    resolution = float(input("Base resolution in metres [0.5]: ").strip() or "0.5")
    vertical = input("Vertical reference [unknown]: ").strip() or "unknown"
    relative_root = Path(root)
    try:
        relative_root = root.relative_to(config_path.parent)
    except ValueError:
        pass
    _write_new_json(config_path, {
        "repository_root": relative_root.as_posix(),
        "source_profile": "pnoa",
        "grid": {
            "grid_id": grid_id,
            "horizontal_crs": horizontal_crs,
            "origin_x_m": 0,
            "origin_y_m": 0,
            "tile_size_m": 1000,
            "resolution_m": resolution,
            "vertical_reference": vertical,
            "tile_id_template": "E{xmin}_N{ymin}"
        }
    })
    return config_path


def _create_import_job() -> Path:
    print(
        "\nSelect an existing import-job JSON, or choose a new filename and the "
        "launcher will create it.\nYou can drag a file from Explorer into this window."
    )
    selected = _open_json("Select an import-job JSON")
    if selected is not None:
        return selected
    if os.name == "nt":
        raise ActionCancelled("Import cancelled: no JSON file selected")
    path = _ask_path("Import job JSON", Path.cwd() / "import-job.json")
    if path.exists():
        return path
    repository = _ask_path("Repository JSON")
    delivery = _ask_path("LAS/LAZ input directory")
    mode = input("Transfer mode [copy/move, default copy]: ").strip().lower() or "copy"
    _write_new_json(path, {
        "repository": str(repository),
        "input_directory": str(delivery),
        "transfer_mode": mode,
    })
    return path


def _create_product_job() -> Path:
    print(
        "\nSelect an existing product-job JSON, or choose a new filename and the "
        "launcher will create it.\nYou can drag a file from Explorer into this window."
    )
    selected = _open_json("Select a product-job JSON")
    if selected is not None:
        return selected
    if os.name == "nt":
        raise ActionCancelled("Generation cancelled: no JSON file selected")
    path = _ask_path("Product job JSON", Path.cwd() / "product-job.json")
    if path.exists():
        return path
    repository = _ask_path("Repository JSON")
    release = input("New release ID: ").strip()
    requested = input("Products [dtm / dsm / all, default all]: ").strip().lower() or "all"
    products = {"dtm": ["dtm"], "dsm": ["dsm"], "all": ["dtm", "dsm", "ndsm"]}.get(requested)
    if products is None:
        raise ValueError("Products must be dtm, dsm or all")
    selection_type = input("Selection [all / bbox / tiles, default all]: ").strip().lower() or "all"
    if selection_type == "all":
        selection = {"all": True}
    elif selection_type == "bbox":
        values = [float(value.strip()) for value in input("BBOX xmin,ymin,xmax,ymax: ").split(",")]
        selection = {
            "bbox": values,
            "bbox_crs": input("BBOX CRS [EPSG:4326]: ").strip() or "EPSG:4326",
            "snap": "outward",
        }
    elif selection_type == "tiles":
        selection = {"tile_ids": [value.strip() for value in input("Tile IDs, comma separated: ").split(",") if value.strip()]}
    else:
        raise ValueError("Selection must be all, bbox or tiles")
    _write_new_json(path, {
        "repository": str(repository),
        "release_id": release,
        "products": products,
        "selection": selection,
        "processing": {},
    })
    return path


def _arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Guided or direct lidar2DSM repository launcher"
    )
    commands = parser.add_subparsers(dest="action")
    create = commands.add_parser("create", help="create or validate a repository")
    create.add_argument("config", type=Path)
    import_job = commands.add_parser("import", help="run an import-job JSON")
    import_job.add_argument("job", type=Path)
    generate = commands.add_parser("generate", help="run a product-job JSON")
    generate.add_argument("job", type=Path)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    ready, exit_code = _ensure_runtime(arguments)
    if not ready:
        return exit_code
    args = _arguments(arguments)
    sys.path.insert(0, str(ROOT / "src"))
    from lidar2dsm.products import generate_products
    from lidar2dsm.repository import init_repository, load_repository_config, run_import_job

    if args.action == "create":
        print(json.dumps(init_repository(load_repository_config(args.config)), indent=2))
        return 0
    if args.action == "import":
        print(json.dumps(run_import_job(args.job, progress=print), indent=2))
        return 0
    if args.action == "generate":
        result = generate_products(args.job)
        print(json.dumps({
            "status": result["status"], "release_id": result["release_id"],
            "tiles": len(result["selected_tiles"]),
        }, indent=2))
        return 0

    while True:
        print(
            "\nlidar2DSM\n\n1. Create repository\n2. Import LAS/LAZ delivery\n"
            "3. Generate products\n4. Exit\n\n"
            "The selected action may ask for a JSON path. Prompts ending in ':' are waiting for input."
        )
        try:
            choice = _choose_action()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return 0
        try:
            if choice == "1":
                path = _create_repository_job()
                print(json.dumps(init_repository(load_repository_config(path)), indent=2))
            elif choice == "2":
                print("\nOption 2 selected: import LAS/LAZ delivery.")
                print(json.dumps(run_import_job(_create_import_job(), progress=print), indent=2))
            elif choice == "3":
                print("\nOption 3 selected: generate products.")
                result = generate_products(_create_product_job())
                print(json.dumps({
                    "status": result["status"], "release_id": result["release_id"],
                    "tiles": len(result["selected_tiles"]),
                }, indent=2))
            elif choice == "4":
                return 0
            else:
                print("Choose 1, 2, 3 or 4.")
        except KeyboardInterrupt:
            print("\nAction cancelled. No running import or generation was forced to continue.")
        except ActionCancelled as error:
            print(error)
        except (ValueError, OSError, RuntimeError, ImportError) as error:
            print(f"Error: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
