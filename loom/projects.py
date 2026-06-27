"""Project registry storage for Loom."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .config import global_config_dir
from .fsutil import atomic_write_text


def _empty_registry() -> dict:
    return {"default_dir": "", "projects": {}}


def registry_path() -> Path:
    return global_config_dir() / "projects.json"


def load_registry() -> dict:
    path = registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_registry()

    if not isinstance(data, dict):
        return _empty_registry()

    registry = _empty_registry()
    if isinstance(data.get("default_dir"), str):
        registry["default_dir"] = data["default_dir"]
    if isinstance(data.get("projects"), dict):
        registry["projects"] = deepcopy(data["projects"])
    return registry


def save_registry(data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(registry_path(), text)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve(path: Path) -> Path:
    return Path(path).expanduser().resolve()


def _name_for_path(projects: dict, path: Path) -> str | None:
    resolved = str(path)
    for name, entry in projects.items():
        if entry.get("path") == resolved:
            return name
    return None


def _available_name(projects: dict, base: str) -> str:
    if base not in projects:
        return base

    suffix = 2
    while f"{base} ({suffix})" in projects:
        suffix += 1
    return f"{base} ({suffix})"


def register(path: Path, *, default_dir: Path | None = None) -> dict:
    root = _resolve(path)
    data = load_registry()
    projects = data["projects"]
    now = _now()

    existing_name = _name_for_path(projects, root)
    if existing_name is not None:
        projects[existing_name]["last_open"] = now
    else:
        name = _available_name(projects, root.name)
        projects[name] = {
            "path": str(root),
            "created": now,
            "last_open": now,
        }

    if default_dir is not None:
        data["default_dir"] = str(_resolve(default_dir))

    save_registry(data)
    return data


def list_all() -> dict:
    data = load_registry()
    for entry in data["projects"].values():
        entry["exists"] = Path(entry.get("path", "")).exists()
    return data


def remove(name: str) -> bool:
    data = load_registry()
    if name not in data["projects"]:
        return False
    del data["projects"][name]
    save_registry(data)
    return True


def set_default_dir(path: Path) -> dict:
    data = load_registry()
    data["default_dir"] = str(_resolve(path))
    save_registry(data)
    return data


def get_default_dir() -> str:
    return load_registry()["default_dir"]
