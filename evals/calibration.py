"""校准 meta-eval 纯函数:Cohen's κ + 每维 P/R/F1。零依赖手写(不引 sklearn)。

只算一致性/查全查准,不产任何「总体分」。11 例数据集每维正例仅 1-2 个,总体准确率
会被大量 absent 格灌水,故用 κ(扣偶然一致)+ 分维 recall(高代价维单独看)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def cohen_kappa(a: list, b: list) -> float:
    """两个等长标签序列的 Cohen's κ。完全一致→1.0;单一类别且一致→1.0。"""
    if len(a) != len(b):
        raise ValueError(f"κ 两序列须等长:{len(a)} != {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("κ 空序列无定义")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe >= 1.0:                       # 单一类别:两方都恒判同一类
        return 1.0 if po == 1.0 else 0.0
    return round((po - pe) / (1 - pe), 4)


@dataclass
class PRF:
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None

    def as_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": self.precision, "recall": self.recall, "f1": self.f1}


def prf_for_dimension(gold: list[bool], pred: list[bool]) -> PRF:
    """单维度跨 case 的 P/R/F1。分母为 0 的指标记 None(未定义,不伪造 0/1)。"""
    if len(gold) != len(pred):
        raise ValueError(f"P/R/F1 两序列须等长:{len(gold)} != {len(pred)}")
    tp = sum(1 for g, p in zip(gold, pred) if g and p)
    fp = sum(1 for g, p in zip(gold, pred) if (not g) and p)
    fn = sum(1 for g, p in zip(gold, pred) if g and (not p))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    precision = round(precision, 4) if precision is not None else None
    recall = round(recall, 4) if recall is not None else None
    return PRF(tp, fp, fn, precision, recall, f1)


TARGETS_PATH = Path(__file__).resolve().parent / "calibration" / "targets.json"


def load_targets() -> dict:
    return json.loads(TARGETS_PATH.read_text(encoding="utf-8"))


def evaluate_against_targets(metric_value: float | None, target: float) -> dict:
    """指标 vs 预注册阈值的纯比较。value=None(无数据)→ met=None(待测,非未达标)。"""
    met = None if metric_value is None else (metric_value >= target)
    return {"target": target, "value": metric_value, "met": met}
