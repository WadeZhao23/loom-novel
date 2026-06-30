from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .backends import Backend
from .import_jobs import ImportJobConflict, ImportJobStore


Progress = Callable[[dict], None]
PHASES = ("worldview", "system", "characters", "outlines")

_EXTRACTION_PROMPTS = {
    "worldview": (
        "phase=worldview\n"
        "你是世界观设定提取器。仅从给定章节提取地点、势力、规则、历史与硬性约束。"
        "仅输出结构清晰的 Markdown 正文，不要 JSON，不要解释任务。"
    ),
    "system": (
        "phase=system\n"
        "你是小说体系提取器。仅从给定章节提取能力、等级、资源、机制、限制与代价。"
        "仅输出结构清晰的 Markdown 正文，不要 JSON，不要解释任务。"
    ),
    "characters": (
        "phase=characters\n"
        "你是人物档案提取器。仅从给定章节提取人物身份、关系、动机、能力与状态变化。"
        "仅输出结构清晰的 Markdown 正文，不要 JSON，不要解释任务。"
    ),
}

_OUTLINE_PROMPT = (
    "phase=outlines\n"
    "你是章节大纲提取器。概括本章目标、冲突、关键转折、结果与章末钩子。"
    "仅输出 Markdown 正文，不要添加章节标题，不要 JSON，不要解释任务。"
)


def chunk_chapters(
    chapters: list[dict], *, char_budget: int = 12_000
) -> list[list[dict]]:
    if (
        not isinstance(char_budget, int)
        or isinstance(char_budget, bool)
        or char_budget <= 0
    ):
        raise ValueError("char_budget must be a positive integer")
    if not chapters:
        return []

    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_size = 0
    for chapter in chapters:
        size = len(_render_chapters([chapter]))
        separator_size = 2 if current else 0
        if current and current_size + separator_size + size > char_budget:
            chunks.append(current)
            current = []
            current_size = 0
            separator_size = 0
        current.append(chapter)
        current_size += separator_size + size
    if current:
        chunks.append(current)
    return chunks


def run_parse(
    store: ImportJobStore,
    task_id: str,
    backend: Backend,
    *,
    progress: Progress | None = None,
    char_budget: int = 12_000,
) -> dict:
    # Validate the public option before changing durable task state.
    chunk_chapters([], char_budget=char_budget)

    while True:
        with store.lock(task_id):
            task = store.get(task_id)
            _validate_parse_status(task.get("status"))
            revision = task["chapter_revision"]

        all_chapters = store.get_chapters(task_id)
        selected = sorted(
            (chapter for chapter in all_chapters if chapter.get("selected") is True),
            key=lambda chapter: chapter["order"],
        )
        selected_ids = [chapter["id"] for chapter in selected]
        chunks = chunk_chapters(selected, char_budget=char_budget)
        extraction_units = len(chunks) + max(0, len(chunks) - 1)
        total = extraction_units * 3 + len(selected)

        with store.lock(task_id):
            current = store.get(task_id)
            _validate_parse_status(current.get("status"))
            if current.get("chapter_revision") != revision:
                continue
            if not selected:
                raise ValueError("At least one selected chapter is required")
            store.update(
                task_id,
                status="running",
                phase=None,
                progress={"completed": 0, "total": total},
                error=None,
            )
        break

    completed = 0
    current_phase: str | None = None

    def emit(event: dict) -> None:
        if progress is not None:
            progress(event)

    def begin_phase(phase: str) -> None:
        nonlocal current_phase
        current_phase = phase
        store.update(
            task_id,
            phase=phase,
            progress={"completed": completed, "total": total},
        )
        emit({"type": "phase", "phase": phase, "completed": completed, "total": total})

    def advance(phase: str) -> None:
        nonlocal completed
        completed += 1
        store.update(task_id, progress={"completed": completed, "total": total})
        emit(
            {
                "type": "progress",
                "phase": phase,
                "completed": completed,
                "total": total,
            }
        )

    results: dict[str, str] = {}
    try:
        for phase in PHASES[:-1]:
            begin_phase(phase)
            results[phase] = _run_extraction_phase(
                store,
                task_id,
                backend,
                phase,
                chunks,
                revision,
                selected_ids,
                char_budget,
                advance,
            )
            emit(
                {
                    "type": "phase_done",
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                }
            )

        phase = "outlines"
        begin_phase(phase)
        results[phase] = _run_outlines_phase(
            store,
            task_id,
            backend,
            selected,
            revision,
            selected_ids,
            char_budget,
            advance,
        )
        emit(
            {
                "type": "phase_done",
                "phase": phase,
                "completed": completed,
                "total": total,
            }
        )

        with store.lock(task_id):
            store.save_results(task_id, results)
            store.update(
                task_id,
                status="completed",
                result_revision=revision,
                progress={"completed": total, "total": total},
                error=None,
            )
        emit({"type": "complete", "completed": total, "total": total})
        return results
    except Exception as exc:
        message = str(exc)
        with store.lock(task_id):
            store.update(
                task_id,
                status="failed",
                phase=current_phase,
                progress={"completed": completed, "total": total},
                error={"message": message},
            )
        emit(
            {
                "type": "error",
                "phase": current_phase,
                "message": message,
            }
        )
        raise


def _validate_parse_status(status: object) -> None:
    if status == "running":
        raise ImportJobConflict("Import job is already running")
    if status == "completed":
        raise ImportJobConflict("Completed import job cannot be parsed again")
    if status not in {"ready", "failed", "interrupted"}:
        raise ValueError(f"Import job is not ready for parsing: {status}")


def _run_extraction_phase(
    store: ImportJobStore,
    task_id: str,
    backend: Backend,
    phase: str,
    chunks: list[list[dict]],
    revision: int,
    selected_ids: list[str],
    char_budget: int,
    advance: Callable[[str], None],
) -> str:
    rendered = [_render_chapters(chunk) for chunk in chunks]
    hashes = [
        _input_hash(phase, revision, selected_ids, chunk_text) for chunk_text in rendered
    ]
    checkpoint = _read_checkpoint(store, task_id, phase)
    checkpoint_valid = (
        checkpoint is not None
        and checkpoint.get("phase") == phase
        and checkpoint.get("revision") == revision
    )
    old_chunks = checkpoint.get("chunks", []) if checkpoint_valid else []
    reusable: dict[int, dict] = {}
    if isinstance(old_chunks, list):
        for item in old_chunks:
            if not isinstance(item, dict) or set(item) != {"index", "input_hash", "output"}:
                continue
            index = item.get("index")
            if (
                isinstance(index, int)
                and 0 <= index < len(hashes)
                and item.get("input_hash") == hashes[index]
                and isinstance(item.get("output"), str)
            ):
                reusable[index] = item

    all_reused = len(reusable) == len(chunks)
    records = dict(reusable)
    outputs: list[str] = []
    for index, chunk_text in enumerate(rendered):
        if index in reusable:
            output = reusable[index]["output"]
        else:
            output = backend.complete(
                _EXTRACTION_PROMPTS[phase],
                chunk_text,
                max_chars=char_budget,
            )
            records[index] = {
                "index": index,
                "input_hash": hashes[index],
                "output": output,
            }
            _commit_checkpoint(
                store,
                task_id,
                phase,
                revision,
                [records[key] for key in sorted(records)],
                "",
            )
        outputs.append(output)
        advance(phase)

    old_merged = checkpoint.get("merged") if checkpoint_valid else None
    merge_units = max(0, len(outputs) - 1)
    if all_reused and isinstance(old_merged, str) and old_merged:
        merged = old_merged
        for _ in range(merge_units):
            advance(phase)
    else:
        merged = _merge_outputs(backend, phase, outputs, char_budget, advance)

    final_records = [records[index] for index in range(len(chunks))]
    _commit_checkpoint(store, task_id, phase, revision, final_records, merged)
    return merged


def _merge_outputs(
    backend: Backend,
    phase: str,
    outputs: list[str],
    char_budget: int,
    advance: Callable[[str], None],
) -> str:
    if len(outputs) == 1:
        return outputs[0]

    current = list(outputs)
    while len(current) > 1:
        next_round: list[str] = []
        for index in range(0, len(current), 2):
            batch = current[index : index + 2]
            if len(batch) == 1:
                next_round.append(batch[0])
                continue
            merged = backend.complete(
                f"phase={phase} merge\n"
                "合并下面两份提取结果，去重并保留所有明确约束。"
                "仅输出结构清晰的 Markdown 正文，不要 JSON，不要解释任务。",
                "\n\n---\n\n".join(batch),
                max_chars=char_budget,
            )
            next_round.append(merged)
            advance(phase)
        current = next_round
    return current[0]


def _run_outlines_phase(
    store: ImportJobStore,
    task_id: str,
    backend: Backend,
    chapters: list[dict],
    revision: int,
    selected_ids: list[str],
    char_budget: int,
    advance: Callable[[str], None],
) -> str:
    phase = "outlines"
    rendered = [_render_chapters([chapter]) for chapter in chapters]
    hashes = [
        _input_hash(phase, revision, selected_ids, chapter_text)
        for chapter_text in rendered
    ]
    checkpoint = _read_checkpoint(store, task_id, phase)
    checkpoint_valid = (
        checkpoint is not None
        and checkpoint.get("phase") == phase
        and checkpoint.get("revision") == revision
    )
    old_chunks = checkpoint.get("chunks", []) if checkpoint_valid else []
    reusable: dict[int, dict] = {}
    if isinstance(old_chunks, list):
        for item in old_chunks:
            if not isinstance(item, dict) or set(item) != {"index", "input_hash", "output"}:
                continue
            index = item.get("index")
            if (
                isinstance(index, int)
                and 0 <= index < len(hashes)
                and item.get("input_hash") == hashes[index]
                and isinstance(item.get("output"), str)
            ):
                reusable[index] = item

    records = dict(reusable)
    outputs: list[str] = []
    for index, chapter_text in enumerate(rendered):
        if index in reusable:
            output = reusable[index]["output"]
        else:
            output = backend.complete(
                _OUTLINE_PROMPT,
                chapter_text,
                max_chars=char_budget,
            )
            records[index] = {
                "index": index,
                "input_hash": hashes[index],
                "output": output,
            }
            _commit_checkpoint(
                store,
                task_id,
                phase,
                revision,
                [records[key] for key in sorted(records)],
                "",
            )
        outputs.append(output)
        advance(phase)

    merged = "\n\n".join(
        f"## {chapter['title']}\n\n{output}" for chapter, output in zip(chapters, outputs)
    )
    final_records = [records[index] for index in range(len(chapters))]
    _commit_checkpoint(store, task_id, phase, revision, final_records, merged)
    return merged


def _render_chapters(chapters: list[dict]) -> str:
    return "\n\n".join(
        f"# {chapter['title']}\n\n{chapter['content']}" for chapter in chapters
    )


def _input_hash(
    phase: str, revision: int, selected_ids: list[str], chunk_text: str
) -> str:
    payload = json.dumps(
        {
            "phase": phase,
            "revision": revision,
            "selected_chapter_ids": selected_ids,
            "chunk_text": chunk_text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_checkpoint(
    store: ImportJobStore, task_id: str, phase: str
) -> dict | None:
    path = store.checkpoint_path(task_id, phase)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {"phase", "revision", "chunks", "merged"}:
        return None
    return value


def _commit_checkpoint(
    store: ImportJobStore,
    task_id: str,
    phase: str,
    revision: int,
    chunks: list[dict],
    merged: str,
) -> None:
    checkpoint = {
        "phase": phase,
        "revision": revision,
        "chunks": chunks,
        "merged": merged,
    }
    payload = json.dumps(checkpoint, ensure_ascii=False, indent=2).encode("utf-8")
    path = store.checkpoint_path(task_id, phase)
    with store.lock(task_id):
        _atomic_write(path, payload)


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ChapterSplit:
    chapters: list[dict]
    confidence: str


_HEADING_RE = re.compile(
    r"^[ \t]*(?P<title>"
    r"(?:第[0-9零〇一二两三四五六七八九十百千万]+[章回]|"
    r"卷[0-9零〇一二两三四五六七八九十百千万]+|序章|楔子|后记)"
    r"(?:[ \t]+(?![ \t]*[:：\-—])[^\r\n]*|"
    r"[ \t]*[:：\-—][ \t]*[^\r\n \t:：\-—][^\r\n]*)?)"
    r"[ \t]*$",
    re.MULTILINE,
)


def decode_txt(raw: bytes) -> tuple[str, str]:
    if not isinstance(raw, bytes):
        raise ValueError("TXT 数据必须是字节")
    if raw and raw.count(b"\x00") / len(raw) > 0.01:
        raise ValueError("文件包含过多空字节，可能是二进制而非文本")

    candidates: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    candidates.extend(("utf-8", "gb18030"))

    for encoding in candidates:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            raise ValueError("TXT 内容为空（empty）")
        return text, encoding
    raise ValueError("无法将文件解码为文本")


def split_chapters(text: str, *, fallback_chars: int = 12_000) -> ChapterSplit:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("章节文本不能为空")
    if (
        not isinstance(fallback_chars, int)
        or isinstance(fallback_chars, bool)
        or fallback_chars <= 0
    ):
        raise ValueError("fallback_chars 必须是正整数")

    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        chunks = _fallback_chunks(text, fallback_chars)
        chapters = [
            _new_chapter(index, f"第{index}章", content)
            for index, content in enumerate(chunks, start=1)
        ]
        return ChapterSplit(chapters=chapters, confidence="low")

    chapters: list[dict] = []
    preface = text[: matches[0].start()]
    if preface.strip():
        chapters.append(_new_chapter(1, "序章", preface))

    for index, match in enumerate(matches):
        content_start = match.end()
        if text.startswith("\r\n", content_start):
            content_start += 2
        elif content_start < len(text) and text[content_start] in "\r\n":
            content_start += 1
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append(
            _new_chapter(
                len(chapters) + 1,
                match.group("title").strip(),
                text[content_start:content_end],
            )
        )
    return ChapterSplit(chapters=chapters, confidence="high")


def validate_chapters(chapters: list[dict]) -> None:
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("至少需要一个章节")
    if any(not isinstance(chapter, dict) for chapter in chapters):
        raise ValueError("每个章节必须是对象")

    ids = [chapter.get("id") for chapter in chapters]
    if any(not isinstance(chapter_id, str) or not chapter_id.strip() for chapter_id in ids):
        raise ValueError("每个章节都需要非空 ID")
    if len(ids) != len(set(ids)):
        raise ValueError("章节 ID 必须唯一")

    orders = [chapter.get("order") for chapter in chapters]
    if any(not isinstance(order, int) or isinstance(order, bool) for order in orders):
        raise ValueError("章节顺序必须是整数")
    if len(set(orders)) != len(chapters) or sorted(orders) != list(
        range(1, len(chapters) + 1)
    ):
        raise ValueError("章节顺序必须唯一且从 1 连续递增")

    if any(
        not isinstance(chapter.get("title"), str) or not chapter["title"].strip()
        for chapter in chapters
    ):
        raise ValueError("每个章节都需要非空标题")
    if any(not isinstance(chapter.get("content"), str) for chapter in chapters):
        raise ValueError("每个章节都需要文本内容")
    if any(not isinstance(chapter.get("selected"), bool) for chapter in chapters):
        raise ValueError("每个章节都需要 selected 标记")
    if not any(chapter["selected"] for chapter in chapters):
        raise ValueError("至少需要选择一个章节")


def split_chapter(chapters: list[dict], chapter_id: str, offset: int) -> list[dict]:
    result = _copy_chapters(chapters)
    index = _find_chapter(result, chapter_id)
    content = result[index]["content"]
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset <= 0
        or offset >= len(content)
    ):
        raise ValueError("拆分位置必须严格位于章节内容内部")

    original = result[index]
    original["content"] = content[:offset]
    continuation = {
        **original,
        "id": str(uuid.uuid4()),
        "title": f"{original['title'].strip()}（续）",
        "content": content[offset:],
    }
    result.insert(index + 1, continuation)
    return _renumber(result)


def merge_chapters(
    chapters: list[dict], chapter_id: str, *, direction: str
) -> list[dict]:
    result = _copy_chapters(chapters)
    index = _find_chapter(result, chapter_id)
    if direction == "previous":
        if index == 0:
            raise ValueError("第一章不能与前一章合并")
        left_index, right_index = index - 1, index
    elif direction == "next":
        if index == len(result) - 1:
            raise ValueError("最后一章不能与后一章合并")
        left_index, right_index = index, index + 1
    else:
        raise ValueError("direction 必须是 previous 或 next")

    left = result[left_index]
    right = result[right_index]
    left["content"] = _join_content(left["content"], right["content"])
    left["selected"] = left["selected"] or right["selected"]
    del result[right_index]
    return _renumber(result)


def move_chapter(chapters: list[dict], chapter_id: str, *, offset: int) -> list[dict]:
    result = _copy_chapters(chapters)
    index = _find_chapter(result, chapter_id)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValueError("offset 必须是整数")
    destination = index + offset
    if destination < 0 or destination >= len(result):
        raise ValueError("移动目标超出章节范围")
    moved = result.pop(index)
    result.insert(destination, moved)
    return _renumber(result)


def select_chapter_range(
    chapters: list[dict], *, start: int, end: int
) -> list[dict]:
    result = _copy_chapters(chapters)
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 1
        or end < start
        or end > len(result)
    ):
        raise ValueError("章节选择范围无效")
    for chapter in result:
        chapter["selected"] = start <= chapter["order"] <= end
    return _renumber(result)


def _new_chapter(order: int, title: str, content: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "order": order,
        "title": title,
        "content": content,
        "selected": True,
    }


def _fallback_chunks(text: str, limit: int) -> list[str]:
    boundary_ends = [match.end() for match in re.finditer(r"\n[ \t]*\n+", text)]
    chunks: list[str] = []
    start = 0
    boundary_index = 0
    while len(text) - start > limit:
        maximum_end = start + limit
        preferred_end = None
        while (
            boundary_index < len(boundary_ends)
            and boundary_ends[boundary_index] <= maximum_end
        ):
            if boundary_ends[boundary_index] > start:
                preferred_end = boundary_ends[boundary_index]
            boundary_index += 1
        end = preferred_end if preferred_end is not None else maximum_end
        chunks.append(text[start:end])
        start = end
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def _copy_chapters(chapters: list[dict]) -> list[dict]:
    validate_chapters(chapters)
    return [dict(chapter) for chapter in sorted(chapters, key=lambda row: row["order"])]


def _find_chapter(chapters: list[dict], chapter_id: str) -> int:
    for index, chapter in enumerate(chapters):
        if chapter["id"] == chapter_id:
            return index
    raise ValueError(f"未找到章节 ID: {chapter_id}")


def _renumber(chapters: list[dict]) -> list[dict]:
    for order, chapter in enumerate(chapters, start=1):
        chapter["order"] = order
    validate_chapters(chapters)
    return chapters


def _join_content(left: str, right: str) -> str:
    return left + right
