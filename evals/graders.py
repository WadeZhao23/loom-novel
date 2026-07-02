"""一组 grader:每个把一章文本评成一条 GraderResult(0~1 分 + 通过与否 + 证据)。

两类:
- **确定性 grader**(离线、不花钱、毫秒级):长度、AI 腔(复用 loom.aitell)、关键要素(必含/禁止项)、
  风格相似度(生成稿 vs 作者真稿的纯字符串统计距离,「越写越像你」的回归度量)。
- **LLM-judge grader**(需后端):复用 loom.gates 的复审 critic(CRITIC_质检 / CRITIC_去AI味)。

loom.* 任一不可用时,grader 优雅降级为「跳过」(score=0、gating=False、不拖垮整跑)。
"""

from __future__ import annotations

import math
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


# ──────────────────── 确定性 grader:风格相似度(「越写越像你」)────────────────────
# 生成稿 vs 作者真稿样本,四个纯字符串统计特征各算一个 0~1 相似度再取均值;零依赖、不发网。
# 只活在 evals 里给开发者做回归比对,绝不进产品 UI/用户路径——ADR-0002「不量化不上报」
# 约束的是产品给用户打分,这里评的是引擎版本。

_PUNCTS = "。,、!?…:;“”——,!?:;"               # 标点频率向量的固定维度
_LEN_BINS = (4, 8, 12, 18, 26, 40)              # 句长分桶边界(字),末桶 40+

# 虚词/常见腔调副词的固定清单(频率向量维度)。多字词在前是刻意的:count 按子串数,
# 「仿佛/缓缓/瞬间」这类 AI 默认腔高频词与「的/地/得」的相对用量,是最便宜的嗓音信号。
_FUNC_WORDS = (
    "仿佛 忽然 已经 只是 不过 然而 甚至 几乎 依然 好像 似乎 或许 于是 突然 渐渐 慢慢 终于 竟然 "
    "一直 立刻 顿时 瞬间 缓缓 悄悄 轻轻 微微 隐隐 不由 如同 死死 "
    "的 了 着 是 就 都 又 才 还 也 很 被 把 让 给 对 向 往 从 和 跟 与 但 却 而 般 地 得 呢 吗 吧 啊"
).split()


def _sentences(text: str) -> list[str]:
    """句切:直接复用 loom.fingerprint._segment(引号感知版),与 learn 的对齐口径一致;
    loom 不可用时退化到裸句末切分(grader 只观测,不因缺 loom 崩掉整跑)。"""
    body = _H1.sub("", text, count=1)
    try:
        from loom.fingerprint import _segment
        return _segment(body)
    except Exception:
        return [s.strip() for s in re.split(r"(?<=[。!?!?…\n])", body) if s.strip()]


def _len_dist(sents: list[str]) -> list[float]:
    counts = [1.0] * (len(_LEN_BINS) + 1)        # +1 拉普拉斯平滑,避免空桶
    for s in sents:
        n = len(re.sub(r"\s+", "", s))
        counts[sum(1 for b in _LEN_BINS if n > b)] += 1
    total = sum(counts)
    return [c / total for c in counts]


def _js_similarity(p: list[float], q: list[float]) -> float:
    """1 − JS散度/ln2:对称、有界 [0,1],比裸 KL 经得起零桶。"""
    def kl(a: list[float], b: list[float]) -> float:
        return sum(x * math.log(x / y) for x, y in zip(a, b) if x > 0)
    m = [(x + y) / 2 for x, y in zip(p, q)]
    return max(0.0, 1.0 - (kl(p, m) + kl(q, m)) / 2 / math.log(2))


def _cosine(u: list[float], v: list[float]) -> float:
    dot = sum(a * b for a, b in zip(u, v))
    nu, nv = math.sqrt(sum(a * a for a in u)), math.sqrt(sum(b * b for b in v))
    return dot / (nu * nv) if nu and nv else 0.0


def _char_bigrams(text: str) -> set[str]:
    han = re.sub(r"[^一-鿿]", "", text)   # 只留汉字:标点已有专门维度
    return {han[i:i + 2] for i in range(len(han) - 1)}


def _avg_len(sents: list[str]) -> float:
    if not sents:
        return 0.0
    return sum(len(re.sub(r"\s+", "", s)) for s in sents) / len(sents)


def style_metrics(gen: str, ref: str) -> dict[str, float]:
    """四个 0~1 相似度 + 「综合」均值。gen=生成稿,ref=作者真稿样本(多段拼成一份)。"""
    gs, rs = _sentences(gen), _sentences(ref)
    a, b = _char_bigrams(gen), _char_bigrams(ref)
    m = {
        "句长分布": _js_similarity(_len_dist(gs), _len_dist(rs)),
        "标点频率": _cosine([gen.count(c) for c in _PUNCTS], [ref.count(c) for c in _PUNCTS]),
        "虚词频率": _cosine([gen.count(w) for w in _FUNC_WORDS], [ref.count(w) for w in _FUNC_WORDS]),
        "bigram重合": len(a & b) / len(a | b) if (a or b) else 0.0,
        "_平均句长差": abs(_avg_len(gs) - _avg_len(rs)),   # 只进 detail,不进综合
    }
    m["综合"] = round(sum(v for k, v in m.items() if not k.startswith("_")) / 4, 4)
    return m


def grade_style_similarity(text: str, author_ref: str, min_sim: float | None = None,
                           weight: float = 0.2, name: str = "风格相似·像你",
                           gating: bool | None = None) -> GraderResult:
    """风格相似度(0~1,越高越像作者真稿)。不给 min_sim 时只观测、不 gating。"""
    m = style_metrics(text, author_ref)
    sim = m["综合"]
    passed = True if min_sim is None else sim >= min_sim
    detail = (f"综合 {sim:.3f}" + (f"(阈值 ≥{min_sim})" if min_sim is not None else "")
              + " — " + " / ".join(f"{k} {v:.2f}" for k, v in m.items()
                                   if k != "综合" and not k.startswith("_"))
              + f" / 平均句长差 {m['_平均句长差']:.1f} 字")
    return GraderResult(name, round(sim, 3), passed, weight,
                        gating=(min_sim is not None) if gating is None else gating,
                        detail=detail)


def grade_style_ab(text_neutral: str, text_learned: str, author_ref: str,
                   min_gap: float = 0.05, weight: float = 1.0) -> GraderResult:
    """「指纹在生效」的最小可证伪实验:同一章,学过指纹的产出须比中性指纹的
    更接近作者真稿(综合相似度差 ≥ min_gap)。score 把差距归一到 0~1:
    差距=阈值 → 0.5,≥2×阈值 → 1.0,便于进基线做回归比对。"""
    mn, ml = style_metrics(text_neutral, author_ref), style_metrics(text_learned, author_ref)
    gap = ml["综合"] - mn["综合"]
    if min_gap > 0:
        score = max(0.0, min(1.0, gap / (2 * min_gap)))
    else:
        score = 1.0 if gap > 0 else 0.0
    ev = [f"{k}:中性 {mn[k]:.2f} → 学过 {ml[k]:.2f}(Δ{ml[k] - mn[k]:+.2f})"
          for k in ("句长分布", "标点频率", "虚词频率", "bigram重合")]
    return GraderResult("指纹生效·A/B", round(score, 3), gap >= min_gap, weight,
                        detail=(f"到真稿相似度:中性 {mn['综合']:.3f} → 学过 {ml['综合']:.3f}"
                                f"(Δ{gap:+.3f},阈值 ≥{min_gap})"),
                        evidence=ev)


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
