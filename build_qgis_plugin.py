"""Package the QGIS plugin with the current repository's engine and samples."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
PLUGIN = "qgis_cost_path"


def build(output):
    plugin_files = ("__init__.py", "metadata.txt", "plugin.py", "dialog.py", "github_sync.py")
    core_files = ("cost_raster.py", "cost_path/__init__.py", "cost_path/engine.py")
    samples = ("cost_grid_4x4.json", "cost_grid_5x5.json", "cost_grid_10x10.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in plugin_files:
            archive.write(ROOT / PLUGIN / name, f"{PLUGIN}/{name}")
        archive.writestr(f"{PLUGIN}/core/__init__.py", "")
        for name in core_files:
            archive.write(ROOT / name, f"{PLUGIN}/core/{name}")
        for name in samples:
            archive.write(ROOT / "sample_data" / name, f"{PLUGIN}/sample_data/{name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"{PLUGIN}.zip")
    args = parser.parse_args()
    build(args.output)
    print(args.output.resolve())
