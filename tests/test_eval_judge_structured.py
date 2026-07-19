"""结构化 Judge:schema/严格解析/prompt/infra 三态。零真实模型。"""
import json

import pytest

from evals.dataset import DIMENSIONS
from evals.judge import DimensionVerdict, JudgeParseError, build_judge_prompt, load_rubric, parse_judge_verdict


def _full_verdict(**overrides):
    """8 维全 present=False 的合法 verdict JSON(可覆写个别维)。"""
    items = []
    for d in DIMENSIONS:
        item = {"dimension": d, "present": False, "severity": None, "evidence": "", "reason": "无"}
        if d in overrides:
            item.update(overrides[d])
        items.append(item)
    return json.dumps(items, ensure_ascii=False)


def test_parse_clean_verdict_all_absent():
    vs = parse_judge_verdict(_full_verdict())
    assert len(vs) == 8
    assert [v.dimension for v in vs] == list(DIMENSIONS)   # 按 DIMENSIONS 顺序
    assert all(v.present is False and v.severity is None for v in vs)


def test_parse_present_dimension():
    raw = _full_verdict(设定漂移={"present": True, "severity": "高",
                                  "evidence": "御空长剑", "reason": "违反无飞行铁律"})
    vs = {v.dimension: v for v in parse_judge_verdict(raw)}
    assert vs["设定漂移"].present is True and vs["设定漂移"].severity == "高"


def test_parse_tolerates_code_fence():
    raw = "```json\n" + _full_verdict() + "\n```"
    assert len(parse_judge_verdict(raw)) == 8       # 模型爱包围栏,得容忍


def test_malformed_json_raises():
    with pytest.raises(JudgeParseError):
        parse_judge_verdict("这不是 JSON,是自由文本「通过」")


def test_missing_dimension_raises():
    items = json.loads(_full_verdict())[:-1]        # 少一维
    with pytest.raises(JudgeParseError, match="缺"):
        parse_judge_verdict(json.dumps(items, ensure_ascii=False))


def test_unknown_dimension_raises():
    items = json.loads(_full_verdict())
    items[0]["dimension"] = "文学性"                # 越界维(rubric 外)
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(json.dumps(items, ensure_ascii=False))


def test_illegal_severity_raises():
    raw = _full_verdict(AI腔={"present": True, "severity": "致命", "evidence": "x", "reason": "y"})
    with pytest.raises(JudgeParseError, match="severity"):
        parse_judge_verdict(raw)


def test_present_false_with_severity_raises():
    raw = _full_verdict(断钩子={"present": False, "severity": "高"})
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(raw)


def test_dimension_verdict_as_dict_roundtrip():
    v = DimensionVerdict("AI腔", True, "低", "翻转句", "命中")
    assert v.as_dict() == {"dimension": "AI腔", "present": True, "severity": "低",
                           "evidence": "翻转句", "reason": "命中"}


def test_extra_unknown_dimension_beyond_full_set_raises():
    """8 维齐全(不触发缺维度兜底)+ 第 9 个越界维——只有越界维度守卫能拦。"""
    items = json.loads(_full_verdict())                 # 8 维合法
    items.append({"dimension": "文学性", "present": False, "severity": None,
                  "evidence": "", "reason": "越界"})     # 第9维越界
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(json.dumps(items, ensure_ascii=False))


def test_duplicate_dimension_raises():
    """8 唯一维 + 1 条重复维(内容矛盾)——删守卫会「后覆盖前」静默吞掉矛盾。"""
    items = json.loads(_full_verdict())                 # 8 唯一维
    dup = dict(items[0]); dup["present"] = True; dup["severity"] = "高"
    dup["evidence"] = "x"; dup["reason"] = "矛盾的重复维"
    items.append(dup)                                    # 第9项=第0维的矛盾重复
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(json.dumps(items, ensure_ascii=False))


def test_present_non_bool_raises():
    """present 非 bool 且取值 falsy(0)、severity 仍为 null——若走 present=False 分支的
    severity 检查(severity is None → 不拦),就不会被顺带拦住,只有 present-bool 守卫能拦。
    （注意不能用 "true" 这类真值字符串：它会让代码落入 present truthy 分支,
    被 severity not in SEVERITIES 的检查顺带拦下,测试就钉不住 present 守卫本身。）"""
    raw = _full_verdict(断钩子={"present": 0})           # 0 非 bool,且 falsy
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(raw)


def test_build_prompt_names_all_dimensions():
    ctx = {"setting": "无飞行铁律", "characters": "沈砚:寡言",
           "prev_hook": "提灯人喊破真名", "chapter_goal": "过磅"}
    system, user = build_judge_prompt(ctx, "正文内容", load_rubric())
    for d in DIMENSIONS:
        assert d in system                      # 8 维判据都在 system
    assert "JSON" in system or "json" in system  # 明确要求 JSON 输出
    assert "沈砚:寡言" in user and "正文内容" in user  # context+chapter 进 user


def test_build_prompt_carries_engine_critic_criteria():
    from loom.evalapi import CRITIC_质检, CRITIC_去AI味
    system, _ = build_judge_prompt({"setting": "s", "characters": "c",
                                    "prev_hook": "p", "chapter_goal": "g"}, "x", load_rubric())
    # 判据单源:引擎 CRITIC 原文必须嵌进 Judge system(不是另写一套)
    assert "信息边界" in CRITIC_质检 and "信息边界" in system
    assert "写作指纹" in CRITIC_去AI味 and "写作指纹" in system


def test_json_instruction_overrides_freetext_output():
    system, _ = build_judge_prompt({"setting": "s", "characters": "c",
                                    "prev_hook": "p", "chapter_goal": "g"}, "x", load_rubric())
    # 消歧:必须显式声明「忽略上面的自由文本输出说明」且「干净维度也要 present=false 对象」
    assert "忽略" in system
    assert "8 维" in system or "8维" in system or "完整" in system
    # 反向自证:CRITIC 的自由文本输出壳确实同时在 system 里(所以才需要消歧)
    assert "只回一行" in system or "每条一行" in system


def test_json_instruction_bridges_note_and_reason_field_names():
    system, _ = build_judge_prompt({"setting": "s", "characters": "c",
                                    "prev_hook": "p", "chapter_goal": "g"}, "x", load_rubric())
    # rubric 操作化细则全文用 note 指说明字段,JSON schema 用 reason——两者都须在 system 里,
    # 且 JSON 指令段须显式桥接,消除 note/reason 双名歧义。
    assert "note" in system and "reason" in system
    assert "note" in system.split("## 输出格式")[-1]  # 桥接语落在 JSON 指令段内,不是巧合命中


def test_build_prompt_no_numeric_score_language():
    system, _ = build_judge_prompt({"setting": "s", "characters": "c",
                                    "prev_hook": "p", "chapter_goal": "g"}, "x", load_rubric())
    # ADR-0002:不许诱导模型打「总体分」
    for banned in ("总体文学分", "综合评分", "打分", "评分(0", "score"):
        assert banned not in system
