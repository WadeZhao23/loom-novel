"""κ / P·R·F1 纯函数:手算小样本对拍。零真实模型、零外部依赖。"""
import pytest

from evals.calibration import PRF, cohen_kappa, prf_for_dimension


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
