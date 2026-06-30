"""harness:加载数据集 → 逐 case 跑 grader → 聚合 → 和基线比对(回归门禁)。

一个 case = 一个目录,含:
  case.json   —— 元信息 + 期望(必含/禁止项/AI腔阈值/长度容差/设定)
  chapter.md  —— 待评的章节文本(「被测系统」的产出:可以是固定 fixture,也可以是 `--generate` 现跑的)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .graders import (
    GraderResult,
    grade_aitell,
    grade_deslop_llm,
    grade_keywords,
    grade_length,
    grade_quality_llm,
)


@dataclass
class CaseResult:
    case_id: str
    title: str
    score: float
    passed: bool
    graders: list[GraderResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "title": self.title, "score": self.score,
                "passed": self.passed, "graders": [g.as_dict() for g in self.graders]}


def _weighted(graders: list[GraderResult]) -> float:
    wsum = sum(g.weight for g in graders) or 1.0
    return round(sum(g.score * g.weight for g in graders) / wsum, 3)


def run_case(case_dir: Path, *, backend=None, judge: bool = False) -> CaseResult:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    text = (case_dir / case.get("fixture", "chapter.md")).read_text(encoding="utf-8")
    exp = case.get("expect", {})

    graders = [
        grade_length(text, case.get("chapter_chars", 800), exp.get("len_tolerance", 0.5)),
        grade_aitell(text, case.get("fingerprint_anchors", []), exp.get("max_aitell_hits", 0)),
        grade_keywords(text, exp.get("must_include"), exp.get("must_not_include")),
    ]
    if judge and backend is not None:
        graders.append(grade_quality_llm(text, case.get("setting", ""), backend))
        graders.append(grade_deslop_llm(text, case.get("fingerprint", ""), backend))

    passed = all(g.passed for g in graders if g.gating)
    return CaseResult(case["id"], case.get("title", case["id"]), _weighted(graders), passed, graders)


def discover_cases(cases_dir: Path) -> list[Path]:
    return sorted(p.parent for p in cases_dir.glob("*/case.json"))


def run_suite(cases_dir: Path, *, backend=None, judge: bool = False) -> list[CaseResult]:
    return [run_case(d, backend=backend, judge=judge) for d in discover_cases(cases_dir)]


def aggregate(results: list[CaseResult]) -> dict:
    n = len(results) or 1
    passed = sum(1 for r in results if r.passed)
    per_grader: dict[str, list[float]] = {}
    for r in results:
        for g in r.graders:
            per_grader.setdefault(g.name, []).append(g.score)
    return {
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / n, 3),
        "mean_score": round(sum(r.score for r in results) / n, 3),
        "per_grader": {k: round(sum(v) / len(v), 3) for k, v in per_grader.items()},
    }


# ───────────────────────────── 回归门禁(和基线比对)─────────────────────────────

def save_baseline(path: Path, results: list[CaseResult]) -> None:
    payload = {"cases": {r.case_id: {"score": r.score, "passed": r.passed} for r in results},
               "summary": aggregate(results)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_baseline(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compare_to_baseline(results: list[CaseResult], baseline: dict, tol: float = 0.05) -> list[dict]:
    """返回回归项:某 case 在基线里通过、现在不通过,或分数比基线低超过 tol。"""
    base = baseline.get("cases", {})
    regressions: list[dict] = []
    for r in results:
        b = base.get(r.case_id)
        if not b:
            continue  # 新增 case,不算回归
        if b["passed"] and not r.passed:
            regressions.append({"case": r.case_id, "kind": "通过→失败",
                                "was": b["score"], "now": r.score})
        elif r.score + tol < b["score"]:
            regressions.append({"case": r.case_id, "kind": f"分数下滑 >{tol}",
                                "was": b["score"], "now": r.score})
    return regressions
