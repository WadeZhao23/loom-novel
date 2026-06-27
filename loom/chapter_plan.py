from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .backends import Backend, LoomBackendError
from .config import load_config
from .fsutil import atomic_write_text
from .guard import STEP, validate_output

Progress = Callable[[dict], None]
_CARD_START = "<!-- LOOM:CHAPTER-PLAN:START -->"
_CARD_END = "<!-- LOOM:CHAPTER-PLAN:END -->"


def _noop(event: dict) -> None:
    pass


def outline_path(project_root: Path, chapter_n: int) -> Path:
    return project_root / "正文" / ".细纲" / f"第{chapter_n}章.md"


def card_outline_path(project_root: Path) -> Path:
    return project_root / "外置大脑" / "卡章纲.md"


def _validate(project_root: Path, total: int, start_from: int) -> None:
    if not (project_root / "loom.toml").is_file():
        raise FileNotFoundError(f"{project_root} is not a loom project (missing loom.toml).")
    if total < 1:
        raise ValueError("total must be at least 1")
    if start_from < 1:
        raise ValueError("start_from must be at least 1")
    if start_from > total:
        raise ValueError("start_from cannot be greater than total")


def _read_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _clip(text: str, limit: int = 2400) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...(已截断)"


def _background(text: str, limit: int = 2400) -> str:
    text = _clip(text, limit)
    return re.sub(r"第\s*(\d+)\s*章", r"第\1节", text)


def _section(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        body = "（暂无）"
    return f"## {title}\n{body}"


def _managed_card_blocks(text: str) -> dict[int, str]:
    blocks: dict[int, str] = {}
    for match in re.finditer(r"^### 第(\d+)章\s*\n(.*?)(?=^### 第\d+章\s*\n|\Z)", text, re.MULTILINE | re.DOTALL):
        blocks[int(match.group(1))] = match.group(2).strip()
    return blocks


def _render_managed_card(blocks: dict[int, str]) -> str:
    parts = [_CARD_START, "## AI 批量章节规划"]
    for chapter_n in sorted(blocks):
        parts.append(f"### 第{chapter_n}章\n{blocks[chapter_n].strip()}")
    parts.append(_CARD_END)
    return "\n\n".join(parts)


def _sync_card_outline(project_root: Path, chapter_n: int, outline: str) -> None:
    path = card_outline_path(project_root)
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    start = original.find(_CARD_START)
    end = original.find(_CARD_END)

    if start != -1 and end != -1 and start < end:
        managed = original[start + len(_CARD_START):end]
        prefix = original[:start].rstrip()
        suffix = original[end + len(_CARD_END):].strip()
    else:
        managed = ""
        prefix = original.rstrip()
        suffix = ""

    blocks = _managed_card_blocks(managed)
    blocks[chapter_n] = outline.strip()

    pieces = []
    if prefix:
        pieces.append(prefix)
    pieces.append(_render_managed_card(blocks))
    if suffix:
        pieces.append(suffix)
    atomic_write_text(path, "\n\n".join(pieces).rstrip() + "\n")


def _build_prompt(project_root: Path, chapter_n: int, total: int, title: str) -> tuple[str, str]:
    world = _background(_read_if_exists(project_root / "外置大脑" / "世界观.md"))
    characters = _background(_read_if_exists(project_root / "外置大脑" / "人物卡.md"))
    card_outline = _background(_read_if_exists(card_outline_path(project_root)))
    previous = _background(_read_if_exists(outline_path(project_root, chapter_n - 1)), 1200) if chapter_n > 1 else ""

    system = (
        "你是网文大纲师。只输出本章可编辑细纲，不要解释你的工作过程。"
        "细纲要具体到场景推进、冲突变化、反转和章末钩子。"
    )
    user = "\n\n".join(
        [
            f"# 书名：{title}",
            f"# 当前任务：为第 {chapter_n} 章生成细纲（全书预计 {total} 章）",
            _section("卡章纲", card_outline),
            _section("世界观", world),
            _section("人物卡", characters),
            _section("上一章细纲", previous) if previous else "",
            "## 输出要求\n只输出第{n}章细纲正文，内容可以简洁，但必须非空、可直接保存。".format(n=chapter_n),
        ]
    )
    return system, user


def plan_chapters(
    project_root: Path,
    total: int,
    backend: Backend,
    *,
    start_from: int = 1,
    force: bool = False,
    progress: Progress = _noop,
) -> dict:
    _validate(project_root, total, start_from)
    config = load_config(project_root)

    planned = 0
    skipped = 0
    planned_chapters: list[int] = []

    for chapter_n in range(start_from, total + 1):
        path = outline_path(project_root, chapter_n)
        progress({"type": "progress", "chapter": chapter_n, "total": total})

        if not force and _read_if_exists(path):
            skipped += 1
            progress({"type": "skip", "chapter": chapter_n, "path": str(path)})
            continue

        system, user = _build_prompt(project_root, chapter_n, total, config.title)
        outline = backend.complete(system, user, max_chars=700).strip()
        reasons = validate_output(outline, STEP)
        if reasons:
            raise LoomBackendError("细纲生成失败:" + "；".join(reasons), code="model_output_invalid")

        atomic_write_text(path, outline + "\n")
        _sync_card_outline(project_root, chapter_n, outline)
        planned += 1
        planned_chapters.append(chapter_n)
        progress({"type": "done", "chapter": chapter_n, "outline": outline, "path": str(path)})

    progress({"type": "complete", "planned": planned, "skipped": skipped})
    return {"planned": planned, "skipped": skipped, "chapters": planned_chapters}
