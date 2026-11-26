"""Read the team repository's main branch and stage an isolated plugin version."""

import importlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import ModuleType
from urllib.request import Request, urlopen
from zipfile import ZipFile


REPOSITORY = "cy873994525-blip/GIS-"
API = f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main"
ARCHIVE = f"https://codeload.github.com/{REPOSITORY}/zip/"
COMMIT = re.compile(r"[0-9a-f]{40}")
ARCHIVE_LIMIT = 8 * 1024 * 1024
PAYLOAD_LIMIT = 16 * 1024 * 1024
LOCAL = Path(__file__).resolve().parent


def download(url, limit):
    request = Request(url, headers={
        "User-Agent": "GIS-Cost-Path-QGIS",
        "Cache-Control": "no-cache",
    })
    with urlopen(request, timeout=6) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("GitHub response exceeds the size limit")
    return data


def payload_path(path):
    if path.parts[0] == "qgis_cost_path":
        relative = PurePosixPath(*path.parts[1:])
        if relative.name not in {"__init__.py", "plugin.py", "metadata.txt", "github_sync.py"}:
            return relative
    if path.parts[0] == "cost_path" or path.as_posix() in {
        "cost_raster.py", "coord_transform.py", "cost_rules.py",
        "contract.py", "golden_cases.py",
    }:
        return PurePosixPath("core") / path
    if path.parts[0] == "sample_data" and path.suffix == ".json":
        return path
    return None


def stage_revision(cache, sha, archive_data):
    if not COMMIT.fullmatch(sha):
        raise ValueError("Invalid GitHub commit SHA")
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / sha
    if destination.is_dir():
        return destination

    with TemporaryDirectory(dir=cache) as temp, ZipFile(io.BytesIO(archive_data)) as archive:
        staging = Path(temp) / "payload"
        staging.mkdir()
        total_size = 0
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            archive_path = PurePosixPath(entry.filename)
            if (len(archive_path.parts) < 2 or archive_path.parts[0] != f"GIS--{sha}"
                    or ".." in archive_path.parts or "\\" in entry.filename
                    or any(":" in part for part in archive_path.parts)):
                raise ValueError("Unexpected repository archive path")
            relative = payload_path(PurePosixPath(*archive_path.parts[1:]))
            if relative is None:
                continue
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Symlinks are unsupported in the plugin")
            total_size += entry.file_size
            if total_size > PAYLOAD_LIMIT:
                raise ValueError("Plugin files exceed the size limit")
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)

        if not (staging / "dialog.py").is_file():
            shutil.copy2(LOCAL / "dialog.py", staging / "dialog.py")
        required = (
            "core/cost_raster.py", "core/coord_transform.py", "core/cost_rules.py",
            "core/contract.py", "core/golden_cases.py",
            "core/cost_path/__init__.py", "core/cost_path/engine.py",
            "qgis_layers.py", "sample_data/cost_grid_4x4.json",
            "sample_data/cost_grid_5x5.json", "sample_data/cost_grid_10x10.json",
            "sample_data/cost_grid_4x4_map.json",
        )
        for name in required:
            if not (staging / name).is_file():
                raise ValueError(f"Required plugin file missing: {name}")
        for source_file in staging.rglob("*.py"):
            compile(source_file.read_bytes(), str(source_file), "exec")
        try:
            staging.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
    return destination


def fetch_revision(task, cache):
    sha = json.loads(download(API, 32 * 1024))["object"]["sha"]
    if not isinstance(sha, str) or not COMMIT.fullmatch(sha):
        raise ValueError("Invalid GitHub commit SHA")
    if not task.isCanceled() and not (cache / sha).is_dir():
        stage_revision(cache, sha, download(ARCHIVE + sha, ARCHIVE_LIMIT))
    return sha


def last_working_revision(cache):
    try:
        sha = (cache / "last-working").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return sha if COMMIT.fullmatch(sha) and (cache / sha).is_dir() else None


def mark_working(cache, sha):
    with NamedTemporaryFile(mode="w", encoding="ascii", dir=cache, delete=False) as file:
        file.write(sha + "\n")
    Path(file.name).replace(cache / "last-working")


def dialog_class(cache, sha):
    # An isolated package gives each revision its own relative imports and modules.
    name = f"{__package__}._revision_{sha}"
    if name not in sys.modules:
        package = ModuleType(name)
        package.__package__ = name
        package.__path__ = [str(cache / sha)]
        sys.modules[name] = package
    return importlib.import_module(f"{name}.dialog").CostPathDialog

