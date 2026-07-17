"""Judge 校准数据集:schema 校验器。纯数据,零模型。"""
import json
from pathlib import Path

import pytest

from evals.dataset import (
    DIMENSIONS,
    DatasetError,
    SPLITS,
    discover_cases,
    load_case,
)


def _blank_labels(**overrides):
    """8 维全 present=False 的合法标注;overrides 按维度名替换单条。"""
    labels = [{"dimension": d, "present": False,
               "annotator": "构造注入(gold-by-construction)"} for d in DIMENSIONS]
    for dim, patch in overrides.items():
        for l in labels:
            if l["dimension"] == dim:
                l.update(patch)
    return labels


def _write_case(tmp_path, *, labels=None, split="dev", chapter="矿灯昏黄,沈砚验伤。他把旧矿牌收进怀里。"):
    d = tmp_path / "ds_x"; d.mkdir()
    case = {
        "id": "ds_x", "split": split, "version": 1,
        "source": {"origin": "constructed", "license": "self-authored", "deidentified": True},
        "context": {"setting": "灵气复苏,逆息体质忌讳外泄。", "characters": "沈砚:寡言,谋定后动。",
                    "prev_hook": "上一章末:矿道尽头传来提灯脚步声。", "chapter_goal": "接钩+验伤+埋矿牌线。"},
        "labels": labels if labels is not None else _blank_labels(),
    }
    (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "chapter.md").write_text(chapter, encoding="utf-8")
    return d


def test_dimensions_are_the_eight_judge_dims():
    assert DIMENSIONS == ("人物OOC", "设定漂移", "断钩子", "无爽点",
                          "信息边界", "物品状态连续性", "时间连续性", "AI腔")
    assert SPLITS == ("dev", "calibration", "holdout")


def test_clean_case_loads(tmp_path):
    case = load_case(_write_case(tmp_path))
    assert case["id"] == "ds_x" and len(case["labels"]) == 8


def test_missing_dimension_rejected(tmp_path):
    labels = _blank_labels()[:-1]                      # 只 7 条 → 维度不全
    with pytest.raises(DatasetError, match="维度"):
        load_case(_write_case(tmp_path, labels=labels))


def test_chapter_evidence_must_be_substring(tmp_path):
    labels = _blank_labels(设定漂移={"present": True, "severity": "高",
                                    "evidence_type": "chapter", "evidence": "正文里根本没有这句",
                                    "note": "注入:境界名写错"})
    with pytest.raises(DatasetError, match="子串"):
        load_case(_write_case(tmp_path, labels=labels))


def test_absence_evidence_must_be_empty(tmp_path):
    labels = _blank_labels(断钩子={"present": True, "severity": "高",
                                  "evidence_type": "absence", "evidence": "不该有引文",
                                  "note": "注入:通章不接提灯脚步声的钩"})
    with pytest.raises(DatasetError, match="absence"):
        load_case(_write_case(tmp_path, labels=labels))


def test_valid_positive_case_loads(tmp_path):
    labels = _blank_labels(设定漂移={"present": True, "severity": "高",
                                    "evidence_type": "chapter", "evidence": "旧矿牌",
                                    "note": "示例:以子串核验通过为准"})
    case = load_case(_write_case(tmp_path, labels=labels))
    hit = [l for l in case["labels"] if l["present"]]
    assert len(hit) == 1 and hit[0]["dimension"] == "设定漂移"


def test_bad_split_rejected(tmp_path):
    with pytest.raises(DatasetError, match="split"):
        load_case(_write_case(tmp_path, split="test"))


def test_clean_label_must_not_carry_severity(tmp_path):
    labels = _blank_labels(时间连续性={"present": False, "severity": "低",
                                      "annotator": "构造注入(gold-by-construction)"})
    with pytest.raises(DatasetError, match="present=False"):
        load_case(_write_case(tmp_path, labels=labels))
