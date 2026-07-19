"""结构化 LLM-Judge(eval 侧,产品永不 import):跑 8 维 rubric,吐严格 JSON verdict。

与产品 gates.py 的自由文本 critic 分离:判据单源自 evalapi 的 CRITIC + rubric.md,
本模块只把「输出格式」从自由文本换成 JSON,好逐维对账算 κ/PRF。severity 只用类别
{高,中,低,null},绝不引数值分(ADR-0002)。后端/解析失败 → infra_error,不假通过(P0-C)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

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
