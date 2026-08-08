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
    assert g.score == 0.0


def test_deslop_llm_explicit_pass_is_a_real_pass():
    g = grade_deslop_llm("正文", "指纹", _FixedBackend("通过"))
    assert g.passed is True and g.gating is True


# ── 回归:「通过」不能用子串匹配判定(未通过/不通过 都*包含*「通过」二字)──────────
# review 发现的洞:旧判据 `"通过" not in verdict` 是子串检查,「本章未通过质检」这类明确的
# 否定判词会被误判成合法零硬伤直接放行——同一条 fail-open 故障线,且更隐蔽(负面判词被当通过)。


def test_quality_llm_negated_pass_verdict_is_infra_not_pass():
    # 复现 review 给的例子:模型明确说"没通过",但格式跑偏(没有 `- ` 条目行),
    # parse_critic_verdict 抓不到任何硬伤,n_issues==0。子串判据会被"未通过"里的"通过"骗过。
    verdict = "本章未通过质检，人物表现有问题，建议重写。"
    g = grade_quality_llm("正文", "设定", _FixedBackend(verdict))
    assert g.passed is False, "模型明确说没通过,不能判定为通过"
    assert g.gating is False
    assert g.detail.startswith("[infra]")
    assert g.score == 0.0


def test_quality_llm_bare_negation_is_infra_not_pass():
    g = grade_quality_llm("正文", "设定", _FixedBackend("不通过"))
    assert g.passed is False
    assert g.gating is False
    assert g.detail.startswith("[infra]")
    assert g.score == 0.0


def test_quality_llm_trailing_punctuation_pass_is_a_real_pass():
    # 「通过」带尾部标点仍是合法通过(必须和 parse_verdict 的 rstrip 口径一致)
    g = grade_quality_llm("正文", "设定", _FixedBackend("通过。"))
    assert g.passed is True
    assert g.gating is True
    assert g.score == 1.0


def test_quality_llm_bulleted_pass_is_a_real_pass():
    # 「- 通过」带项目符号仍是合法通过
    g = grade_quality_llm("正文", "设定", _FixedBackend("- 通过"))
    assert g.passed is True
    assert g.gating is True
    assert g.score == 1.0


def test_quality_llm_issue_containing_pass_word_is_normal_scored_path():
    # 硬伤条目自己的文本里出现「通过」两字(如"设定说他要先通过考验")不该被误判成通过或 infra——
    # 走的是正常的按条打分路径(n_issues==1)。
    verdict = '- 人物OOC | 设定说他要先通过考验才能觉醒 | 证据:"他直接觉醒了"'
    g = grade_quality_llm("正文", "设定", _FixedBackend(verdict))
    assert not g.detail.startswith("[infra]")
    assert g.passed is False
    assert g.score == 0.5
    assert len(g.evidence) == 1


def test_deslop_llm_negated_pass_verdict_is_infra_not_pass():
    # 同一 helper(_verdict_is_unparsable)同时喂给 quality 和 deslop 两个 grader,
    # 回归不能只钉一处——两个消费者都要证明"未通过"不会被误判成通过。
    verdict = "本章未通过质检，人物表现有问题，建议重写。"
    g = grade_deslop_llm("正文", "指纹", _FixedBackend(verdict))
    assert g.passed is False
    assert g.gating is False
    assert g.detail.startswith("[infra]")
    assert g.score == 0.0
