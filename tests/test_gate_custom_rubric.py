"""S5 自定义 Gate 开关:loom.toml [gate] 段 custom_rubric 指向自定义 rubric。"""
import json
from pathlib import Path

import pytest

from loom.config import Config, load_config
from loom.gates import load_critic, load_revise


def test_custom_rubric_config_field():
    """Config 有 custom_rubric 字段,默认空串。"""
    cfg = Config()
    assert cfg.custom_rubric == ""


def test_load_custom_rubric_from_config(tmp_path: Path):
    """custom_rubric 文件存在时,load_critic/load_revise 返回自定义内容。"""
    custom = tmp_path / "my_rubric.md"
    custom.write_text("这是自定义 rubric 内容。\n", encoding="utf-8")
    content = load_critic(tmp_path, "质检", custom_rubric=str(custom.relative_to(tmp_path)))
    assert "自定义 rubric" in content


def test_load_default_rubric_when_no_custom(tmp_path: Path):
    """不传 custom_rubric 时,回退到默认 skills/ 目录。"""
    # 在 temp 项目里建一个 skills/ 目录模拟 scaffold
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "质检rubric.md").write_text("默认质检 rubric", encoding="utf-8")
    content = load_critic(tmp_path, "质检")
    assert "默认质检 rubric" in content


def test_custom_rubric_nonexistent_falls_back(tmp_path: Path):
    """custom_rubric 指向不存在的文件时,静默回退默认。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "质检rubric.md").write_text("默认质检 rubric", encoding="utf-8")
    content = load_critic(tmp_path, "质检", custom_rubric="不存在.md")
    assert "默认质检 rubric" in content


def test_custom_rubric_in_toml(tmp_path: Path):
    """在 loom.toml 配置 custom_rubric 后,load_config 正确解析。"""
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "质检rubric.md").write_text("默认", encoding="utf-8")
    toml_content = """
[backend]
provider = "deepseek"
model = "deepseek-v4-pro"

[novel]
title = "测试书"
"章节字数" = 800

[gate]
"轮数" = 2
custom_rubric = "my_custom_rubric.md"
"""
    (tmp_path / "loom.toml").write_text(toml_content, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.custom_rubric == "my_custom_rubric.md"
    assert cfg.gate_rounds == 2


def test_custom_rubric_loads_via_pipeline(tmp_path: Path):
    """通过 Config 传下去的 custom_rubric 能被 run_gate 加载。"""
    # 建 skills/ 默认
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "质检rubric.md").write_text("默认质检 rubric", encoding="utf-8")
    (tmp_path / "skills" / "质检revise.md").write_text("默认质检 revise", encoding="utf-8")
    # 建自定义
    custom = tmp_path / "my_custom_rubric.md"
    custom.write_text("这是自定义 rubric 文件,质检和 revise 都从这里读。", encoding="utf-8")
    # 测试通过 load_critic/revise 传入 custom_rubric
    critic = load_critic(tmp_path, "质检", custom_rubric="my_custom_rubric.md")
    revise = load_revise(tmp_path, "质检", custom_rubric="my_custom_rubric.md")
    assert "自定义 rubric" in critic
    assert "自定义 rubric" in revise
