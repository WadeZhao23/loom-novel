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
