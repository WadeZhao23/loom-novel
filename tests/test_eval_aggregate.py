"""N 次运行 → 分布。temp=0.9 无 seed,单次分数差一律不作结论。

红线:不造数——N 次里 M 次 infra 就照实记两个数,绝不用 M 次均值冒充 N 次。
"""
import pytest

from evals.aggregate import Distribution, aggregate_runs, distribution, overlaps


# ── distribution ───────────────────────────────────────────────────────────
def test_distribution_odd_count():
    d = distribution([0.2, 0.8, 0.5])
    assert d.median == 0.5 and d.lo == 0.2 and d.hi == 0.8
    assert d.n_valid == 3 and d.n_total == 3


def test_distribution_even_count_averages_middle_two():
    d = distribution([0.2, 0.4, 0.6, 0.8])
    assert d.median == pytest.approx(0.5)


def test_distribution_drops_none_and_reports_both_counts():
    """5 次里 2 次 infra:必须照实记 n_valid=3 / n_total=5,不得拿 3 次冒充 5 次。"""
    d = distribution([0.4, None, 0.6, None, 0.5])
    assert d.n_valid == 3 and d.n_total == 5
    assert d.median == 0.5


def test_distribution_all_infra_is_none_not_zero():
    d = distribution([None, None])
    assert d.median is None and d.lo is None and d.hi is None
    assert d.n_valid == 0 and d.n_total == 2


def test_distribution_empty():
    d = distribution([])
    assert d.n_valid == 0 and d.n_total == 0 and d.median is None


def test_distribution_high_precision_invariant_odd_count():
    """高精度输入:中位数必须在 lo 和 hi 范围内(四舍五入后仍需满足)。

    两端都四舍五入到 4 位小数时,须保持 lo <= median <= hi,防回归。
    """
    d = distribution([0.123456789])
    assert d.median <= d.hi, f"median {d.median} should be <= hi {d.hi}"
    assert d.lo <= d.median, f"lo {d.lo} should be <= median {d.median}"
    assert d.lo <= d.hi, f"lo {d.lo} should be <= hi {d.hi}"


def test_distribution_high_precision_invariant_even_count():
    """高精度输入:偶数个时中位数为中间两个的平均。均值也四舍五入到 4 位小数时,
    须保持 lo <= median <= hi。
    """
    d = distribution([0.66666666, 0.66666677])
    assert d.median <= d.hi, f"median {d.median} should be <= hi {d.hi}"
    assert d.lo <= d.median, f"lo {d.lo} should be <= median {d.median}"
    assert d.lo <= d.hi, f"lo {d.lo} should be <= hi {d.hi}"


# ── overlaps ───────────────────────────────────────────────────────────────
def _dist(lo, hi):
    return {"lo": lo, "hi": hi, "median": (lo + hi) / 2, "n_valid": 3, "n_total": 3}


def test_overlaps_true_when_ranges_touch():
    assert overlaps(_dist(0.4, 0.7), _dist(0.6, 0.9)) is True


def test_overlaps_false_when_separated():
    assert overlaps(_dist(0.1, 0.3), _dist(0.6, 0.9)) is False


def test_overlaps_true_when_either_side_unmeasured():
    """一边没有有效数据 → 不能宣称分开,保守判重叠(不造结论)。"""
    assert overlaps(_dist(0.1, 0.3), {"lo": None, "hi": None,
                                      "median": None, "n_valid": 0, "n_total": 3}) is True


# ── aggregate_runs ─────────────────────────────────────────────────────────
def _report(setter_score, writer_score, *, writer_passed=True):
    return {
        "steps": {
            "设定师": [{"name": "设定师·硬设定专名", "score": setter_score, "passed": True,
                      "weight": 0.3, "gating": True, "detail": "", "evidence": []}],
            "写手": [{"name": "写手·必含要素", "score": writer_score, "passed": writer_passed,
                    "weight": 0.3, "gating": True, "detail": "", "evidence": []}],
        },
        "weakest": None if writer_passed else "写手",
    }


def test_aggregate_runs_builds_per_item_distributions():
    agg = aggregate_runs([_report(1.0, 0.5), _report(1.0, 0.7), _report(1.0, 0.6)])
    assert agg["n_total"] == 3 and agg["n_valid"] == 3
    w = agg["steps"]["写手"]["写手·必含要素"]
    assert w["median"] == 0.6 and w["lo"] == 0.5 and w["hi"] == 0.7


def test_aggregate_runs_counts_infra_runs_honestly():
    agg = aggregate_runs([_report(1.0, 0.5), None, _report(1.0, 0.7)])
    assert agg["n_total"] == 3 and agg["n_valid"] == 2
    assert agg["steps"]["写手"]["写手·必含要素"]["n_valid"] == 2


def test_aggregate_runs_all_infra_returns_no_numbers():
    agg = aggregate_runs([None, None])
    assert agg["n_valid"] == 0 and agg["steps"] == {} and agg["weakest"] is None


def test_aggregate_runs_weakest_is_majority_vote():
    """最弱棒按多数决,不被单次波动带偏。"""
    agg = aggregate_runs([_report(1.0, 0.2, writer_passed=False),
                          _report(1.0, 0.3, writer_passed=False),
                          _report(1.0, 0.9)])
    assert agg["weakest"] == "写手"


def test_aggregate_runs_no_weakest_when_mostly_clean():
    agg = aggregate_runs([_report(1.0, 0.9), _report(1.0, 0.9),
                          _report(1.0, 0.2, writer_passed=False)])
    assert agg["weakest"] is None


def test_aggregate_runs_infra_run_first_still_aligns_length():
    """整体 infra 的 run 排在第一个时,每项分数列表长度仍须等于 n_total。

    参考实现在这里踩过坑:靠"遍历时已经见过的 item 名字"给 infra run 补 None,
    第一个 run 就是 None 时,当时 item_scores 还是空的,补不到任何东西——
    该 item 的分数列表就会短一格,n_total 被悄悄算成 1 而不是 2。
    """
    agg = aggregate_runs([None, _report(1.0, 0.7)])
    assert agg["n_total"] == 2 and agg["n_valid"] == 1
    w = agg["steps"]["写手"]["写手·必含要素"]
    assert w["n_total"] == 2 and w["n_valid"] == 1 and w["median"] == 0.7


def test_aggregate_runs_multiple_infra_runs_scattered():
    """infra 散落在首、中、尾,每项列表长度都要等于 n_total=4。"""
    agg = aggregate_runs([None, _report(1.0, 0.5), None, _report(1.0, 0.9)])
    w = agg["steps"]["写手"]["写手·必含要素"]
    assert agg["n_total"] == 4 and agg["n_valid"] == 2
    assert w["n_total"] == 4 and w["n_valid"] == 2
    assert w["median"] == pytest.approx(0.7)


def test_aggregate_runs_skipped_item_excluded_from_distribution():
    """detail 带 [skipped]/[not-measurable] 前缀的项(真正没测到)不进分布——
    不能被当 0 分冲进中位数,也不能被当"有效测过"计进 n_valid。

    排除靠的是 detail 前缀,不是 gating——见下面
    test_aggregate_runs_observe_only_item_with_real_score_is_included。
    """
    report_a = {
        "steps": {"写手": [
            {"name": "写手·对话密度", "score": 0.0, "passed": True,
             "weight": 0.0, "gating": False, "detail": "[skipped] 无对话可测", "evidence": []},
        ]},
        "weakest": None,
    }
    report_b = {
        "steps": {"写手": [
            {"name": "写手·对话密度", "score": 0.8, "passed": True,
             "weight": 0.3, "gating": True, "detail": "", "evidence": []},
        ]},
        "weakest": None,
    }
    agg = aggregate_runs([report_a, report_b])
    d = agg["steps"]["写手"]["写手·对话密度"]
    assert d["n_total"] == 2
    assert d["n_valid"] == 1  # 只有 report_b 那次算数
    assert d["median"] == 0.8  # 不能被 skipped 的 0 分拉低


def test_aggregate_runs_observe_only_item_with_real_score_is_included():
    """observe-only 项(gating=False, weight=0.0,但**每次都真测了**,如写手·AI翻转句)
    必须进分布——不能因为 gating=False 就当"没测到"丢掉,那样报告会把真实测过的
    信号说成"从未测过"(Important-1:此前 aggregate.py 用 gating 当排除判据,把这类
    观测项和真正的 skipped/[not-measurable] 项混为一谈,一起被排除)。
    """
    report_a = {
        "steps": {"写手": [
            {"name": "写手·AI翻转句", "score": 0.5, "passed": True,
             "weight": 0.0, "gating": False, "detail": "命中 1 处(初稿基线)", "evidence": []},
        ]},
        "weakest": None,
    }
    report_b = {
        "steps": {"写手": [
            {"name": "写手·AI翻转句", "score": 1.0, "passed": True,
             "weight": 0.0, "gating": False, "detail": "命中 0 处(初稿基线)", "evidence": []},
        ]},
        "weakest": None,
    }
    agg = aggregate_runs([report_a, report_b])
    d = agg["steps"]["写手"]["写手·AI翻转句"]
    assert d["n_total"] == 2
    assert d["n_valid"] == 2, "两次都真测过,不能因 gating=False 被当没测到"
    assert d["median"] == 0.75


# ── 判据从 min~max 换成 Mann-Whitney(2026-08-10 真事故) ──────────────────
# 事故:设定师·锚点篇幅 10v10,改前 [0.0 … 0.934] vs 改后 [0.537 … 1.0]。
# min~max 判「重叠 → 分不出」,精确检验 p=0.0245——旧判据把一个【真实的改进】
# 判成了没变化(假阴性)。根因:min~max 描述样本铺多开,不随 N 收窄。

from evals.aggregate import mannwhitney_p, distribution, overlaps

# 事故当天的真实数据,逐字钉住
_PRE_ANCHOR = [0.0, 0.286, 0.309, 0.323, 0.526, 0.686, 0.703, 0.837, 0.894, 0.934]
_POST_ANCHOR = [0.537, 0.643, 0.703, 0.754, 0.846, 0.88, 0.971, 0.983, 1.0, 1.0]


def test_mannwhitney_matches_independently_verified_exact_values():
    """这三个 p 是用暴力置换枚举(C(20,10)=184756 全枚举)独立算过的,DP 实现必须对上。"""
    p, how = mannwhitney_p(_PRE_ANCHOR, _POST_ANCHOR)
    assert how == "精确"
    assert abs(p - 0.0245) < 1e-3, p
    # 写手·AI翻转句 与 润色师·AI味下降 当天的真实分数
    p2, _ = mannwhitney_p([0.333] * 4 + [1.0] * 6,
                          [0.2, 0.25, 0.25, 0.333, 0.5, 0.5, 0.5, 0.5, 1.0, 1.0])
    assert abs(p2 - 0.1476) < 1e-3, p2
    p3, _ = mannwhitney_p([0.0] * 3 + [1.0] * 7, [0.0] * 5 + [0.5] + [1.0] * 4)
    assert abs(p3 - 0.3698) < 1e-3, p3


def test_old_minmax_criterion_would_have_missed_it():
    """反证这条测试的必要性:旧判据在同一份数据上确实判「重叠」。

    哪天有人想把判据改回区间,这条会提醒他当初为什么换掉。"""
    da = distribution(_PRE_ANCHOR).as_dict()
    db = distribution(_POST_ANCHOR).as_dict()
    assert overlaps(da, db) is True                      # 旧判据:分不出
    assert mannwhitney_p(_PRE_ANCHOR, _POST_ANCHOR)[0] < 0.05   # 新判据:改进


def test_p_shrinks_as_n_grows_at_same_effect():
    """核心性质:效应比例不变、样本变多 → p 必须变小。

    min~max 恰恰相反(N 越大越易抽到极端值、区间越宽),这是换判据的根本理由。"""
    ps = []
    for mult in (1, 2, 3):
        a = [0.333] * (4 * mult) + [1.0] * (6 * mult)
        b = [0.25] * (6 * mult) + [1.0] * (4 * mult)
        ps.append(mannwhitney_p(a, b)[0])
    assert ps[0] > ps[1] > ps[2], ps


def test_identical_batches_are_indistinguishable():
    xs = [0.2, 0.4, 0.6, 0.8, 1.0]
    p, _ = mannwhitney_p(xs, list(xs))
    assert p > 0.9


def test_empty_side_makes_no_claim():
    assert mannwhitney_p([], [1.0, 2.0]) == (1.0, "无数据")
    assert mannwhitney_p([1.0], []) == (1.0, "无数据")


def test_distribution_persists_raw_scores():
    """判据要原始分数;summary.json 不存它,--compare 就只能退回旧区间判据。"""
    d = distribution([0.5, None, 0.1, 0.9]).as_dict()
    assert d["scores"] == [0.1, 0.5, 0.9]
    assert d["n_valid"] == 3 and d["n_total"] == 4
    assert distribution([None, None]).as_dict()["scores"] is None
