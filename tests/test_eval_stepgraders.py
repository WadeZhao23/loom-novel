"""棒级体检项:每项都是「上游有、这一棒输出里没了」的差分。纯确定性,零 LLM。"""
from evals.stepgraders import (
    grade_polisher,
    grade_setter,
    grade_writer,
    skipped,
)


def _by_name(results, name):
    for r in results:
        if r.name == name:
            return r
    raise AssertionError(f"没有名为 {name} 的体检项:{[r.name for r in results]}")


# ── skipped 形状 ───────────────────────────────────────────────────────────
def test_skipped_shape_does_not_pollute_gating():
    g = skipped("大纲师", "细纲覆盖必含要素")
    assert g.passed is True, "这棒没跑不该判失败"
    assert g.gating is False
    assert g.detail.startswith("[skipped]")


# ── 设定师 ─────────────────────────────────────────────────────────────────
def test_setter_flags_missing_hardfact_term():
    res = grade_setter("本章设定锚点:主角在废矿。", ["逆息", "F~SSS"])
    g = _by_name(res, "设定师·硬设定专名")
    assert g.passed is False
    assert any("逆息" in e for e in g.evidence)
    assert any("F~SSS" in e for e in g.evidence)


def test_setter_passes_when_all_terms_present():
    res = grade_setter("锚点:逆息体质,力量体系 F~SSS。", ["逆息", "F~SSS"])
    assert _by_name(res, "设定师·硬设定专名").passed is True


def test_setter_flags_overlong_anchor():
    res = grade_setter("锚" * 400, [])
    g = _by_name(res, "设定师·锚点篇幅")
    assert g.passed is False
    assert "350" in g.detail


def test_setter_skipped_when_no_output():
    res = grade_setter(None, ["逆息"])
    assert all(g.gating is False and g.detail.startswith("[skipped]") for g in res)


# ── 写手 ───────────────────────────────────────────────────────────────────
def test_writer_flags_short_draft():
    res = grade_writer("短稿。", 600, [], [])
    g = _by_name(res, "写手·初稿篇幅")
    assert g.passed is False
    assert "600" in g.detail


def test_writer_flags_dropped_must_include():
    res = grade_writer("沈砚睁开眼。" * 60, 300, ["矿灯"], [])
    g = _by_name(res, "写手·必含要素")
    assert g.passed is False
    assert any("矿灯" in e for e in g.evidence)


def test_writer_counts_aitell_hits():
    res = grade_writer("他不是累，而是怕。" * 40, 300, [], [])
    g = _by_name(res, "写手·AI翻转句")
    assert g.detail.startswith("命中")


# ── 润色师 ─────────────────────────────────────────────────────────────────
def test_polisher_flags_aitell_not_reduced():
    edited = "他不是累，而是怕。" * 5
    polished = edited                      # 一处都没擦掉
    g = _by_name(grade_polisher(polished, edited, []), "润色师·AI味下降")
    assert g.passed is False
    assert "0" in g.detail


def test_polisher_passes_when_aitell_drops():
    edited = "他不是累，而是怕。" * 5
    polished = "他累，也怕。" * 5           # 翻转句被擦掉
    assert _by_name(grade_polisher(polished, edited, []), "润色师·AI味下降").passed is True


def test_polisher_flags_shrinkage():
    edited = "字" * 1000
    polished = "字" * 500                   # 越擦越短一半
    g = _by_name(grade_polisher(polished, edited, []), "润色师·篇幅保持")
    assert g.passed is False


def test_polisher_skipped_when_upstream_missing():
    res = grade_polisher("终稿", None, [])
    assert all(g.gating is False for g in res)
