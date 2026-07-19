"""维度门禁策略:初始全 observe,校准达标才晋级(本 Phase 只建机制不晋级)。"""
from evals.calibration import gate_hard_dimensions, gate_policy, load_gating, load_targets
from evals.dataset import DIMENSIONS


def test_gating_covers_all_dims_initially_observe():
    g = load_gating()
    for d in DIMENSIONS:
        assert g["dimensions"][d] == "observe"      # 初始全 observe(无校准前不硬门禁)
    assert "校准" in g["note"] or "达标" in g["note"]


def test_gate_policy_unknown_dim_defaults_observe():
    assert gate_policy("不存在的维度", load_gating()) == "observe"


def test_gate_policy_reads_declared():
    g = {"dimensions": {"AI腔": "hard"}}
    assert gate_policy("AI腔", g) == "hard"
    assert gate_policy("设定漂移", g) == "observe"   # 未声明 → observe


def test_gating_has_no_hard_dimensions_yet():
    """护栏:本 Phase 只建机制,不晋级任何维度——gating.json 里不该出现 hard。"""
    assert "hard" not in load_gating()["dimensions"].values()


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
