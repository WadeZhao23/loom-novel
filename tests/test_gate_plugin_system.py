"""M1 Gate 插件系统:loom.toml [gate.custom] 注册自定义审查关卡。"""
from __future__ import annotations

from pathlib import Path

import pytest

from loom.config import Config, load_config
from loom.gates import _load_custom_rubric, run_custom_gates
from loom.parse import _PASS_PHRASES

from conftest import FakeBackend, const


def test_custom_gates_config_field():
    """Config 有 custom_gates 字段,默认空 dict。"""
    cfg = Config()
    assert cfg.custom_gates == {}


def test_custom_gates_in_toml(tmp_path: Path):
    """[gate.custom] 段正确解析进 Config.custom_gates。"""
    toml_content = (
        '[backend]\n'
        'provider = "deepseek"\n'
        'model = "deepseek-v4-pro"\n'
        '\n'
        '[novel]\n'
        'title = "测试书"\n'
        '"章节字数" = 800\n'
        '\n'
        '[gate]\n'
        '"轮数" = 1\n'
        '\n'
        '[gate.custom]\n'
        '"情绪检查" = "skills/情绪检查.md"\n'
        '"节奏检查" = "skills/节奏检查.md"\n'
    )
    (tmp_path / "loom.toml").write_text(toml_content, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.custom_gates == {"情绪检查": "skills/情绪检查.md", "节奏检查": "skills/节奏检查.md"}


def test_custom_gates_absent_in_toml(tmp_path: Path):
    """[gate.custom] 不存在时,custom_gates 默认为空 dict(向后兼容)。"""
    toml_content = (
        '[backend]\n'
        'provider = "deepseek"\n'
        'model = "deepseek-v4-pro"\n'
        '\n'
        '[novel]\n'
        'title = "测试书"\n'
        '"章节字数" = 800\n'
        '\n'
        '[gate]\n'
        '"轮数" = 1\n'
    )
    (tmp_path / "loom.toml").write_text(toml_content, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.custom_gates == {}


def test_custom_gates_empty_in_toml(tmp_path: Path):
    """[gate.custom] 段为空时,custom_gates 为空 dict。"""
    toml_content = (
        '[backend]\n'
        'provider = "deepseek"\n'
        'model = "deepseek-v4-pro"\n'
        '\n'
        '[novel]\n'
        'title = "测试书"\n'
        '"章节字数" = 800\n'
        '\n'
        '[gate]\n'
        '"轮数" = 1\n'
        '\n'
        '[gate.custom]\n'
    )
    (tmp_path / "loom.toml").write_text(toml_content, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.custom_gates == {}


def test_load_custom_rubric_relative_path(tmp_path: Path):
    """相对路径的 rubric 文件(相对书根)可加载。"""
    rubric_file = tmp_path / "skills" / "情绪检查.md"
    rubric_file.parent.mkdir(parents=True, exist_ok=True)
    rubric_file.write_text("检查文中情绪是否合理。", encoding="utf-8")
    content = _load_custom_rubric(tmp_path, "skills/情绪检查.md")
    assert "情绪" in content


def test_load_custom_rubric_absolute_path(tmp_path: Path):
    """绝对路径的 rubric 文件可加载。"""
    rubric_file = tmp_path / "节奏检查.md"
    rubric_file.write_text("检查文中节奏是否流畅。", encoding="utf-8")
    content = _load_custom_rubric(tmp_path, str(rubric_file))
    assert "节奏" in content


def test_load_custom_rubric_missing_file(tmp_path: Path):
    """不存在的 rubric 文件返回空串。"""
    content = _load_custom_rubric(tmp_path, "不存在的文件.md")
    assert content == ""


def test_run_custom_gate_single(tmp_path: Path):
    """注册一条自定义 Gate 并执行,产出 Issue。"""
    rubric_file = tmp_path / "skills" / "情绪检查.md"
    rubric_file.parent.mkdir(parents=True, exist_ok=True)
    rubric_file.write_text(
        "你是**独立审读**,检查文中是否有情绪描写不合理之处。\n"
        '输出格式:有则每条一行 `- 类别 | 问题 | 证据:"原文"`;无则只回「通过」。',
        encoding="utf-8",
    )

    backend = FakeBackend(lambda s, u: '- 情绪突兀 | 角色情绪转变太快 | 证据:"他突然笑了"')
    dummy = tmp_path / "skills" / "dummy.md"
    dummy.parent.mkdir(parents=True, exist_ok=True)
    dummy.write_text("dummy", encoding="utf-8")

    text, remaining = run_custom_gates(
        backend,
        draft="正文内容:他突然笑了。刚才还在哭。",
        custom_gates={"情绪检查": "skills/情绪检查.md"},
        project_root=tmp_path,
    )

    assert len(remaining) == 1
    assert remaining[0].kind == "情绪突兀"
    assert "情绪转变" in remaining[0].desc
    assert "他突然笑了" in remaining[0].evidence


def test_run_custom_gates_multiple(tmp_path: Path):
    """注册多条自定义 Gate 并执行。"""
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "情绪检查.md").write_text(
        '检查情绪。输出格式:每条一行 `- 类别 | 问题 | 证据:"原文"`;无则回「通过」。',
        encoding="utf-8",
    )
    (tmp_path / "skills" / "节奏检查.md").write_text(
        '检查节奏。输出格式:每条一行 `- 类别 | 问题 | 证据:"原文"`;无则回「通过」。',
        encoding="utf-8",
    )

    replies = [
        '- 情绪突兀 | 角色情绪转变太快 | 证据:"他突然笑了"',
        '- 节奏拖沓 | 描写过于冗长 | 证据:"他慢慢地一步一步地走"',
    ]
    backend = FakeBackend(lambda s, u: replies.pop(0) if replies else "通过")

    text, remaining = run_custom_gates(
        backend,
        draft="正文内容。",
        custom_gates={"情绪检查": "skills/情绪检查.md", "节奏检查": "skills/节奏检查.md"},
        project_root=tmp_path,
    )

    assert len(remaining) == 2
    kinds = {r.kind for r in remaining}
    assert "情绪突兀" in kinds
    assert "节奏拖沓" in kinds


def test_run_custom_gates_none_configured(tmp_path: Path):
    """custom_gates 为空时静默跳过。"""
    text, remaining = run_custom_gates(
        FakeBackend(const("通过")),
        draft="正文内容。",
        custom_gates={},
        project_root=tmp_path,
    )
    assert text == "正文内容。"
    assert remaining == []


def test_run_custom_gate_nonexistent_rubric(tmp_path: Path):
    """指向不存在的 rubric 文件时优雅降级(跳过,不阻断)。"""
    text, remaining = run_custom_gates(
        FakeBackend(const("通过")),
        draft="正文内容。",
        custom_gates={"不存在的Gate": "不存在的文件.md"},
        project_root=tmp_path,
    )
    assert text == "正文内容。"
    assert remaining == []


def test_custom_gates_pipeline_integration(tmp_path: Path):
    """完整流程:Config 带 custom_gates,调用 run_custom_gates 正常执行。"""
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "情绪检查.md").write_text(
        '检查情绪。输出格式:每条一行 `- 类别 | 问题 | 证据:"原文"`;无则回「通过」。',
        encoding="utf-8",
    )

    cfg = Config(custom_gates={"情绪检查": "skills/情绪检查.md"})
    backend = FakeBackend(lambda s, u: '- 情绪突兀 | 角色情绪转变太快 | 证据:"他突然笑了"')

    text, remaining = run_custom_gates(
        backend,
        draft="正文:他突然笑了。刚才还在哭。",
        custom_gates=cfg.custom_gates,
        project_root=tmp_path,
    )

    assert len(remaining) == 1
    assert remaining[0].kind == "情绪突兀"
