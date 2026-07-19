"""κ / P·R·F1 纯函数:手算小样本对拍。零真实模型、零外部依赖。"""
import pytest

from evals.calibration import PRF, cohen_kappa, evaluate_against_targets, load_targets, prf_for_dimension


def test_kappa_perfect_agreement():
    assert cohen_kappa([True, False, True], [True, False, True]) == 1.0


def test_kappa_chance_level_near_zero():
    # 对角与反对角各半,po=0.5;两方各 50% 正例 → pe=0.5 → κ=0
    a = [True, True, False, False]
    b = [True, False, True, False]
    assert abs(cohen_kappa(a, b) - 0.0) < 1e-9


def test_kappa_known_value():
    # 教科书例:po=0.7, pe=0.5 → κ=(0.7-0.5)/(1-0.5)=0.4
    # 注:brief 原始 b=[T]*3+[F]*2+[T]*2+[F]*3 实际只 6/10 一致(po=0.6→κ=0.2),手算有误,
    # 已改用真正 7/10 一致的序列对拍(pe=0.5 由 a 自身 50/50 保证,与 b 的分布无关)。
    a = [True]*5 + [False]*5
    b = [True]*3 + [False]*2 + [True]*1 + [False]*4   # a∩b 一致 7/10(验证见下方独立核对)
    assert abs(cohen_kappa(a, b) - 0.4) < 1e-9


def test_kappa_length_mismatch_raises():
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False])


def test_kappa_single_category_all_false():
    assert cohen_kappa([False, False], [False, False]) == 1.0   # 都判 absent 且一致


def test_prf_perfect():
    p = prf_for_dimension([True, False, True], [True, False, True])
    assert p.tp == 2 and p.fp == 0 and p.fn == 0
    assert p.precision == 1.0 and p.recall == 1.0 and p.f1 == 1.0


def test_prf_with_errors():
    # gold: 1,1,0 ; pred: 1,0,1 → tp=1 fp=1 fn=1 → P=R=0.5 F1=0.5
    p = prf_for_dimension([True, True, False], [True, False, True])
    assert (p.tp, p.fp, p.fn) == (1, 1, 1)
    assert p.precision == 0.5 and p.recall == 0.5 and p.f1 == 0.5


def test_prf_no_predictions_precision_none():
    # 无任何 pred 正例 → precision 未定义(None),recall=0
    p = prf_for_dimension([True, False], [False, False])
    assert p.tp == 0 and p.precision is None and p.recall == 0.0


def test_targets_preregistered_values():
    t = load_targets()
    assert t["kappa_human_human"] == 0.70
    assert t["kappa_judge_gold"] == 0.60
    assert t["high_cost_recall"] == 0.85
    assert isinstance(t["high_cost_dimensions"], list) and t["high_cost_dimensions"]
    assert "待验收标准" in t["note"] or "非当前事实" in t["note"]   # 诚实性:不冒充结果


def test_evaluate_meets_target():
    r = evaluate_against_targets(0.72, 0.70)
    assert r["met"] is True and r["value"] == 0.72 and r["target"] == 0.70


def test_evaluate_below_target():
    assert evaluate_against_targets(0.55, 0.60)["met"] is False


def test_evaluate_no_data_is_none_not_fail():
    r = evaluate_against_targets(None, 0.70)
    assert r["met"] is None       # 无数据 ≠ 未达标,是「待测」


def test_high_cost_dimensions_are_real_dimensions():
    # 跨模块耦合护栏:targets.json 的高代价维必须是真实 DIMENSIONS 成员——
    # 防将来改维度名/打错字让 Phase 4 硬门禁悄悄指向不存在的维度。
    from evals.dataset import DIMENSIONS
    assert set(load_targets()["high_cost_dimensions"]) <= set(DIMENSIONS)
