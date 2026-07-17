"""harness:加载数据集 → 逐 case 跑 grader → 聚合 → 和基线比对(回归门禁)。

一个 case = 一个目录,含:
  case.json   —— 元信息 + 期望(必含/禁止项/AI腔阈值/长度容差/设定)
  chapter.md  —— 待评的章节文本(「被测系统」的产出:可以是固定 fixture,也可以是 `--generate` 现跑的)

A/B 型 case(case.json 里 "type": "style_ab")则含:
  author_ref.md       —— 作者真稿样本(风格参照系)
  chapter_neutral.md  —— 同一章,「中性默认指纹」下的产出
  chapter_learned.md  —— 同一章,「学过作者手改的指纹」下的产出
断言学过版到真稿的风格距离显著更近(grade_style_ab)——「指纹在生效」的最小可证伪实验。
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
    grade_style_ab,
    grade_style_similarity,
)


@dataclass
class CaseResult:
    case_id: str
    title: str
    score: float
    passed: bool
    graders: list[GraderResult] = field(default_factory=list)
    case_type: str = "quality"        # "quality" | "detector_contract"
    contract_ok: bool = True          # detector_contract:声明必须命中缺陷的 grader 是否都如约失败

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "title": self.title, "score": self.score,
                "passed": self.passed, "case_type": self.case_type,
                "contract_ok": self.contract_ok, "graders": [g.as_dict() for g in self.graders]}


def _weighted(graders: list[GraderResult]) -> float:
    wsum = sum(g.weight for g in graders) or 1.0
    return round(sum(g.score * g.weight for g in graders) / wsum, 3)


def run_case(case_dir: Path, *, backend=None, judge: bool = False) -> CaseResult:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    exp = case.get("expect", {})

    if case.get("type") == "style_ab":
        return _run_style_ab_case(case_dir, case, exp)

    text = (case_dir / case.get("fixture", "chapter.md")).read_text(encoding="utf-8")

    graders = [
        grade_length(text, case.get("chapter_chars", 800), exp.get("len_tolerance", 0.5)),
        grade_aitell(text, case.get("fingerprint_anchors", []), exp.get("max_aitell_hits", 0)),
        grade_keywords(text, exp.get("must_include"), exp.get("must_not_include")),
    ]
    if "author_ref" in case:   # 可选:给普通 case 也挂风格相似观测(不给阈值就不 gating)
        ref = (case_dir / case["author_ref"]).read_text(encoding="utf-8")
        graders.append(grade_style_similarity(text, ref, exp.get("min_style_sim")))
    if judge and backend is not None:
        graders.append(grade_quality_llm(text, case.get("setting", ""), backend))
        graders.append(grade_deslop_llm(text, case.get("fingerprint", ""), backend))

    case_type = case.get("case_type", "quality")
    if case_type == "detector_contract":
        want_fail = set(case.get("expect_fail_graders", []))
        by_name = {g.name: g for g in graders}
        # 契约成立 = 每个声明必须命中缺陷的 grader 都存在且 passed=False
        contract_ok = bool(want_fail) and all(
            (name in by_name) and (by_name[name].passed is False) for name in want_fail)
        return CaseResult(case["id"], case.get("title", case["id"]), _weighted(graders),
                          contract_ok, graders, case_type=case_type, contract_ok=contract_ok)
    passed = all(g.passed for g in graders if g.gating)
    return CaseResult(case["id"], case.get("title", case["id"]), _weighted(graders),
                      passed, graders, case_type=case_type)


def _run_style_ab_case(case_dir: Path, case: dict, exp: dict) -> CaseResult:
    """A/B 型 case:同一章的「中性默认指纹」vs「学过的指纹」两份产出,比谁更接近作者真稿。
    gating 只看 A/B 差距;两份产出各自的相似度以 weight=0 挂着,只为看板可见。"""
    read = lambda key, default: (case_dir / case.get(key, default)).read_text(encoding="utf-8")  # noqa: E731
    ref = read("author_ref", "author_ref.md")
    neutral = read("fixture_neutral", "chapter_neutral.md")
    learned = read("fixture_learned", "chapter_learned.md")

    graders = [
        grade_style_similarity(neutral, ref, name="风格相似·中性指纹", weight=0.0, gating=False),
        grade_style_similarity(learned, ref, name="风格相似·学过指纹", weight=0.0, gating=False),
        grade_style_ab(neutral, learned, ref, exp.get("min_style_gap", 0.05)),
    ]
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
