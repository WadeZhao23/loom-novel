"""棒级体检项:给流水线每一棒的**中间产物**各挂一组确定性检查。

为什么要有它:章级总分只能告诉你「这章掉分了」,翻译不成「改哪一棒的 prompt」。
每一项都设计成「上游有、这一棒输出里没了」的**差分**,所以命中就能定位到棒。

红线:
- 全部确定性、零 LLM 调用——同一份文本跑两次结果必须逐字相同。
- 对 loom 的复用只走 loom.evalapi 门面,不 import 私有符号。
- 只活在 evals 里给开发者做回归归因,绝不进产品 UI/用户路径(ADR-0002)。
- 某棒缺席(WYSIWYG 旁路 / 断点续跑跳过)记 skipped,**不记 0 分**——旁路不是失败。
"""

from __future__ import annotations

import re

from loom.evalapi import (
    STEP_SHORT_BUDGETS,
    detect_aitell,
    parse_scene_budgets,
    scene_range,
    split_edit_note,
)

from .graders import GraderResult

_WS = re.compile(r"\s+")


def _chars(text: str) -> int:
    """去空白字数。与 graders._body_len 同口径,但中间产物没有 H1 标题,不必剥。"""
    return len(_WS.sub("", text or ""))


def skipped(step: str, item: str) -> GraderResult:
    """这一棒没有产物时的统一形状。

    passed=True 是刻意的:「这棒没跑」不该污染通过判定;gating=False 让它不进门禁;
    聚合侧按 detail 的 [skipped] 前缀把它排除出分布(不拉低中位数)。
    """
    return GraderResult(f"{step}·{item}", 0.0, True, weight=0.0, gating=False,
                        detail=f"[skipped] {step} 这一棒没有产物(旁路或续跑跳过)")


# ─────────────────────────────── 设定师 ───────────────────────────────

def grade_setter(anchor: str | None, hardfact_terms: list[str]) -> list[GraderResult]:
    """设定师产出「本章设定锚点」(≤350 字的语义选择)。

    体检两项:
    - 硬设定专名:case 声明必须带上的境界/金手指/地名等专名,锚点里在不在。
      锚点丢了专名,下游大纲师/写手就只能靠 hardfacts 直送兜底,是设定漂移的上游根因。
    - 锚点篇幅:超过 STEP_SHORT_BUDGETS["设定师"](350)说明它在复述整份世界观,
      会稀释下游 prompt。
    """
    if not anchor:
        return [skipped("设定师", "硬设定专名"), skipped("设定师", "锚点篇幅")]

    terms = hardfact_terms or []
    missing = [t for t in terms if t not in anchor]
    total = len(terms)
    score = 1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total)
    term_result = GraderResult(
        "设定师·硬设定专名", round(score, 3), not missing, weight=0.30,
        detail=f"声明 {total} 个硬设定专名,锚点缺 {len(missing)} 个",
        evidence=[f"锚点里没有:「{m}」" for m in missing])

    budget = STEP_SHORT_BUDGETS.get("设定师", 350)
    n = _chars(anchor)
    over = max(0, n - budget)
    len_result = GraderResult(
        "设定师·锚点篇幅", round(max(0.0, 1.0 - over / max(1, budget)), 3), over == 0,
        weight=0.10, detail=f"{n} 字(预算 {budget} 字)")
    return [term_result, len_result]


# ─────────────────────────────── 大纲师 ───────────────────────────────

def grade_outliner(outline: str | None, chapter_target: int,
                   must_include: list[str]) -> list[GraderResult]:
    """大纲师产出「本章场景骨头(分镜细纲)」。

    体检三项(全部复用产品自己的判据,不另立一套——重写必漂):
    - 必含要素:case 的 must_include 有没有在细纲这层就丢掉(丢在这里 = 写手根本没机会写)。
    - 场次数:落在 scene_range(chapter_target) 声明的区间内(evalapi 接缝,与喂 prompt
      的 _scene_budget 同源)。
    - 篇幅预算标注:每场标了「约X字」且各场合计与章目标偏差 ≤30%(与产品
      _check_scene_budget 的 0.3 阈值同口径)。
    """
    if outline is None:
        return [skipped("大纲师", "必含要素"), skipped("大纲师", "场次数"),
                skipped("大纲师", "篇幅预算")]

    must = must_include or []
    missing = [k for k in must if k not in outline]
    total = len(must)
    inc_score = 1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total)
    inc = GraderResult("大纲师·必含要素", round(inc_score, 3), not missing, weight=0.30,
                       detail=f"必含 {total} 项,细纲缺 {len(missing)} 项",
                       evidence=[f"细纲里没有:「{m}」" for m in missing])

    budgets = parse_scene_budgets(outline)
    lo, hi = scene_range(chapter_target)
    n_scenes = len(budgets)
    in_range = lo <= n_scenes <= hi
    cnt = GraderResult("大纲师·场次数", 1.0 if in_range else 0.0, in_range, weight=0.20,
                       detail=f"{n_scenes} 场(目标 {chapter_target} 字 → 应 {lo}-{hi} 场)")

    total_budget = sum(budgets)
    if not budgets:
        bud = GraderResult("大纲师·篇幅预算", 0.0, False, weight=0.15,
                           detail="各场都没标「约X字」,写手篇幅无锚")
    else:
        drift = abs(total_budget - chapter_target)
        ok = chapter_target <= 0 or drift <= chapter_target * 0.3
        bud = GraderResult("大纲师·篇幅预算",
                           round(max(0.0, 1.0 - drift / max(1, chapter_target)), 3), ok,
                           weight=0.15,
                           detail=f"各场合计约 {total_budget} 字(章目标 {chapter_target},容差 30%)")
    return [inc, cnt, bud]


# ──────────────────────────────── 写手 ────────────────────────────────

def grade_writer(draft: str | None, target_chars: int,
                 must_include: list[str], anchors: list[str]) -> list[GraderResult]:
    """写手产出「本章初稿」。这是第一份完整正文,建立后两棒的比较基准。

    体检三项:初稿篇幅 vs 章目标、必含要素命中、AI 翻转句命中数(初稿基线,
    供润色师那棒算「降了多少」)。
    """
    if draft is None:
        return [skipped("写手", "初稿篇幅"), skipped("写手", "必含要素"),
                skipped("写手", "AI翻转句")]

    n = _chars(draft)
    # 初稿容差刻意比终稿宽:后面还有编辑/润色两棒会动篇幅。只挡「离谱」。
    lo, hi = target_chars * 0.5, target_chars * 1.5
    len_ok = lo <= n <= hi
    d = 0.0 if len_ok else (lo - n if n < lo else n - hi)
    length = GraderResult("写手·初稿篇幅",
                          round(max(0.0, 1.0 - d / max(1, target_chars)), 3), len_ok,
                          weight=0.20, detail=f"{n} 字(章目标 {target_chars} ±50%)")

    must = must_include or []
    missing = [k for k in must if k not in draft]
    total = len(must)
    inc = GraderResult("写手·必含要素",
                       round(1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total), 3),
                       not missing, weight=0.30,
                       detail=f"必含 {total} 项,初稿缺 {len(missing)} 项",
                       evidence=[f"初稿里没有:「{m}」" for m in missing])

    hits = detect_aitell(draft, anchors or [])
    ai = GraderResult("写手·AI翻转句", round(1.0 / (1.0 + len(hits)), 3), True,
                      weight=0.0, gating=False,
                      detail=f"命中 {len(hits)} 处(初稿基线,供润色师那棒算降幅)",
                      evidence=[h.evidence for h in hits])
    return [length, inc, ai]


# ──────────────────────────────── 编辑 ────────────────────────────────

def grade_editor(edited: str | None, draft: str | None,
                 must_include: list[str]) -> list[GraderResult]:
    """编辑产出「本章改稿」+ 成对围栏的《本章改动留痕》。

    体检三项(全是 改稿 vs 初稿 的差分):
    - 留痕围栏:<LOOM:EDIT-NOTE> 与 </LOOM:EDIT-NOTE> 必须成对(未闭合会让留痕混进正文)。
    - 必含要素保持:**初稿有、改稿没了**才算编辑改丢的。初稿本来就缺的不赖它——
      归因必须指对棒,否则闭环会把作者引到错的地方。
    - 篇幅变化:编辑被明令「篇幅保持原稿量级、绝不扩写」,超出 ±30% 就是没守。
      算篇幅前先剥留痕围栏,否则留痕越长越显得「扩写」。
    """
    if edited is None or draft is None:
        return [skipped("编辑", "留痕围栏"), skipped("编辑", "必含要素保持"),
                skipped("编辑", "篇幅变化")]

    body, note = split_edit_note(edited)
    unclosed = "围栏未闭合" in note
    fence_ok = bool(note.strip()) and not unclosed
    fence = GraderResult("编辑·留痕围栏", 1.0 if fence_ok else 0.0, fence_ok, weight=0.15,
                         detail=("留痕围栏成对" if fence_ok
                                 else ("围栏未闭合" if unclosed else "没有《本章改动留痕》")))

    must = must_include or []
    dropped = [k for k in must if k in draft and k not in body]
    keep = GraderResult("编辑·必含要素保持",
                        round(1.0 if not must else max(0.0, 1.0 - len(dropped) / len(must)), 3),
                        not dropped, weight=0.35,
                        detail=f"初稿有而改稿没了的必含项:{len(dropped)} 个",
                        evidence=[f"编辑把「{k}」改丢了" for k in dropped])

    n_draft, n_edit = _chars(draft), _chars(body)
    ratio = n_edit / max(1, n_draft)
    size_ok = 0.7 <= ratio <= 1.3
    size = GraderResult("编辑·篇幅变化", round(min(1.0, 1.0 - abs(1.0 - ratio)), 3), size_ok,
                        weight=0.10,
                        detail=f"初稿 {n_draft} → 改稿 {n_edit} 字(×{ratio:.2f},应在 0.7~1.3)")
    return [fence, keep, size]


# ─────────────────────────────── 润色师 ───────────────────────────────

def grade_polisher(polished: str | None, edited: str | None,
                   anchors: list[str]) -> list[GraderResult]:
    """润色师产出「本章终稿」,职责是擦掉通用机器味、保住写作指纹。

    体检两项(全是 终稿 vs 改稿 的差分):
    - AI味下降:改稿里有 aitell 命中时,终稿必须**真的降下来**(after < before)——
      持平不算达标,「没降」就是这一棒白跑了(它的职责就是擦这个)。改稿本来就零命中
      时无处可降,终稿保持零即算达标。
    - 篇幅保持:被明令「绝不扩写」,同时也不该越擦越短。低于改稿 80% 就是擦过头。

    注:改稿带《本章改动留痕》围栏,算 AI 味与篇幅前必须先剥掉——留痕不是正文。
    """
    if polished is None or edited is None:
        return [skipped("润色师", "AI味下降"), skipped("润色师", "篇幅保持")]

    edited_body, _ = split_edit_note(edited)
    before = len(detect_aitell(edited_body, anchors or []))
    after = len(detect_aitell(polished, anchors or []))
    dropped = before - after
    # 改稿本来就零命中 → 终稿保持零即算达标(没有可降的);否则必须真降(严格 <),
    # 持平(after == before)算「没降」,不能放行——见 docstring。
    ai_ok = after < before if before > 0 else after == 0
    ai = GraderResult("润色师·AI味下降",
                      round(1.0 if before == 0 else max(0.0, dropped / before), 3), ai_ok,
                      weight=0.35,
                      detail=f"改稿 {before} 处 → 终稿 {after} 处(降 {dropped} 处)")

    n_edit, n_pol = _chars(edited_body), _chars(polished)
    ratio = n_pol / max(1, n_edit)
    size_ok = 0.8 <= ratio <= 1.2
    size = GraderResult("润色师·篇幅保持", round(min(1.0, 1.0 - abs(1.0 - ratio)), 3), size_ok,
                        weight=0.10,
                        detail=f"改稿 {n_edit} → 终稿 {n_pol} 字(×{ratio:.2f},应在 0.8~1.2)")
    return [ai, size]
