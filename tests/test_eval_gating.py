"""维度门禁策略:默认 observe,校准达标才晋级——信息边界已据真校准报告晋级 hard。"""
from evals.calibration import gate_hard_dimensions, gate_policy, load_gating, load_targets
from evals.dataset import DIMENSIONS


def test_gating_covers_all_dims_observe_except_calibration_backed_promotions():
    # 未被校准报告背书晋级的维度仍须是 observe(无校准不硬门禁);
    # 已晋级的维度由 test_current_hard_is_exactly_信息边界 单独钉死是谁。
    g = load_gating()
    hard = {d for d, p in g["dimensions"].items() if p == "hard"}
    for d in DIMENSIONS:
        if d in hard:
            continue
        assert g["dimensions"][d] == "observe"      # 未晋级维度:无校准不硬门禁
    assert "校准" in g["note"] or "达标" in g["note"]


def test_gate_policy_unknown_dim_defaults_observe():
    assert gate_policy("不存在的维度", load_gating()) == "observe"


def test_gate_policy_reads_declared():
    g = {"dimensions": {"AI腔": "hard"}}
    assert gate_policy("AI腔", g) == "hard"
    assert gate_policy("设定漂移", g) == "observe"   # 未声明 → observe


def test_hard_dims_are_calibration_backed_high_cost():
    """晋级纪律:任何 hard 维度必须①是预注册高代价维、②有已提交校准报告为证。
    防凭印象把维度翻 hard(spec §Phase3/4:校准达标才晋级)。"""
    import json
    from pathlib import Path
    from evals.calibration import load_gating, load_targets
    g = load_gating()["dimensions"]
    hard = [d for d, p in g.items() if p == "hard"]
    high_cost = set(load_targets()["high_cost_dimensions"])
    for d in hard:
        assert d in high_cost, f"{d} 晋级 hard 但不是高代价维"
    report = Path("evals/calibration/report.json")
    if hard:
        assert report.is_file(), "有 hard 维度但缺 evals/calibration/report.json 校准证据"
        jvg = json.loads(report.read_text(encoding="utf-8"))["judge_vs_gold"]
        target = load_targets()["high_cost_recall"]
        for d in hard:
            assert jvg[d]["recall"] is not None and jvg[d]["recall"] >= target, \
                f"{d} 是 hard 但校准报告里 recall 未达 {target}"


def test_current_hard_is_exactly_信息边界():
    from evals.calibration import load_gating
    g = load_gating()["dimensions"]
    assert [d for d, p in g.items() if p == "hard"] == ["信息边界"]   # 本期只晋级这一项


def test_gating_dimensions_exactly_match_dataset():
    # 跨模块耦合护栏:gating.json 的维度键必须恰好=DIMENSIONS(不多不少)——
    # 防打错字混入伪维度、或改 DIMENSIONS 后 gating 漏同步。
    assert set(load_gating()["dimensions"].keys()) == set(DIMENSIONS)


def _report_with(recalls: dict):
    # 构造最小 report:judge_vs_gold 每维给定 recall
    from evals.dataset import DIMENSIONS
    jvg = {d: {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0,
               "recall": recalls.get(d), "f1": None} for d in DIMENSIONS}
    return {"judge_vs_gold": jvg}


def test_gate_passes_when_hard_dim_clears_target():
    gating = {"dimensions": {"信息边界": "hard"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": 1.0}), gating, load_targets())
    assert ok is True and failures == []


def test_gate_fails_when_hard_dim_below_target():
    gating = {"dimensions": {"信息边界": "hard"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": 0.5}), gating, load_targets())
    assert ok is False and any("信息边界" in f for f in failures)


def test_gate_ignores_observe_dims():
    gating = {"dimensions": {"信息边界": "observe", "AI腔": "observe"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": 0.1, "AI腔": 0.0}), gating, load_targets())
    assert ok is True and failures == []          # observe 不参与门禁


def test_gate_warns_on_unmeasurable_hard_dim():
    gating = {"dimensions": {"信息边界": "hard"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": None}), gating, load_targets())
    assert ok is True and failures == [] and any("信息边界" in w for w in warns)  # 无正例→跳过不失败


def test_gate_boundary_recall_equals_target_passes():
    # recall 恰好等于 target 应通过(≥ 非严格 >)——钉死边界,防重构悄悄引入 > 回归
    gating = {"dimensions": {"信息边界": "hard"}}
    target = load_targets()["high_cost_recall"]
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": target}), gating, load_targets())
    assert ok is True and failures == []
