"""编辑留痕围栏三态解析(S7):成对标签 / 未闭合降级 / 旧单点哨兵回归 + 流式过滤双标记。"""
from __future__ import annotations

from loom.agents import EDIT_NOTE_SENTINEL, _edit_stream_filter
from loom.parse import (EDIT_NOTE_CLOSE, EDIT_NOTE_OPEN, EDIT_NOTE_UNCLOSED,
                        split_edit_note, strip_edit_note)

BODY = "他睁开眼。矿灯昏黄。"
NOTE = "《本章改动留痕》\n- 补了一句悬念。"


def test_paired_fence_closed():
    text = f"{BODY}\n{EDIT_NOTE_OPEN}\n{NOTE}\n{EDIT_NOTE_CLOSE}"
    body, note = split_edit_note(text)
    assert body == BODY
    assert note == NOTE
    assert EDIT_NOTE_UNCLOSED not in note   # 闭合围栏不该带降级标注


def test_paired_fence_drops_trailing_junk_after_close():
    # 围栏可校验的意义:闭标签之后的模型碎碎念不进留痕、更不进正文
    text = f"{BODY}\n{EDIT_NOTE_OPEN}\n{NOTE}\n{EDIT_NOTE_CLOSE}\n以上就是我的修改说明。"
    body, note = split_edit_note(text)
    assert body == BODY
    assert note == NOTE
    assert "修改说明" not in note


def test_unclosed_fence_degrades_with_annotation():
    text = f"{BODY}\n{EDIT_NOTE_OPEN}\n{NOTE}"
    body, note = split_edit_note(text)
    assert body == BODY                     # 正文照常切出,不因未闭合丢稿
    assert note.startswith(EDIT_NOTE_UNCLOSED)   # 留痕头部标注「围栏未闭合」
    assert NOTE in note


def test_legacy_single_sentinel_still_parses():
    # 老项目模板还在用单点哨兵:读侧永久兼容,不逼用户升级模板
    text = f"{BODY}\n{EDIT_NOTE_SENTINEL}\n{NOTE}"
    body, note = split_edit_note(text)
    assert body == BODY
    assert note == NOTE


def test_no_marker_returns_all_as_body():
    assert split_edit_note(BODY) == (BODY, "")


def test_strip_edit_note_both_markers():
    fenced = f"{BODY}\n{EDIT_NOTE_OPEN}\n{NOTE}\n{EDIT_NOTE_CLOSE}"
    legacy = f"{BODY}\n{EDIT_NOTE_SENTINEL}\n{NOTE}"
    assert strip_edit_note(fenced) == BODY
    assert strip_edit_note(legacy) == BODY
    assert strip_edit_note(BODY) == BODY    # 无标记原样返回(同一对象语义,零拷贝路径)


def _stream(text: str, size: int = 3) -> str:
    """按 size 切成 delta 流喂过滤器,返回真正外流(agent_chunk)的拼接。"""
    out: list[str] = []
    cb = _edit_stream_filter(lambda ev: out.append(ev["delta"]))
    for i in range(0, len(text), size):
        cb(text[i:i + size])
    return "".join(out)


def test_stream_filter_cuts_at_new_fence():
    text = f"{BODY}\n{EDIT_NOTE_OPEN}\n{NOTE}\n{EDIT_NOTE_CLOSE}"
    emitted = _stream(text)
    assert "LOOM:EDIT-NOTE" not in emitted   # 标记与留痕一个字都不外流
    assert "留痕" not in emitted
    assert emitted.startswith(BODY[:6])      # 干净正文照常流出(尾窗内的字节允许滞留)


def test_stream_filter_cuts_at_legacy_sentinel():
    text = f"{BODY}\n{EDIT_NOTE_SENTINEL}\n{NOTE}"
    emitted = _stream(text)
    assert "LOOM:EDIT-NOTE" not in emitted
    assert "留痕" not in emitted
    assert emitted.startswith(BODY[:6])
