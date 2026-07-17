"""Generation suite:evalapi 生成接缝 + 固定输入生成链路。零真实模型。"""
import json
from pathlib import Path

import pytest

from loom import evalapi
from loom.evalapi import load_config
from evals.generate import load_gen_case, prepare_project

_GEN_SEAM = ("run_pipeline", "scaffold_init", "load_config", "save_config",
             "Config", "get_backend", "outline_path")


def test_evalapi_generation_seam_exports():
    # Phase 1 生成接缝:七个再导出必须存在且进 __all__(evals 只准走门面)
    for name in _GEN_SEAM:
        assert hasattr(evalapi, name), f"evalapi 缺生成接缝导出:{name}"
        assert name in evalapi.__all__, f"{name} 未进 evalapi.__all__"


def _write_gen_case(tmp_path, *, with_outline=True):
    d = tmp_path / "gen_case_src"
    (d / "overlay" / "正文" / ".细纲").mkdir(parents=True)
    (d / "case.json").write_text(json.dumps({
        "id": "gen_test", "title": "生成测试例", "chapter_n": 1, "chapter_chars": 200,
        "expect": {"must_include": ["矿灯"], "must_not_include": ["二中"]},
    }, ensure_ascii=False), encoding="utf-8")
    if with_outline:
        (d / "overlay" / "正文" / ".细纲" / "第1章.md").write_text(
            "固定细纲:分镜一醒来验伤;分镜二矿灯下遇人;分镜三末场倒计时钩。\n", encoding="utf-8")
    return d


def test_load_gen_case_validates_required_fields(tmp_path):
    d = tmp_path / "bad"; d.mkdir()
    (d / "case.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="chapter_n"):
        load_gen_case(d)


def test_prepare_project_applies_overlay_and_config(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    case = load_gen_case(case_dir)
    work = tmp_path / "work"; work.mkdir()
    project = prepare_project(case_dir, case, work)
    assert (project / "agents" / "写手.md").is_file()               # scaffold 骨架就绪
    outline = (project / "正文" / ".细纲" / "第1章.md").read_text(encoding="utf-8")
    assert outline.startswith("固定细纲")                            # overlay 盖上了
    cfg = load_config(project)
    assert cfg.chapter_chars == 200                                  # case 的字数进了 config
    assert cfg.continuity_scan is False                              # 评测口径固定关(省一次调用)
