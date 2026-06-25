"""章节标题/正文体切分。"""
from __future__ import annotations

from loom.chaptertext import compose, parse_title, split_title, strip_title


def test_split_with_title():
    title, body = split_title("# 矿洞惊变\n\n他屏住呼吸。\n下一句。")
    assert title == "矿洞惊变"
    assert body == "他屏住呼吸。\n下一句。"


def test_old_chapter_without_title():
    # 老章无 H1:标题为 None、正文体=原文,绝不凭空造标题
    text = "他屏住呼吸。\n下一句。"
    assert split_title(text) == (None, text)
    assert parse_title(text) is None
    assert strip_title(text) == text


def test_compose_roundtrip():
    body = "他屏住呼吸。\n下一句。"
    composed = compose("矿洞惊变", body)
    assert composed == "# 矿洞惊变\n\n他屏住呼吸。\n下一句。"
    assert strip_title(composed) == body
    assert parse_title(composed) == "矿洞惊变"


def test_compose_empty_title_is_just_body():
    assert compose("", "正文") == "正文"
    assert compose(None, "正文") == "正文"


def test_compose_tolerates_hash_in_title():
    assert compose("# 矿洞惊变", "正文") == "# 矿洞惊变\n\n正文"


def test_title_only_change_has_same_body():
    a = "# 旧标题\n\n一样的正文。"
    b = "# 新标题\n\n一样的正文。"
    assert strip_title(a) == strip_title(b)   # 改标题不动正文体
