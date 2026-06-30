"""一组 grader:每个把一章文本评成一条 GraderResult(0~1 分 + 通过与否 + 证据)。

两类:
- **确定性 grader**(离线、不花钱、毫秒级):长度、AI 腔(复用 loom.aitell)、关键要素(必含/禁止项)。
- **LLM-judge grader**(需后端):复用 loom.gates 的复审 critic(CRITIC_质检 / CRITIC_去AI味)。

loom.* 任一不可用时,grader 优雅降级为「跳过」(score=0、gating=False、不拖垮整跑)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class GraderResult:
    name: str
    score: float            # 0~1,1 最好
    passed: bool            # 是否达标
    weight: float = 1.0     # 聚合权重
    gating: bool = True      # 是否计入「本例通过」判定(LLM grader 关闭时为非 gating)
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name, "score": self.score, "passed": self.passed,
            "weight": self.weight, "gating": self.gating, "detail": self.detail,
            "evidence": self.evidence,
        }


_H1 = re.compile(r"^\s*#\s+.*\n")


def _body_len(text: str) -> int:
    """正文字数(去掉首行 H1 标题、去空白)。与 loom 同口径:标题不算正文。"""
    body = _H1.sub("", text, count=1)
    return len(re.sub(r"\s+", "", body))


# ───────────────────────────── 确定性 grader ─────────────────────────────

def grade_length(text: str, target_chars: int, tol: float = 0.5, weight: float = 0.15) -> GraderResult:
    n = _body_len(text)
    lo, hi = target_chars * (1 - tol), target_chars * (1 + tol)
    ok = lo <= n <= hi
    if ok:
        score = 1.0
    else:
        d = (lo - n) if n < lo else (n - hi)
        score = max(0.0, 1.0 - d / max(1, target_chars))
    return GraderResult("长度达标", round(score, 3), ok, weight,
                        detail=f"{n} 字(目标 {target_chars} ±{int(tol * 100)}%)")


def grade_aitell(text: str, anchors: list[str] | None = None,
                 max_hits: int = 0, weight: float = 0.30) -> GraderResult:
    """复用 loom.aitell.detect:数「不是A而是B」这类 AI 翻转句。命中越少越好。"""
    try:
        from loom.aitell import detect
    except Exception as e:  # noqa: BLE001 — loom 不可用时降级跳过
        return GraderResult("去AI味·确定性", 0.0, True, weight, gating=False,
                            detail=f"(跳过:loom.aitell 不可用 — {e})")
    hits = detect(text, anchors or [])
    n = len(hits)
    return GraderResult("去AI味·确定性", round(1.0 / (1.0 + n), 3), n <= max_hits, weight,
                        detail=f"命中 {n} 处 AI 对比句式(阈值 ≤{max_hits})",
                        evidence=[h.evidence for h in hits])


def grade_keywords(text: str, must_include: list[str] | None,
                   must_not_include: list[str] | None, weight: float = 0.25) -> GraderResult:
    """关键要素:必含项缺失 = 漏写;禁止项命中 = 设定漂移(如等级名/地名写错)。"""
    must_include = must_include or []
    must_not_include = must_not_include or []
    missing = [k for k in must_include if k not in text]
    leaked = [k for k in must_not_include if k in text]
    total = len(must_include) + len(must_not_include)
    bad = len(missing) + len(leaked)
    score = 1.0 if total == 0 else max(0.0, 1.0 - bad / total)
    ev = [f"缺少必含:「{m}」" for m in missing] + [f"出现禁止项(设定漂移):「{l}」" for l in leaked]
    return GraderResult("关键要素", round(score, 3), not missing and not leaked, weight,
                        detail=f"必含缺 {len(missing)} / 禁止项命中 {len(leaked)}", evidence=ev)


# ───────────────────────────── LLM-judge grader ─────────────────────────────

def grade_quality_llm(text: str, setting: str, backend, weight: float = 0.20) -> GraderResult:
    """复用 loom.gates 的「质检」复审 critic 当 LLM-judge:挑 OOC / 设定漂移 / 断钩子 / 无爽点 / 信息越界。"""
    try:
        from loom.gates import CRITIC_质检, _parse_verdict
    except Exception as e:  # noqa: BLE001
        return GraderResult("质检·LLM", 0.0, True, weight, gating=False, detail=f"(跳过 — {e})")
    user = (f"## 设定与标准\n{setting}\n\n## 待复审的本章稿\n{text}\n\n"
            "## 你的任务\n按上面的标准,只挑硬伤、给证据,严格按格式输出;无硬伤只回一行「通过」。")
    try:
        verdict = backend.complete(CRITIC_质检, user, max_chars=600)
    except Exception as e:  # noqa: BLE001 — 后端报错不拖垮整跑
        return GraderResult("质检·LLM", 0.0, True, weight, gating=False, detail=f"(后端调用失败 — {e})")
    issues = _parse_verdict(verdict)
    n = len(issues)
    return GraderResult("质检·LLM", round(1.0 / (1.0 + n), 3), n == 0, weight,
                        detail=f"复审挑出 {n} 处硬伤",
                        evidence=[f"{i.kind}:{i.desc}" for i in issues])


def grade_deslop_llm(text: str, fingerprint: str, backend, weight: float = 0.10) -> GraderResult:
    """复用「去AI味」复审 critic:LLM 视角下的 AI 腔命中(与确定性 aitell 互补)。"""
    try:
        from loom.gates import CRITIC_去AI味, _parse_verdict
    except Exception as e:  # noqa: BLE001
        return GraderResult("去AI味·LLM", 0.0, True, weight, gating=False, detail=f"(跳过 — {e})")
    user = (f"## 写作指纹(命中前先看这个豁免作者签名句)\n{fingerprint}\n\n## 待审读的本章终稿\n{text}\n\n"
            "## 你的任务\n按《去AI味》黑名单挑具体命中,严格按格式输出;无命中只回一行「通过」。")
    try:
        verdict = backend.complete(CRITIC_去AI味, user, max_chars=600)
    except Exception as e:  # noqa: BLE001
        return GraderResult("去AI味·LLM", 0.0, True, weight, gating=False, detail=f"(后端调用失败 — {e})")
    issues = _parse_verdict(verdict)
    n = len(issues)
    return GraderResult("去AI味·LLM", round(1.0 / (1.0 + n), 3), n == 0, weight,
                        detail=f"复审命中 {n} 处 AI 腔",
                        evidence=[f"{i.kind}:{i.desc}" for i in issues])
