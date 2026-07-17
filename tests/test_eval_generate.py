"""Generation suite:evalapi 生成接缝 + 固定输入生成链路。零真实模型。"""
import json
from pathlib import Path

import pytest

from loom import evalapi
from loom.evalapi import load_config
from evals.generate import load_gen_case, prepare_project, generate_one
from loom.parse import EDIT_NOTE_CLOSE, EDIT_NOTE_OPEN
from conftest import ScriptedBackend

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


# 7 调脚本(细纲 overlay 旁路大纲师):设定/写手/编辑/质检"通过"/润色/去AI味"通过"/标题。
# 产出文本 ≥40 字过终稿最短闸(200×12%=24,地板40);避开翻转句与禁词,含"矿灯"喂 must_include。
_SETTER = "本章设定锚点:主角沈砚在废弃矿场;境界凡境;金手指为重生记忆。"
_DRAFT = "寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀。"
_EDITED = (_DRAFT + "\n" + EDIT_NOTE_OPEN + "\n《本章改动留痕》\n- 钩子更硬。\n" + EDIT_NOTE_CLOSE)
_POLISHED = "寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀,也记得递刀的人。"
_GEN_RUN_7 = [_SETTER, _DRAFT, _EDITED, "通过", _POLISHED, "通过", "矿灯"]


def test_generate_one_end_to_end_offline(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    be = ScriptedBackend(list(_GEN_RUN_7))
    run_dir = generate_one(case_dir, backend=be,
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    assert be.replies == []                                        # 恰好 7 调(调用数契约)
    assert len(be.calls) == 7                                      # 耗尽不证「恰7调」,calls 钉死精确值
    text = (run_dir / "chapter.md").read_text(encoding="utf-8")
    assert "矿灯" in text and EDIT_NOTE_OPEN not in text           # 终稿落盘且无哨兵残留
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["case_id"] == "gen_test"
    assert any(g["name"] == "关键要素" for g in report["graders"])  # 复用既有 grader 真跑了
    assert not (case_dir / "chapter.md").exists()                  # 金标数据集目录零写入


def test_generate_one_runs_never_collide(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    kw = dict(runs_dir=tmp_path / "runs")
    r1 = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                      workdir=tmp_path / "w1", **kw)
    r2 = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                      workdir=tmp_path / "w2", **kw)
    assert r1 != r2 and r1.exists() and r2.exists()                # 两次运行两个目录,零覆盖


def test_manifest_traceability_fields(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["run_id"] == run_dir.name
    assert m["git_commit"] and m["git_commit"] != "nogit"          # 本仓是 git 仓,必有 sha
    assert m["backend_mode"] == "injected(测试)"
    assert m["backend_class"] == "ScriptedBackend"                 # 实际后端类名,不撒谎
    assert m["n_calls"] == 7 and len(m["calls"]) == 7              # 7 调契约进档
    assert all(c["elapsed_s"] >= 0 and c["output_chars"] > 0 for c in m["calls"][:3])
    assert m["tokens"] is None and m["cost"] is None               # 不造数
    assert m["retries"] == 0
    assert "usage" in m["notes"] or "代理指标" in m["notes"]        # 置空原因写明


def test_manifest_hashes_stable_and_sensitive(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    kw = dict(runs_dir=tmp_path / "runs")
    m1 = json.loads((generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                                  workdir=tmp_path / "w1", **kw) / "manifest.json").read_text(encoding="utf-8"))
    m2 = json.loads((generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                                  workdir=tmp_path / "w2", **kw) / "manifest.json").read_text(encoding="utf-8"))
    assert m1["prompt_hash"] == m2["prompt_hash"]                  # 同输入同 prompt → hash 稳定
    assert m1["dataset_hash"] == m2["dataset_hash"]
    # 数据集变一个字 → dataset_hash 必变(细纲走大纲师旁路直接落盘,需过 STEP 最短闸 min_chars=8,
    # 故内容比"改了的细纲"更长,只为不触发无关的过短校验,不改变本测试意图)
    (case_dir / "overlay" / "正文" / ".细纲" / "第1章.md").write_text(
        "改动后的细纲:分镜一如常。\n", encoding="utf-8")
    m3 = json.loads((generate_one(case_dir, backend=ScriptedBackend(
        [_SETTER, _DRAFT, _EDITED, "通过", _POLISHED, "通过", "矿灯"]),
        workdir=tmp_path / "w3", **kw) / "manifest.json").read_text(encoding="utf-8"))
    assert m3["dataset_hash"] != m1["dataset_hash"]
