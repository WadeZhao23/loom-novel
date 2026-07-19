"""三源统一报告(fixture/generation/judge 校准),缺源诚实留空。零真实模型。"""
import json


def test_report_assembles_three_sources(tmp_path):
    from evals.report import build_run_report, write_run_report
    fixture = {"passed": 3, "cases": 3, "regressions": []}
    generation = [{"run_id": "r1", "git_commit": "abc", "backend_class": "DemoBackend"}]
    calibration = {"coverage": {"n_total": 11, "n_evaluated": 8, "n_infra_dropped": 3,
                                "dropped_case_ids": ["a", "b", "c"]}, "judge_vs_gold": {}}
    rep = build_run_report(fixture, generation, calibration)
    assert rep["fixture"]["passed"] == 3
    assert rep["generation"][0]["run_id"] == "r1"
    assert rep["calibration"]["coverage"]["n_infra_dropped"] == 3
    j, m = write_run_report(rep, tmp_path)
    assert j.is_file() and m.is_file()
    assert json.loads(j.read_text(encoding="utf-8"))["fixture"]["passed"] == 3


def test_report_missing_sources_marked_pending(tmp_path):
    from evals.report import build_run_report, write_run_report
    rep = build_run_report({"passed": 3, "cases": 3, "regressions": []}, None, None)
    assert rep["generation"]["status"] == "未跑" or rep["generation"] == []
    assert rep["calibration"]["status"] == "待真机"
    _, m = write_run_report(rep, tmp_path)
    assert "待真机" in m.read_text(encoding="utf-8")     # MD 如实标缺源


def test_report_md_single_lists_high_cost_recall():
    from evals.report import build_run_report, write_run_report
    calibration = {
        "coverage": {"n_total": 11, "n_evaluated": 11, "n_infra_dropped": 0, "dropped_case_ids": []},
        "targets": {"high_cost_dimensions": ["信息边界", "设定漂移"]},
        "judge_vs_gold": {"信息边界": {"tp": 1, "fp": 0, "fn": 1, "precision": 1.0, "recall": 0.5, "f1": 0.667},
                          "设定漂移": {"tp": 2, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}},
    }
    rep = build_run_report({"passed": 3, "cases": 3, "regressions": []}, None, calibration)
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        _, m = write_run_report(rep, pathlib.Path(td))
        md = m.read_text(encoding="utf-8")
    assert "高代价维度" in md
    assert "信息边界" in md and "recall=0.5" in md    # 高代价维 recall 真的单列出来了
    assert "设定漂移" in md and "recall=1.0" in md
