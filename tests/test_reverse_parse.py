from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest

from loom.reverse_parse import (
    decode_txt,
    merge_chapters,
    move_chapter,
    select_chapter_range,
    split_chapter,
    split_chapters,
    validate_chapters,
)


TEXT = "第1章 初见\n甲。\n\n第2章 冲突\n乙。\n"


def chapter(
    chapter_id: str,
    order: int,
    title: str,
    content: str,
    *,
    selected: bool = True,
) -> dict:
    return {
        "id": chapter_id,
        "order": order,
        "title": title,
        "content": content,
        "selected": selected,
    }


def sample_chapters() -> list[dict]:
    return [
        chapter("c1", 1, "第一章", "甲。\n乙。"),
        chapter("c2", 2, "第二章", "丙。"),
    ]


@pytest.mark.parametrize(
    ("raw", "expected_text", "expected_encoding"),
    [
        (b"\xef\xbb\xbfline 1\r\nline 2\r", "line 1\nline 2\n", "utf-8-sig"),
        ("纯文本\r下一行".encode(), "纯文本\n下一行", "utf-8"),
        ("中文内容".encode("gb18030"), "中文内容", "gb18030"),
    ],
)
def test_decode_txt_detects_encoding_and_normalizes_newlines(
    raw: bytes, expected_text: str, expected_encoding: str
) -> None:
    assert decode_txt(raw) == (expected_text, expected_encoding)


@pytest.mark.parametrize("raw", [b"", b" \r\n\t"])
def test_decode_txt_rejects_empty_text(raw: bytes) -> None:
    with pytest.raises(ValueError, match="空|empty"):
        decode_txt(raw)


def test_decode_txt_rejects_binary_data() -> None:
    with pytest.raises(ValueError, match="二进制|binary|文本"):
        decode_txt(b"a" * 98 + b"\x00\x00")


def test_split_chapters_detects_common_headings_with_high_confidence() -> None:
    result = split_chapters(TEXT)

    assert result.confidence == "high"
    assert [row["title"] for row in result.chapters] == ["第1章 初见", "第2章 冲突"]
    assert [row["content"] for row in result.chapters] == ["甲。", "乙。"]
    assert [row["order"] for row in result.chapters] == [1, 2]
    assert [row["selected"] for row in result.chapters] == [True, True]
    assert len({row["id"] for row in result.chapters}) == 2
    assert all(str(UUID(row["id"])) == row["id"] for row in result.chapters)


@pytest.mark.parametrize(
    "title",
    ["第十二章 风起", "第12章 风起", "第12回 风起", "卷一 风起", "序章", "楔子", "后记"],
)
def test_split_chapters_supports_required_heading_forms(title: str) -> None:
    result = split_chapters(f"{title}\n正文。\n")

    assert result.confidence == "high"
    assert result.chapters[0]["title"] == title
    assert result.chapters[0]["content"] == "正文。"


def test_split_chapters_only_matches_headings_at_line_starts() -> None:
    result = split_chapters("他说第1章不该被识别。\n下一段。", fallback_chars=100)

    assert result.confidence == "low"
    assert len(result.chapters) == 1


def test_split_chapters_preserves_non_whitespace_preface() -> None:
    result = split_chapters("写在前面\n\n第1章 开始\n正文。\n")

    assert result.confidence == "high"
    assert [row["title"] for row in result.chapters] == ["序章", "第1章 开始"]
    assert result.chapters[0]["content"] == "写在前面"


def test_heading_free_text_falls_back_at_paragraph_boundaries_and_budget() -> None:
    text = "甲" * 5 + "\n\n" + "乙" * 5 + "\n\n" + "丙" * 13
    result = split_chapters(text, fallback_chars=10)

    assert result.confidence == "low"
    assert [row["content"] for row in result.chapters] == [
        "甲" * 5,
        "乙" * 5,
        "丙" * 10,
        "丙" * 3,
    ]
    assert [row["title"] for row in result.chapters] == [
        "第1章",
        "第2章",
        "第3章",
        "第4章",
    ]
    assert all(str(UUID(row["id"])) == row["id"] for row in result.chapters)


@pytest.mark.parametrize(
    "chapters",
    [
        [],
        [chapter("same", 1, "第一章", "甲"), chapter("same", 2, "第二章", "乙")],
        [chapter("c1", 1, "第一章", "甲"), chapter("c2", 1, "第二章", "乙")],
        [chapter("c1", 1, "第一章", "甲"), chapter("c2", 3, "第二章", "乙")],
        [chapter("c1", 1, " ", "甲")],
        [chapter("c1", 1, "第一章", "甲", selected=False)],
    ],
    ids=["empty", "duplicate-id", "duplicate-order", "noncontiguous", "blank-title", "none-selected"],
)
def test_validate_chapters_rejects_malformed_data_without_mutation(chapters: list[dict]) -> None:
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        validate_chapters(chapters)

    assert chapters == original


def test_validate_chapters_rejects_empty_id_without_mutating_nested_data() -> None:
    chapters = [chapter("", 1, "第一章", "甲。")]
    chapters[0]["metadata"] = {"notes": ["keep"]}
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        validate_chapters(chapters)

    assert chapters == original


@pytest.mark.parametrize("selected", [1, None], ids=["integer", "none"])
def test_validate_chapters_rejects_non_bool_selected_without_mutating_nested_data(
    selected: object,
) -> None:
    chapters = [chapter("c1", 1, "第一章", "甲。")]
    chapters[0]["selected"] = selected
    chapters[0]["metadata"] = {"notes": ["keep"]}
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        validate_chapters(chapters)

    assert chapters == original


def test_validate_chapters_accepts_well_formed_data_without_mutation() -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    assert validate_chapters(chapters) is None
    assert chapters == original


def test_split_chapter_preserves_first_id_and_selection_and_creates_second_id() -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    result = split_chapter(chapters, "c1", 2)

    assert chapters == original
    assert [row["id"] for row in result[:2]] == ["c1", result[1]["id"]]
    assert str(UUID(result[1]["id"])) == result[1]["id"]
    assert result[1]["id"] not in {"c1", "c2"}
    assert [row["content"] for row in result] == ["甲。", "\n乙。", "丙。"]
    assert result[1]["title"].strip()
    assert [row["selected"] for row in result] == [True, True, True]
    assert [row["order"] for row in result] == [1, 2, 3]
    assert result[2]["id"] == "c2"


@pytest.mark.parametrize("offset", [-1, 0, 5, 6])
def test_split_chapter_rejects_offsets_outside_content(offset: int) -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        split_chapter(chapters, "c1", offset)

    assert chapters == original


def test_merge_chapter_with_previous_preserves_previous_identity_and_selection() -> None:
    chapters = [
        chapter("c1", 1, "第一章", "甲", selected=False),
        chapter("c2", 2, "第二章", "乙"),
    ]
    original = deepcopy(chapters)

    result = merge_chapters(chapters, "c2", direction="previous")

    assert chapters == original
    assert result == [chapter("c1", 1, "第一章", "甲\n\n乙")]


def test_merge_chapter_with_next_preserves_current_identity_and_title() -> None:
    result = merge_chapters(sample_chapters(), "c1", direction="next")

    assert result == [chapter("c1", 1, "第一章", "甲。\n乙。\n\n丙。")]


@pytest.mark.parametrize(
    ("chapter_id", "direction"),
    [("c1", "previous"), ("c2", "next"), ("c1", "sideways")],
)
def test_merge_chapters_rejects_invalid_boundaries_and_direction(
    chapter_id: str, direction: str
) -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        merge_chapters(chapters, chapter_id, direction=direction)

    assert chapters == original


def test_move_chapter_uses_relative_offset_and_preserves_ids() -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    result = move_chapter(chapters, "c2", offset=-1)

    assert chapters == original
    assert [row["id"] for row in result] == ["c2", "c1"]
    assert [row["order"] for row in result] == [1, 2]


@pytest.mark.parametrize("chapter_id, offset", [("c1", -1), ("c2", 1), ("c1", 2)])
def test_move_chapter_rejects_destinations_outside_list(chapter_id: str, offset: int) -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        move_chapter(chapters, chapter_id, offset=offset)

    assert chapters == original


def test_select_chapter_range_is_inclusive_and_does_not_mutate() -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    result = select_chapter_range(chapters, start=2, end=2)

    assert chapters == original
    assert [row["selected"] for row in result] == [False, True]
    assert [row["order"] for row in result] == [1, 2]


@pytest.mark.parametrize("start, end", [(0, 1), (1, 3), (2, 1)])
def test_select_chapter_range_rejects_invalid_ranges(start: int, end: int) -> None:
    chapters = sample_chapters()
    original = deepcopy(chapters)

    with pytest.raises(ValueError):
        select_chapter_range(chapters, start=start, end=end)

    assert chapters == original
