from __future__ import annotations

import re
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterSplit:
    chapters: list[dict]
    confidence: str


_HEADING_RE = re.compile(
    r"^[ \t]*(?P<title>"
    r"(?:第[0-9零〇一二两三四五六七八九十百千万]+[章回]|"
    r"卷[0-9零〇一二两三四五六七八九十百千万]+|序章|楔子|后记)"
    r"(?:[ \t]+[^\r\n]*)?)[ \t]*$",
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
    preface = text[: matches[0].start()].strip()
    if preface:
        chapters.append(_new_chapter(1, "序章", preface))

    for index, match in enumerate(matches):
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append(
            _new_chapter(
                len(chapters) + 1,
                match.group("title").strip(),
                text[content_start:content_end].strip(),
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
    paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n+", text.strip()) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        if not paragraph:
            continue
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
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
    if not left:
        return right
    if not right:
        return left
    return f"{left.rstrip()}\n\n{right.lstrip()}"
