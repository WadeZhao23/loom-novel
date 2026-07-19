"""维度门禁策略:初始全 observe,校准达标才晋级(本 Phase 只建机制不晋级)。"""
from evals.calibration import gate_policy, load_gating
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
