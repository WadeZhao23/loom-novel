from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import scaffold
from .fsutil import atomic_write_text
from .import_jobs import ImportJobConflict, ImportJobStore


_BRAIN_RESULTS = {
    "worldview": "世界观.md",
    "system": "修炼体系.md",
    "characters": "人物卡.md",
    "outlines": "卡章纲.md",
}
_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_MAX_CHAPTER_FILENAME_BYTES = 120
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_chapter_filename(order: int, title: str) -> str:
    prefix = f"{order:04d}-"
    suffix = ".md"
    safe_title = _UNSAFE_FILENAME.sub("-", title.strip()).rstrip(" .")
    if not safe_title:
        safe_title = "未命名"
    title_limit = (
        _MAX_CHAPTER_FILENAME_BYTES - len(prefix.encode()) - len(suffix.encode())
    )
    safe_title = safe_title.encode()[:title_limit].decode("utf-8", errors="ignore")
    safe_title = safe_title.rstrip(" .") or "未命名"
    return f"{prefix}{safe_title}{suffix}"


def _validate_project_name(name: str) -> None:
    candidate = Path(name)
    reserved_candidate = name.split(".", 1)[0].upper()
    if (
        not name.strip()
        or name != name.strip()
        or name in {".", ".."}
        or name.endswith((".", " "))
        or _UNSAFE_FILENAME.search(name)
        or reserved_candidate in _WINDOWS_RESERVED_NAMES
        or "/" in name
        or "\\" in name
        or candidate.is_absolute()
        or candidate.drive
        or candidate.name != name
    ):
        raise ValueError("Project name must be a nonempty single path component")


def materialize_import(
    store: ImportJobStore,
    task_id: str,
    *,
    name: str,
    parent_dir: Path,
    genre: str | None,
    include_source_chapters: bool,
    state_loader: Callable[[Path], dict],
    register: Callable[[Path], dict],
) -> dict:
    _validate_project_name(name)
    parent = Path(parent_dir).expanduser()

    with store.lock(task_id):
        task = store.get(task_id)
        if task.get("status") not in {"completed", "created"}:
            raise ImportJobConflict(
                "Import task status must be completed or created, "
                f"got {task.get('status')!r}"
            )
        if task.get("result_revision") != task.get("chapter_revision"):
            raise ImportJobConflict("Import results are stale for the current chapter revision")

        results = store.get_results(task_id)
        if set(results) != set(_BRAIN_RESULTS):
            raise ImportJobConflict("Import results are missing or incomplete")
        chapters = store.get_chapters(task_id)

        parent.mkdir(parents=True, exist_ok=True)
        parent = parent.resolve()
        destination = (parent / name).resolve()
        if destination.parent != parent:
            raise ValueError("Project destination must be directly under the parent path")
        try:
            destination.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise FileExistsError(f"Destination already exists: {destination}") from exc

        try:
            root = scaffold.init(name, parent, genre)
            brain_dir = root / "外置大脑"
            for result_name, filename in _BRAIN_RESULTS.items():
                content = results[result_name]
                atomic_write_text(
                    brain_dir / filename,
                    content if content.endswith("\n") else content + "\n",
                )

            if include_source_chapters:
                source_dir = root / "正文" / ".原稿"
                for chapter in chapters:
                    if not chapter["selected"]:
                        continue
                    content = chapter.get("content", "")
                    chapter_text = f"# {chapter['title']}\n\n{content.rstrip()}\n"
                    atomic_write_text(
                        source_dir
                        / safe_chapter_filename(chapter["order"], chapter["title"]),
                        chapter_text,
                    )

            state = state_loader(root)
            register(root)
            store.update(task_id, status="created")
            return state
        except Exception as exc:
            message = f"{exc} (project preserved at {destination})"
            if isinstance(exc, ValueError):
                raise ValueError(message) from exc
            raise RuntimeError(message) from exc
