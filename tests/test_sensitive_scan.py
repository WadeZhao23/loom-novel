"""违禁词粗筛 scan:单字词不报(「颤抖」踩「抖」类子串误伤)+ 命中带上下文片段。仍只提示不阻断。"""
from __future__ import annotations

from pathlib import Path

from loom import sensitive
from loom.sensitive import scan


def test_scan_hits_carry_contexts(tmp_path: Path):
    # 无 违禁词.md → 用内置基线(含「抖音」);命中要带前后文片段,给人眼判真伪
    hits = scan("他掏出手机刷抖音,越刷越困,索性关机睡觉。", tmp_path)
    h = next(h for h in hits if h["word"] == "抖音")
    assert h["count"] == 1
    assert any("刷抖音" in c for c in h["contexts"])


def test_scan_contexts_capped(tmp_path: Path):
    hits = scan("赌博。" * 10, tmp_path)
    h = next(h for h in hits if h["word"] == "赌博")
    assert h["count"] == 10
    assert len(h["contexts"]) == 3     # 片段只带前几处,不刷屏


def test_scan_ignores_single_char_words(tmp_path: Path, monkeypatch):
    # 防御:词表就算混进单字(手编基线/未来改动),也不报——子串误伤太多
    monkeypatch.setattr(sensitive, "load_words",
                        lambda root: {"抖": "试验", "自杀": "暴力血腥 · 自残"})
    hits = scan("他吓得直颤抖,却从没想过自杀。", tmp_path)
    assert [h["word"] for h in hits] == ["自杀"]
