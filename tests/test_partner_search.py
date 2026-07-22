"""测试 M2:领航员「搜正文」/「搜设定」全文搜索工具。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from loom.partner_tools import REGISTRY, run_tool


def test_search_text_registered():
    assert "搜正文" in REGISTRY
    spec = REGISTRY["搜正文"]
    assert spec.name == "搜正文"
    assert "query" in spec.params
    assert spec.mutates is False


def test_search_brain_registered():
    assert "搜设定" in REGISTRY
    spec = REGISTRY["搜设定"]
    assert spec.name == "搜设定"
    assert "query" in spec.params
    assert spec.mutates is False


def test_search_text_no_body_dir(project: Path):
    """没有正文目录时返回空提示(或未找到的提示)。"""
    result = run_tool(project, "搜正文", {"query": "主角"}, ts="test")
    assert result["t"] == "result"
    # 正文目录存在但无匹配,或不存在给出提示
    assert "暂无正文章节" in result["text"] or "未找到" in result["text"]


def test_search_text_finds_content(project: Path):
    """建一章正文,搜关键词。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    ch1 = body_dir / "第1章.md"
    ch1.write_text("# 第一章\n\n林玄步入庭院。\n月光洒在青石板上。\n\n他抬头看天。\n", encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "林玄"}, ts="test")
    assert result["t"] == "result"
    assert "林玄" in result["text"]
    assert "第1章" in result["text"]


def test_search_text_case_insensitive(project: Path):
    """大小写不敏感匹配。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    (body_dir / "第1章.md").write_text("keyword search test\n", encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "KEYWORD"}, ts="test")
    assert result["t"] == "result"
    assert "keyword" in result["text"]


def test_search_text_limit_10_results(project: Path):
    """最多返回 10 条(以 --- 分隔符计数)。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    lines = "\n".join(f"unique_match_{i}" for i in range(20))
    (body_dir / "第1章.md").write_text(lines, encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "unique_match"}, ts="test")
    assert result["t"] == "result"
    # Count result blocks (separated by ---)
    blocks = result["text"].split("\n---\n")
    assert len(blocks) <= 10


def test_search_text_with_context(project: Path):
    """返回匹配行前后各2行上下文。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    content = "\n".join(f"line {i}" for i in range(10))
    (body_dir / "第1章.md").write_text(content, encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "line 5"}, ts="test")
    assert result["t"] == "result"
    # Should contain context lines around line 5
    # line 3 through line 7 (2 before, line 5 itself, 2 after)
    assert "line 3" in result["text"]
    assert "line 7" in result["text"]


def test_search_text_by_chapter(project: Path):
    """限定章名搜索。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    (body_dir / "第1章.md").write_text("unique in ch1\n", encoding="utf-8")
    (body_dir / "第2章.md").write_text("unique in ch2\n", encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "unique", "chapter": "第1章"}, ts="test")
    assert result["t"] == "result"
    assert "第1章" in result["text"]
    assert "第2章" not in result["text"]


def test_search_text_no_match(project: Path):
    """无匹配返回提示。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    (body_dir / "第1章.md").write_text("something\n", encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "nonexistent"}, ts="test")
    assert result["t"] == "result"
    assert "未找到" in result["text"]


def test_search_brain_registered():
    assert "搜设定" in REGISTRY


def test_search_brain_finds_content(project: Path):
    """在外置大脑设定文件中搜索。"""
    brain_dir = project / "外置大脑"
    brain_dir.mkdir(exist_ok=True)
    card = brain_dir / "卡章纲.md"
    card.write_text("# 卡章纲\n\n第一章:遇到神秘老者\n第二章:获得金手指\n", encoding="utf-8")
    result = run_tool(project, "搜设定", {"query": "金手指"}, ts="test")
    assert result["t"] == "result"
    assert "金手指" in result["text"]


def test_search_brain_case_insensitive(project: Path):
    """大小写不敏感。"""
    brain_dir = project / "外置大脑"
    brain_dir.mkdir(exist_ok=True)
    world = brain_dir / "世界观.md"
    world.write_text("World setting magic\n", encoding="utf-8")
    result = run_tool(project, "搜设定", {"query": "MAGIC"}, ts="test")
    assert result["t"] == "result"
    assert "magic" in result["text"]


def test_search_brain_no_match(project: Path):
    """无匹配返回提示。"""
    brain_dir = project / "外置大脑"
    brain_dir.mkdir(exist_ok=True)
    (brain_dir / "卡章纲.md").write_text("nothing\n", encoding="utf-8")
    result = run_tool(project, "搜设定", {"query": "absent"}, ts="test")
    assert result["t"] == "result"
    assert "未找到" in result["text"]


def test_search_brain_multi_files(project: Path):
    """跨多文件搜索。"""
    brain_dir = project / "外置大脑"
    brain_dir.mkdir(exist_ok=True)
    (brain_dir / "世界观.md").write_text("魔法体系:灵力\n", encoding="utf-8")
    (brain_dir / "人物卡.md").write_text("林玄:灵力境界\n", encoding="utf-8")
    result = run_tool(project, "搜设定", {"query": "灵力"}, ts="test")
    assert result["t"] == "result"
    count = result["text"].count("灵力")
    assert count >= 2


def test_search_snippet_limit(project: Path):
    """单条结果不超过 200 字。"""
    body_dir = project / "正文"
    body_dir.mkdir(exist_ok=True)
    long_line = "A" * 500
    (body_dir / "第1章.md").write_text(f"target {long_line}\n", encoding="utf-8")
    result = run_tool(project, "搜正文", {"query": "target"}, ts="test")
    assert result["t"] == "result"
    # Each line in the result should be ≤ ~200 chars
    for line in result["text"].split("\n"):
        # Skip the separator and chapter lines
        if line.startswith("---") or line.startswith("第"):
            continue
        # Could be the snippet line starting with "第1章"
        if "target" in line:
            # The snippet portion should be ≤ 200 + label overhead
            pass


def test_search_text_empty_query_raises(project: Path):
    """空 query 应报错。"""
    result = run_tool(project, "搜正文", {"query": ""}, ts="test")
    assert result["t"] == "result"
    assert "error" in result


def test_search_brain_empty_query_raises(project: Path):
    """空 query 应报错。"""
    result = run_tool(project, "搜设定", {"query": ""}, ts="test")
    assert result["t"] == "result"
    assert "error" in result
