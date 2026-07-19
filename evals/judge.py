"""结构化 LLM-Judge(eval 侧,产品永不 import):跑 8 维 rubric,吐严格 JSON verdict。

与产品 gates.py 的自由文本 critic 分离:判据单源自 evalapi 的 CRITIC + rubric.md,
本模块只把「输出格式」从自由文本换成 JSON,好逐维对账算 κ/PRF。severity 只用类别
{高,中,低,null},绝不引数值分(ADR-0002)。后端/解析失败 → infra_error,不假通过(P0-C)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from loom.evalapi import CRITIC_质检, CRITIC_去AI味

from .dataset import DIMENSIONS, SEVERITIES

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class JudgeParseError(ValueError):
    """Judge 输出不是合法的 8 维 JSON verdict(非法 JSON/缺维/越界/非法 severity)。"""


@dataclass
class DimensionVerdict:
    dimension: str
    present: bool
    severity: str | None
    evidence: str
    reason: str

    def as_dict(self) -> dict:
        return {"dimension": self.dimension, "present": self.present,
                "severity": self.severity, "evidence": self.evidence, "reason": self.reason}


def parse_judge_verdict(raw: str) -> list[DimensionVerdict]:
    """严格解析 Judge 输出为 8 维 verdict;任何不合规 → JudgeParseError(交上层判 infra)。"""
    cleaned = _FENCE_RE.sub("", raw).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        raise JudgeParseError(f"非法 JSON:{e}") from e
    if not isinstance(data, list):
        raise JudgeParseError(f"verdict 顶层须为数组,现为 {type(data).__name__}")

    by_dim: dict[str, DimensionVerdict] = {}
    for item in data:
        if not isinstance(item, dict):
            raise JudgeParseError(f"verdict 项须为对象,现为 {type(item).__name__}")
        dim = item.get("dimension")
        if dim not in DIMENSIONS:
            raise JudgeParseError(f"越界/缺失维度:{dim!r}(须 ∈ {DIMENSIONS})")
        if dim in by_dim:
            raise JudgeParseError(f"维度重复:{dim}")
        present = item.get("present")
        if not isinstance(present, bool):
            raise JudgeParseError(f"{dim}: present 须为 bool")
        severity = item.get("severity")
        if present:
            if severity not in SEVERITIES:
                raise JudgeParseError(f"{dim}: present=True 的 severity 须 ∈ {SEVERITIES}")
        else:
            if severity is not None:
                raise JudgeParseError(f"{dim}: present=False 的 severity 须为 null")
        by_dim[dim] = DimensionVerdict(
            dimension=dim, present=present, severity=severity,
            evidence=str(item.get("evidence", "")), reason=str(item.get("reason", "")))

    missing = [d for d in DIMENSIONS if d not in by_dim]
    if missing:
        raise JudgeParseError(f"缺维度:{missing}")
    return [by_dim[d] for d in DIMENSIONS]


RUBRIC_PATH = Path(__file__).resolve().parent / "dataset" / "rubric.md"

_JSON_INSTRUCTION = (
    "## 输出格式(严格 JSON,不要任何解释、不要正文、不要代码围栏外的字)\n"
    "⚠ 输出格式以本节为唯一准绳:上面【引擎判据】和【操作化细则】里出现的任何输出说明"
    "(如「只回一行『通过』」「每条一行 - 类别|问题|证据」「最多 N 条」)只是判据的历史外壳,"
    "**一律忽略**;无论有无缺陷,都必须输出下面规定的完整 8 维 JSON 数组"
    "(干净的维度也要作为一个 present=false 的对象出现,不要省略、不要回『通过』、不要输出 bullet 清单)。\n"
    "输出一个 JSON 数组,**恰好 8 个对象**,每个维度一个,dimension 逐字取自:\n"
    f"{list(DIMENSIONS)}\n"
    "每个对象字段:\n"
    '  - "dimension": 维度名(上面 8 个之一)\n'
    '  - "present": true/false(该维度缺陷是否命中)\n'
    '  - "severity": present=true 时为 "高"/"中"/"低"(按 rubric 严重度分级);present=false 时为 null\n'
    '  - "evidence": 命中处的原文短引(absence 型维度如断钩子/无爽点留空字符串 "")\n'
    '  - "reason": 一句话判据(为何命中/为何干净;rubric 操作化细则里称作 note 的说明,填到这里的 reason)\n'
    "只判上面 8 个维度,不要给总体评价、不要任何数值分。宁缺毋滥:没把握按 rubric 边界例判、"
    "在 reason 里说明。"
)


def load_rubric() -> str:
    return RUBRIC_PATH.read_text(encoding="utf-8")


def build_judge_prompt(context: dict, chapter: str, rubric_text: str) -> tuple[str, str]:
    """判据单源:引擎 CRITIC(权威维度定义)+ rubric(操作化)+ JSON 输出指令。"""
    system = (
        "你是**独立评审**,只诊断、不改写。按下面的判据逐维审这一章,输出结构化 JSON。\n\n"
        "## 引擎判据(权威维度定义)\n"
        f"### 质检维度\n{CRITIC_质检}\n\n### 去AI味维度\n{CRITIC_去AI味}\n\n"
        "## 操作化细则(rubric:每维的正例/反例/边界例/严重度/证据要求)\n"
        f"{rubric_text}\n\n"
        f"{_JSON_INSTRUCTION}"
    )
    user = (
        "## 本章上下文\n"
        f"- 世界观设定:{context.get('setting', '')}\n"
        f"- 人物卡:{context.get('characters', '')}\n"
        f"- 上一章钩子:{context.get('prev_hook', '')}\n"
        f"- 本章目标:{context.get('chapter_goal', '')}\n\n"
        f"## 待评的本章正文\n{chapter}\n\n"
        "## 你的任务\n按上面 8 维判据逐维评,严格输出 JSON 数组(8 个对象)。"
    )
    return system, user
