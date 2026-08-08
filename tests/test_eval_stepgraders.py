"""棒级体检项:每项都是「上游有、这一棒输出里没了」的差分。纯确定性,零 LLM。"""
from evals.stepgraders import (
    grade_editor,
    grade_outliner,
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


_GOOD_OUTLINE = ("场景一 · 当夜 · 矿底 · 沈砚 · 醒来验伤 · 约80字\n"
                 "场景二 · 稍后 · 矿道 · 沈砚与巡矿人 · 矿灯照面 · 约70字\n"
                 "场景三 · 拂晓 · 矿口 · 沈砚 · 听见追兵 · 约50字")


# ── 大纲师 ─────────────────────────────────────────────────────────────────
def test_outliner_flags_must_include_dropped_at_outline_layer():
    g = _by_name(grade_outliner(_GOOD_OUTLINE, 200, ["矿灯", "师姐"]), "大纲师·必含要素")
    assert g.passed is False
    assert any("师姐" in e for e in g.evidence)
    assert not any("矿灯" in e for e in g.evidence)


def test_outliner_scene_count_uses_product_scene_range():
    # 200 字目标 → scene_range 给 (2,3);上面细纲正好 3 场 → 达标
    assert _by_name(grade_outliner(_GOOD_OUTLINE, 200, []), "大纲师·场次数").passed is True
    # 5000 字目标 → 应 4-6 场,3 场不够
    g = _by_name(grade_outliner(_GOOD_OUTLINE, 5000, []), "大纲师·场次数")
    assert g.passed is False
    assert "4-6 场" in g.detail


def test_outliner_flags_missing_scene_budget_annotations():
    bare = "场景一 醒来。\n场景二 遇人。\n场景三 追兵。"
    g = _by_name(grade_outliner(bare, 200, []), "大纲师·篇幅预算")
    assert g.passed is False
    assert "没标" in g.detail


def test_outliner_flags_budget_sum_far_from_chapter_target():
    # 各场合计 200,章目标 3000 → 偏差远超 30%
    g = _by_name(grade_outliner(_GOOD_OUTLINE, 3000, []), "大纲师·篇幅预算")
    assert g.passed is False


def test_outliner_skipped_when_bypassed():
    res = grade_outliner(None, 200, ["矿灯"])
    assert all(g.gating is False and g.detail.startswith("[skipped]") for g in res)


# ── 编辑 ───────────────────────────────────────────────────────────────────
_DRAFT_FIX = "沈砚睁开眼，矿灯昏黄。他记得三年后的那一刀。"
_EDITED_OK = (_DRAFT_FIX + "\n<LOOM:EDIT-NOTE>\n- 钩子更硬。\n</LOOM:EDIT-NOTE>")


def test_editor_fence_pair_ok():
    assert _by_name(grade_editor(_EDITED_OK, _DRAFT_FIX, []), "编辑·留痕围栏").passed is True


def test_editor_flags_unclosed_fence():
    bad = _DRAFT_FIX + "\n<LOOM:EDIT-NOTE>\n- 忘了收尾。"
    g = _by_name(grade_editor(bad, _DRAFT_FIX, []), "编辑·留痕围栏")
    assert g.passed is False
    assert "未闭合" in g.detail


def test_editor_flags_no_note_at_all():
    g = _by_name(grade_editor(_DRAFT_FIX, _DRAFT_FIX, []), "编辑·留痕围栏")
    assert g.passed is False


def test_editor_flags_must_include_dropped_by_editor():
    """初稿有、改稿没了 —— 这比「初稿本来就缺」严重得多,必须单独抓。"""
    edited = "沈砚睁开眼。他记得三年后的那一刀。\n<LOOM:EDIT-NOTE>\n- 删了。\n</LOOM:EDIT-NOTE>"
    g = _by_name(grade_editor(edited, _DRAFT_FIX, ["矿灯"]), "编辑·必含要素保持")
    assert g.passed is False
    assert any("矿灯" in e and "改丢" in e for e in g.evidence)


def test_editor_does_not_blame_editor_for_what_draft_never_had():
    """初稿本来就没有的必含项,不算编辑改丢的——归因必须指对棒。"""
    g = _by_name(grade_editor(_EDITED_OK, _DRAFT_FIX, ["师姐"]), "编辑·必含要素保持")
    assert g.passed is True


def test_editor_flags_expansion():
    edited = ("字" * 2000) + "\n<LOOM:EDIT-NOTE>\n- 扩写了。\n</LOOM:EDIT-NOTE>"
    g = _by_name(grade_editor(edited, "字" * 500, []), "编辑·篇幅变化")
    assert g.passed is False


def test_editor_note_body_excluded_from_length():
    """留痕不是正文:算篇幅必须先剥围栏,否则留痕越长越显得「扩写」。"""
    long_note = "\n<LOOM:EDIT-NOTE>\n" + ("留痕。" * 300) + "\n</LOOM:EDIT-NOTE>"
    g = _by_name(grade_editor(_DRAFT_FIX + long_note, _DRAFT_FIX, []), "编辑·篇幅变化")
    assert g.passed is True


def test_editor_skipped_when_upstream_missing():
    assert all(g.gating is False for g in grade_editor(None, _DRAFT_FIX, []))
