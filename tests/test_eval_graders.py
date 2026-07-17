"""确定性 grader 的正反例+边界。别与 test_length_screws.py 重复 grade_length 的既有断言。"""
from evals.graders import grade_aitell, grade_keywords


def test_keywords_must_include_missing_fails():
    g = grade_keywords("这章没有那个词", must_include=["师姐"], must_not_include=None)
    assert g.passed is False and "师姐" in "".join(g.evidence)


def test_keywords_must_not_include_present_fails():
    g = grade_keywords("这章写了二中", must_include=None, must_not_include=["二中"])
    assert g.passed is False


def test_keywords_clean_passes():
    g = grade_keywords("师姐登场了", must_include=["师姐"], must_not_include=["二中"])
    assert g.passed is True


def test_aitell_flip_sentence_caught():
    # AI 翻转句(「不是…而是…」式)该被抓
    flip = "他不是不想说,而是不敢说。" * 3
    g = grade_aitell(flip, anchors=[], max_hits=0)
    assert g.passed is False and g.score < 1.0


def test_aitell_anchor_exempts():
    # 先反证:不给 anchor 时,这句翻转句确实会被判定为 AI 腔命中
    flip_sentence = "他不是不想说,而是不敢说。"
    without_anchor = grade_aitell(flip_sentence, anchors=[], max_hits=0)
    assert without_anchor.passed is False

    # 同一句收进 anchors(作者签名句)→ 豁免,不算 AI 腔
    g = grade_aitell(flip_sentence, anchors=[flip_sentence], max_hits=0)
    assert g.passed is True
