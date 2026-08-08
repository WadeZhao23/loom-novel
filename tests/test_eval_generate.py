"""Generation suite:evalapi 生成接缝 + 固定输入生成链路。零真实模型。"""
import json
import shutil
from pathlib import Path

import pytest

from loom import evalapi
from loom.evalapi import load_config
from evals.generate import load_gen_case, prepare_project, generate_one, main
from loom.parse import EDIT_NOTE_CLOSE, EDIT_NOTE_OPEN
from conftest import ScriptedBackend

_GEN_SEAM = ("run_pipeline", "scaffold_init", "load_config", "save_config",
             "Config", "get_backend", "outline_path")


def test_evalapi_generation_seam_exports():
    # Phase 1 生成接缝:七个再导出必须存在且进 __all__(evals 只准走门面)
    for name in _GEN_SEAM:
        assert hasattr(evalapi, name), f"evalapi 缺生成接缝导出:{name}"
        assert name in evalapi.__all__, f"{name} 未进 evalapi.__all__"


_STEP_SEAM = ("PIPELINE", "load_ledger", "ledger_path", "scene_range",
              "parse_scene_budgets", "split_edit_note", "STEP_SHORT_BUDGETS")


def test_evalapi_step_attribution_seam_exports():
    """棒级归因接缝:evals 复用产品判据必须走门面,不得在 evals 里重写一套(会漂)。"""
    for name in _STEP_SEAM:
        assert hasattr(evalapi, name), f"evalapi 缺棒级归因接缝导出:{name}"
        assert name in evalapi.__all__, f"{name} 未进 evalapi.__all__"


def test_scene_range_matches_scene_budget_string():
    """数值形态与字符串形态必须同源——否则 evals 与 prompt 会各说各话。"""
    from loom.agents import _scene_budget
    for target, expect in ((800, (2, 3)), (2000, (3, 4)), (5000, (4, 6))):
        lo, hi = evalapi.scene_range(target)
        assert (lo, hi) == expect
        assert _scene_budget(target) == f"拆 {lo}-{hi} 场"


def test_pipeline_seam_is_the_five_steps():
    assert evalapi.PIPELINE == ["设定师", "大纲师", "写手", "编辑", "润色师"]


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


def test_gen_case_can_opt_into_continuity_scan(tmp_path):
    """除虫此前被硬编码关死,评测里从没跑过。改成 case 可声明,缺省仍关。"""
    from evals.generate import load_gen_case, prepare_project
    d = tmp_path / "gc_scan"
    (d).mkdir(parents=True)
    (d / "case.json").write_text(json.dumps({
        "id": "scan_on", "chapter_n": 1, "chapter_chars": 200,
        "continuity_scan": True,
    }, ensure_ascii=False), encoding="utf-8")
    case = load_gen_case(d)
    work = tmp_path / "w"; work.mkdir()
    cfg = load_config(prepare_project(d, case, work))
    assert cfg.continuity_scan is True


def test_gen_case_continuity_scan_defaults_off(tmp_path):
    from evals.generate import load_gen_case, prepare_project
    case_dir = _write_gen_case(tmp_path)
    case = load_gen_case(case_dir)
    work = tmp_path / "w2"; work.mkdir()
    cfg = load_config(prepare_project(case_dir, case, work))
    assert cfg.continuity_scan is False, "缺省必须仍关——省一次调用,与既有 golden 同口径"


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


# 8 调脚本(无 overlay 细纲 → 大纲师真跑):设定/大纲/写手/编辑/质检"通过"/润色/去AI味"通过"/标题。
_OUTLINE = ("场景一 · 当夜二更 · 废矿深处 · 沈砚独自一人 · 醒来验伤、确认重生 · 约80字\n"
            "场景二 · 同夜稍后 · 矿道岔口 · 沈砚与巡矿人 · 矿灯下照面、藏起异状 · 约70字\n"
            "场景三 · 拂晓前 · 矿口 · 沈砚 · 听见追兵、倒计时钩 · 约50字\n"
            "爆发点落在场景三。章首接上一章矿口火把。章末钩类型:〔危机迫近〕。")
_GEN_RUN_8 = [_SETTER, _OUTLINE, _DRAFT, _EDITED, "通过", _POLISHED, "通过", "矿灯"]


def test_generate_one_collects_five_step_outputs(tmp_path):
    """五棒产物必须落进 run_dir/steps/;被 WYSIWYG 旁路的大纲师记 skipped(不是 0 分)。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path)          # with_outline=True → 大纲师被旁路
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    steps_dir = run_dir / "steps"
    assert steps_dir.is_dir()
    assert (steps_dir / "设定师.md").read_text(encoding="utf-8") == _SETTER
    assert (steps_dir / "写手.md").read_text(encoding="utf-8") == _DRAFT
    assert (steps_dir / "润色师.md").is_file()
    # 大纲师被 overlay 细纲旁路 → 没有产物文件,且 steps.json 明确记 skipped
    assert not (steps_dir / "大纲师.md").exists()
    meta = json.loads((run_dir / "steps.json").read_text(encoding="utf-8"))
    assert meta["大纲师"] == "skipped", "旁路≠失败,必须记 skipped 不记 0 分"
    assert meta["设定师"] == "collected"


def test_collect_steps_without_outline_overlay_collects_outliner(tmp_path):
    """无 overlay 细纲时大纲师真跑,产物必须被收到。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path, with_outline=False)
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_8)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    assert (run_dir / "steps" / "大纲师.md").read_text(encoding="utf-8") == _OUTLINE
    meta = json.loads((run_dir / "steps.json").read_text(encoding="utf-8"))
    assert meta["大纲师"] == "collected"


def test_step_report_written_and_names_weakest_step(tmp_path):
    """闭环的交付物:step_report.json 要能直接回答「该改哪一棒」。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path, with_outline=False)
    # 写手交的初稿里没有 must_include 的「矿灯」→ 写手·必含要素 应当失败并被点名。
    # 设定师锚点这里刻意带上「矿灯」(不用共享的 _SETTER——它本来就没提矿灯,若沿用会让
    # 设定师·硬设定专名 与 写手·必含要素 同时在 weight=0.30 撞车,点名就不再单指写手了)。
    # 篇幅刻意 ≥40 字(chapter_profile(200)=max(40, 200*0.12)=40)——这份文本被脚本复用为
    # 终稿(润色师那一步同样返回它),太短会先撞上终稿非空硬闸,根本走不到 step_report。
    setter_with_lamp = "本章设定锚点:主角沈砚在废弃矿场,身旁一盏矿灯;境界凡境;金手指为重生记忆。"
    draft_no_lamp = ("寅时三刻，铜锣未响。\n\n沈砚睁开眼，四肢发麻，伤口隐隐作痛，"
                     "他撑着墙壁缓缓站起。\n\n他记得三年后的那一刀，也记得那人转身时留下的背影。")
    edited = draft_no_lamp + "\n" + EDIT_NOTE_OPEN + "\n- 钩子更硬。\n" + EDIT_NOTE_CLOSE
    be = ScriptedBackend([setter_with_lamp, _OUTLINE, draft_no_lamp, edited,
                          "通过", draft_no_lamp, "通过", "标题"])
    run_dir = generate_one(case_dir, backend=be,
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    rep = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
    assert set(rep["steps"]) == {"设定师", "大纲师", "写手", "编辑", "润色师"}
    names = [g["name"] for g in rep["steps"]["写手"]]
    assert "写手·必含要素" in names
    failed = [g for g in rep["steps"]["写手"] if g["name"] == "写手·必含要素"][0]
    assert failed["passed"] is False
    assert rep["weakest"] in ("写手", "大纲师"), f"该点名丢要素的那一棒,实际 {rep['weakest']}"


def test_step_report_marks_bypassed_outliner_skipped_not_failed(tmp_path):
    """大纲师被 WYSIWYG 旁路时不得被点名成最弱棒——旁路不是失败。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path)                 # with_outline=True → 旁路
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    rep = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
    assert all(g["gating"] is False for g in rep["steps"]["大纲师"])
    assert rep["weakest"] != "大纲师"


def test_gen_02_exists_and_has_no_outline_overlay():
    """gen_02 存在的唯一理由就是让大纲师真跑——它一旦带了 overlay 细纲就白设了。"""
    from evals.generate import GEN_CASES_DIR, load_gen_case
    d = GEN_CASES_DIR / "gen_02_mine_escape"
    assert (d / "case.json").is_file(), "缺 gen_02:大纲师这一棒没有任何 case 覆盖"
    case = load_gen_case(d)
    assert case["id"] == "gen_02_mine_escape"
    assert not (d / "overlay" / "正文" / ".细纲").exists(), \
        "gen_02 不得带 overlay 细纲,否则大纲师又被 WYSIWYG 旁路"
    assert case["expect"]["must_include"], "得有必含要素,否则大纲师的必含体检没内容可查"


def test_cli_unknown_case_is_infra_2(tmp_path):
    (tmp_path / "gc").mkdir()
    assert main(["--case", "不存在", "--cases-dir", str(tmp_path / "gc"),
                 "--runs-dir", str(tmp_path / "runs")]) == 2


def test_cli_empty_cases_dir_is_infra_2(tmp_path):
    (tmp_path / "gc").mkdir()
    assert main(["--cases-dir", str(tmp_path / "gc"), "--runs-dir", str(tmp_path / "runs")]) == 2


def test_cli_demo_mode_end_to_end(tmp_path, monkeypatch):
    # demo 模式离线冒烟:证明 CLI→generate_one→DemoBackend 链路通(不证明生成质量)。
    # monkeypatch 先设 LOOM_DEMO,保证 teardown 复原、不串染其它测试。
    monkeypatch.setenv("LOOM_DEMO", "1")
    src = _write_gen_case(tmp_path)
    gc = tmp_path / "gc"; gc.mkdir()
    shutil.copytree(src, gc / "gen_test")
    code = main(["--cases-dir", str(gc), "--runs-dir", str(tmp_path / "runs")])
    assert code == 0
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "manifest.json").is_file() and (runs[0] / "report.json").is_file()
    m = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert m["backend_class"] == "DemoBackend"        # 罐头后端如实入档


def test_run_batch_produces_summary_with_distributions(tmp_path):
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    batch = run_batch(case_dir, repeat=3, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: ScriptedBackend(list(_GEN_RUN_7)),
                      workdir_root=tmp_path / "work")
    assert (batch / "summary.json").is_file() and (batch / "summary.md").is_file()
    assert len(list((batch / "runs").iterdir())) == 3
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_total"] == 3 and summ["n_valid"] == 3
    assert summ["case_id"] == "gen_test"
    w = summ["steps"]["写手"]["写手·必含要素"]
    assert w["median"] is not None and w["n_valid"] == 3


def test_run_batch_survives_a_crashed_run_and_reports_honestly(tmp_path):
    """第 2 次崩了不能丢掉第 1、3 次;而且必须照实写 3 次里 2 次有效。"""
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    seq = iter([ScriptedBackend(list(_GEN_RUN_7)),
                ScriptedBackend([]),                    # 空脚本 → 空响应 → 写盘闸抛错
                ScriptedBackend(list(_GEN_RUN_7))])
    batch = run_batch(case_dir, repeat=3, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: next(seq),
                      workdir_root=tmp_path / "work")
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_total"] == 3 and summ["n_valid"] == 2
    md = (batch / "summary.md").read_text(encoding="utf-8")
    assert "3 次里 2 次有效" in md, "必须照实披露掉数,不得拿 2 次冒充 3 次"
    # 光看 summary 数字不够——batch/runs/ 目录本身也得如实反映:
    # 两次成功跑的产物目录(带 step_report.json)都得在,第 2 次(i=1)崩的那次
    # 要留 infra_1.txt 标记。(不额外断言 batch/runs 下条目总数——generate_one
    # 在跑 pipeline 前就先 mkdir 了 run_dir,下游崩溃会留一个空壳目录,那是
    # generate_one 自身早已有的行为,不属于本次三个 finding 的范围。)
    entries = list((batch / "runs").iterdir())
    completed = [p for p in entries if p.is_dir() and (p / "step_report.json").is_file()]
    assert len(completed) == 2, "两次成功跑的 run 目录(带完整产物)都必须留着"
    assert (batch / "runs" / "infra_1.txt").is_file(), "崩的那次(i=1)要留 infra 标记"


def test_run_batch_batch_id_collision_gets_distinct_paths(tmp_path, monkeypatch):
    """同一秒内两次 run_batch 撞 batch_id 不得硬崩——比照 generate_one 的 run_id 撞车重试。

    time.strftime 钉死同一秒,逼真撞车(而非"日常大概率不会同一秒"这种脆弱假设)。
    """
    import evals.generate as gen_mod
    monkeypatch.setattr(gen_mod.time, "strftime", lambda *a: "20260101-000000")
    case_dir = _write_gen_case(tmp_path)
    b1 = gen_mod.run_batch(case_dir, repeat=1, runs_dir=tmp_path / "runs",
                           backend_factory=lambda: ScriptedBackend(list(_GEN_RUN_7)),
                           workdir_root=tmp_path / "work1")
    b2 = gen_mod.run_batch(case_dir, repeat=1, runs_dir=tmp_path / "runs",
                           backend_factory=lambda: ScriptedBackend(list(_GEN_RUN_7)),
                           workdir_root=tmp_path / "work2")
    assert b1 != b2, "撞车的两个批次必须落到不同目录,而不是互相覆盖"
    assert b1.exists() and b2.exists()
    assert (b1 / "summary.json").is_file() and (b2 / "summary.json").is_file()


def test_run_batch_workdir_mkdir_failure_is_infra_not_fatal(tmp_path):
    """第 2 次(i=1)的 workdir 建目录失败,必须记 infra 继续跑完,不能让整批带着已收的成果崩出去。"""
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    workdir_root = tmp_path / "work"
    workdir_root.mkdir()
    # 预先在 w1 位置放一个文件(不是目录)——generate_one 内部 i=1 时 wd.mkdir() 必炸。
    (workdir_root / "w1").write_text("占位文件,顶替本该是目录的位置", encoding="utf-8")
    batch = run_batch(case_dir, repeat=3, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: ScriptedBackend(list(_GEN_RUN_7)),
                      workdir_root=workdir_root)
    assert (batch / "summary.json").is_file(), "workdir 建目录失败也必须走到 summary 落盘"
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_total"] == 3 and summ["n_valid"] == 2, "1 次因 workdir 而 infra,其余 2 次照收"
    assert (batch / "runs" / "infra_1.txt").is_file(), "workdir mkdir 失败要老实记成该次的 infra"


def test_run_batch_all_runs_crashed_is_infra(tmp_path):
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    batch = run_batch(case_dir, repeat=2, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: ScriptedBackend([]),
                      workdir_root=tmp_path / "work")
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_valid"] == 0 and summ["steps"] == {}


def _fake_batch(tmp_path, name, *, median, lo, hi, n_valid=3):
    b = tmp_path / name
    b.mkdir(parents=True)
    (b / "summary.json").write_text(json.dumps({
        "case_id": "gen_test", "batch_id": name, "n_total": 3, "n_valid": n_valid,
        "weakest": None,
        "steps": {"写手": {"写手·必含要素": {"median": median, "lo": lo, "hi": hi,
                                          "n_valid": n_valid, "n_total": 3}}},
    }, ensure_ascii=False), encoding="utf-8")
    return b


def test_compare_declares_improvement_only_when_ranges_separate(tmp_path):
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.2, lo=0.1, hi=0.3)
    b = _fake_batch(tmp_path, "b", median=0.8, lo=0.7, hi=0.9)
    res = compare_batches(a, b)
    item = res["items"][0]
    assert item["verdict"] == "改进" and item["delta"] == pytest.approx(0.6)
    assert res["n_improved"] == 1 and res["n_regressed"] == 0


def test_compare_refuses_to_call_it_improvement_when_ranges_overlap(tmp_path):
    """中位数涨了但区间重叠——必须判「分不出」,这是本工具最重要的一条纪律。"""
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.50, lo=0.30, hi=0.70)
    b = _fake_batch(tmp_path, "b", median=0.62, lo=0.40, hi=0.85)
    item = compare_batches(a, b)["items"][0]
    assert item["verdict"] == "分不出(区间重叠)"
    assert compare_batches(a, b)["n_improved"] == 0


def test_compare_flags_regression_when_ranges_separate_downward(tmp_path):
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.9, lo=0.85, hi=0.95)
    b = _fake_batch(tmp_path, "b", median=0.3, lo=0.2, hi=0.4)
    res = compare_batches(a, b)
    assert res["items"][0]["verdict"] == "回归" and res["n_regressed"] == 1


def test_compare_says_no_data_when_a_side_is_all_infra(tmp_path):
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.5, lo=0.4, hi=0.6)
    b = _fake_batch(tmp_path, "b", median=None, lo=None, hi=None, n_valid=0)
    assert compare_batches(a, b)["items"][0]["verdict"] == "无数据"


def test_compare_does_not_silently_drop_items_exclusive_to_batch_b(tmp_path):
    """b 独有的 (role, item)——两批 case 不同、或某棒在 a 批被旁路——不得从报告里消失。

    只遍历 a 的键会把 b 独有项静默丢掉:改完 prompt 后新增的体检项、或 a 批
    因旁路完全没跑到的棒,report 里会看不见,这与"不让人漏看变化"的宗旨相悖。
    """
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.5, lo=0.4, hi=0.6)
    b = _fake_batch(tmp_path, "b", median=0.5, lo=0.4, hi=0.6)
    sb = json.loads((b / "summary.json").read_text(encoding="utf-8"))
    sb["steps"]["大纲师"] = {"大纲师·场景数": {"median": 0.9, "lo": 0.8, "hi": 1.0,
                                          "n_valid": 3, "n_total": 3}}
    (b / "summary.json").write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")

    res = compare_batches(a, b)
    keys = {(it["step"], it["item"]) for it in res["items"]}
    assert ("大纲师", "大纲师·场景数") in keys, "b 独有项被静默丢掉了"
    only_b = [it for it in res["items"] if it["step"] == "大纲师"][0]
    assert only_b["verdict"] == "无数据" and only_b["before"] is None
    assert only_b["after"]["median"] == pytest.approx(0.9)
    # a 独有项(若反过来)同理必须出现——用同一断言口径覆盖对称情形
    assert len(res["items"]) == 2, "两批合计两个 (role,item) 键,一个都不能丢"


def test_cli_compare_requires_two_batches(tmp_path):
    from evals.generate import main
    assert main(["--compare", str(tmp_path / "nope")]) == 2


def test_compare_surfaces_sample_counts_for_thin_batches(tmp_path, capsys):
    """n_valid==1 时 distribution() 给出零宽区间(lo==hi==median),两个不同的零宽
    区间几乎必然不重叠——于是判据据实吐出「改进」,但那只是 1 次跑 vs 1 次跑的结果。
    读者必须能从输出里看出这是薄比对,不能让 1-of-N 和 N-of-N 打印得一模一样。
    """
    from evals.generate import compare_batches, main
    a = _fake_batch(tmp_path, "a", median=0.2, lo=0.2, hi=0.2, n_valid=1)
    b = _fake_batch(tmp_path, "b", median=0.8, lo=0.8, hi=0.8, n_valid=1)

    res = compare_batches(a, b)
    item = res["items"][0]
    assert item["verdict"] == "改进"  # 零宽区间不重叠,判据本身没错——问题是样本数不可见
    assert item["n_valid_before"] == 1 and item["n_total_before"] == 3
    assert item["n_valid_after"] == 1 and item["n_total_after"] == 3

    code = main(["--compare", str(a), str(b)])
    out = capsys.readouterr().out
    assert code == 0
    assert "1/3" in out, f"CLI 打印里看不到样本数,thin 比对和 solid 比对长得一样:{out!r}"


def test_cli_repeat_flag_returns_2_when_all_infra(tmp_path, monkeypatch):
    """全 infra → 退出码 2(沿用三态),不得当成质量结论。"""
    monkeypatch.setenv("LOOM_DEMO", "1")
    from evals.generate import main
    src = _write_gen_case(tmp_path)
    gc = tmp_path / "gc"; gc.mkdir()
    shutil.copytree(src, gc / "gen_test")
    # chapter_chars 设成天文数字,DemoBackend 罐头文本必然过不了终稿最短闸 → 每次都崩
    case_path = gc / "gen_test" / "case.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["chapter_chars"] = 900000
    case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    code = main(["--cases-dir", str(gc), "--runs-dir", str(tmp_path / "runs"), "--repeat", "2"])
    assert code == 2
