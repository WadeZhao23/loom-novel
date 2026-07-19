"""结构化 Judge:schema/严格解析/prompt/infra 三态。零真实模型。"""
import json

import pytest

from evals.dataset import DIMENSIONS
from evals.judge import DimensionVerdict, JudgeParseError, parse_judge_verdict


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
