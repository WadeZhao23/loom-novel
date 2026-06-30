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


def safe_chapter_filename(order: int, title: str) -> str:
    safe_title = _UNSAFE_FILENAME.sub("-", title.strip()).rstrip(" .")
    if not safe_title:
        safe_title = "未命名"
    return f"{order:04d}-{safe_title}.md"


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
    destination = Path(parent_dir).expanduser() / name

    with store.lock(task_id):
        task = store.get(task_id)
        if task.get("status") != "completed":
            raise ImportJobConflict(
                f"Import task status must be completed, got {task.get('status')!r}"
            )
        if task.get("result_revision") != task.get("chapter_revision"):
            raise ImportJobConflict("Import results are stale for the current chapter revision")

        results = store.get_results(task_id)
        if set(results) != set(_BRAIN_RESULTS):
            raise ImportJobConflict("Import results are missing or incomplete")
        chapters = store.get_chapters(task_id)

        if destination.exists():
            raise FileExistsError(f"Destination already exists: {destination}")

        try:
            root = scaffold.init(name, Path(parent_dir).expanduser(), genre)
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
                raise type(exc)(message) from exc
            raise RuntimeError(message) from exc
