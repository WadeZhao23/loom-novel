"""确定性 grader 的正反例+边界。别与 test_length_screws.py 重复 grade_length 的既有断言。

下半部分:LLM grader 的失败路径——判词解析不出时必须判 infra,绝不假装满分通过。
"""
from evals.graders import grade_aitell, grade_deslop_llm, grade_keywords, grade_quality_llm


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
    # AI 翻转句(「不是…而是…」式)该被抓。
    # 注:×3 的重复句经 detect_aitell 按证据去重后仍只算 1 条命中——断言只依赖「≥1 命中」,
    # 不是在测「多次命中撞阈值」。
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


class _FixedBackend:
    """恒定回同一段判词,用来钉死解析分支。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
        return self.reply


def test_quality_llm_unparsable_verdict_is_infra_not_pass():
    # 模型回编号列表(prompt 要的是 `- ` 开头),parse_critic_verdict 抓不到条目
    be = _FixedBackend("1. 人物OOC:主角性格突变\n2. 断钩子:章末平淡")
    g = grade_quality_llm("正文", "设定", be)
    assert g.passed is False, "解析失败不得判通过"
    assert g.gating is False, "infra 不该参与 gating"
    assert g.detail.startswith("[infra]")
    assert g.score == 0.0


def test_quality_llm_explicit_pass_is_a_real_pass():
    # 模型如约只回一行「通过」= 合法的零硬伤,必须与解析失败区分开
    g = grade_quality_llm("正文", "设定", _FixedBackend("通过"))
    assert g.passed is True
    assert g.gating is True
    assert g.score == 1.0


def test_deslop_llm_unparsable_verdict_is_infra_not_pass():
    be = _FixedBackend("整体读下来还行，没什么大问题。")
    g = grade_deslop_llm("正文", "指纹", be)
    assert g.passed is False
    assert g.gating is False
    assert g.detail.startswith("[infra]")


def test_deslop_llm_explicit_pass_is_a_real_pass():
    g = grade_deslop_llm("正文", "指纹", _FixedBackend("通过"))
    assert g.passed is True and g.gating is True
