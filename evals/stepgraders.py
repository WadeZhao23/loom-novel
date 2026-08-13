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
    outline_budget,
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
    detail 带 [skipped] 前缀。

    聚合侧(evals/aggregate.py)按 detail 的 **[skipped] 或 [not-measurable]**(后者见
    下面 not_measurable())前缀识别"genuinely 没测到"、排除出分布——不是靠
    gating=False 本身。gating=False 还覆盖 observe-only 项(如 写手·AI翻转句:
    weight=0.0、gating=False,但每次都真测了),那类项必须留在分布里,否则真实
    信号会被误报成"从未测过"(Important-1)。
    """
    return GraderResult(f"{step}·{item}", 0.0, True, weight=0.0, gating=False,
                        detail=f"[skipped] {step} 这一棒没有产物(旁路或续跑跳过)")


def not_measurable(name: str, reason: str) -> GraderResult:
    """某体检项本次结构性测不出(不是「没跑」,是这个信号在当前输入下不适用)。

    与 skipped() 并列的第二种「没测到」——三处调用方(大纲师·场次数无标注时、
    大纲师·篇幅预算 chapter_target<=0 时、编辑·留痕围栏恒不可测)原先各自手写同一份
    weight=0.0/gating=False/passed=True/[not-measurable] 前缀,收进这个小helper 防
    第三处再手抄一遍漂掉某个字段。

    passed=True 是刻意的:「测不出」不该判定失败;weight=0.0/gating=False 让它不进
    门禁;detail 统一带 [not-measurable] 前缀,供 evals/aggregate.py 据此排除出分布
    (同 skipped() 的排除机制,见其 docstring)。
    """
    return GraderResult(name, 0.0, True, weight=0.0, gating=False,
                        detail=f"[not-measurable] {reason}")


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




def _toward_target(name: str, n_before: int, n_after: int, chapter_target: int,
                   *, weight: float, label_before: str, label_after: str) -> GraderResult:
    """按【离章目标更近还是更远】评分,而不是【长度变没变】。

    真事故(2026-08-12):旧口径是 1-|1-ratio|,即「这一棒不该改长度」。但产品在
    _length_hint 里明确给编辑/润色师**压缩授权**——「原稿明显超目标就顺手压回来」。
    两者正面冲突:一次让终稿距目标偏差从 0.236 降到 0.142(客观变好)的改动,
    被旧口径判成「润色师·篇幅保持 回归」(p=0.0247)。判据在惩罚产品刻意要的行为。

    新口径只问一件事:这一棒把稿子推向目标了,还是推离了?
    - passed:没推离(容 0.02 噪声),或推完之后本来就落在容差带内
    - score:按推完之后离目标多远算(越近越高)——仍然扣得动「已经达标还乱压」

    chapter_target<=0 时无从判断,记不可测(不伪造分数)。
    """
    if chapter_target <= 0:
        return not_measurable(name, f"章目标 {chapter_target} 非正数,无从判断离目标更近还是更远")
    dev_before = abs(n_before - chapter_target) / chapter_target
    dev_after = abs(n_after - chapter_target) / chapter_target
    # 与 gen case 的 len_tolerance 封顶同口径:落在 ±25% 内就算达标,不管它动没动
    ok = dev_after <= dev_before + 0.02 or dev_after <= 0.25
    arrow = "更近" if dev_after < dev_before else ("更远" if dev_after > dev_before else "持平")
    return GraderResult(
        name, round(max(0.0, min(1.0, 1.0 - dev_after)), 3), ok, weight=weight,
        detail=(f"{label_before} {n_before} → {label_after} {n_after} 字"
                f"(目标 {chapter_target};离目标 {dev_before:.0%}→{dev_after:.0%},{arrow})"))


# ─────────────────────────────── 大纲师 ───────────────────────────────

def grade_outliner(outline: str | None, chapter_target: int,
                   must_include: list[str]) -> list[GraderResult]:
    """大纲师产出「本章场景骨头(分镜细纲)」。

    体检三项(全部复用产品自己的判据,不另立一套——重写必漂):
    - 必含要素:case 的 must_include 有没有在细纲这层就丢掉(丢在这里 = 写手根本没机会写)。
    - 场次数:落在 scene_range(chapter_target) 声明的区间内(evalapi 接缝,与喂 prompt
      的 _scene_budget 同源)。parse_scene_budgets 数的是「约X字」标注数,不是场景数——
      细纲完全没标注时这个信号测不出场景数(不能报「0 场」,那是假数据),记不可测;
      「没标」这个缺陷交给下面的篇幅预算项单独抓,不在这里重复计。
    - 篇幅预算标注:每场标了「约X字」且各场合计与章目标偏差 ≤30%(与产品
      _check_scene_budget 的 0.3 阈值同口径)。chapter_target<=0 时偏差率没有意义,
      这项检查本身不适用,记不可测(不伪造分数,也不让 passed/score 互相矛盾)。
    """
    if outline is None:
        return [skipped("大纲师", "细纲篇幅"),
                skipped("大纲师", "必含要素"), skipped("大纲师", "场次数"),
                skipped("大纲师", "篇幅预算")]

    must = must_include or []
    missing = [k for k in must if k not in outline]
    total = len(must)
    inc_score = 1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total)
    inc = GraderResult("大纲师·必含要素", round(inc_score, 3), not missing, weight=0.30,
                       detail=f"必含 {total} 项,细纲缺 {len(missing)} 项",
                       evidence=[f"细纲里没有:「{m}」" for m in missing])

    budgets = parse_scene_budgets(outline)
    if not budgets:
        # 没有「约X字」标注 → 数不出场景数(parse_scene_budgets 抓的是标注,不是场景标题)。
        # 报「0 场」会把「没标」这个缺陷在这里和下面的篇幅预算项重复计一遍,还给出假数据。
        cnt = not_measurable(
            "大纲师·场次数",
            "细纲没有「约X字」标注,场次数无法从这个信号测出(该缺陷已由"
            "「大纲师·篇幅预算」的「没标」记录,这里不重复计)")
    else:
        lo, hi = scene_range(chapter_target)
        n_scenes = len(budgets)
        in_range = lo <= n_scenes <= hi
        cnt = GraderResult("大纲师·场次数", 1.0 if in_range else 0.0, in_range, weight=0.20,
                           detail=f"{n_scenes} 场(目标 {chapter_target} 字 → 应 {lo}-{hi} 场)")

    total_budget = sum(budgets)
    if not budgets:
        bud = GraderResult("大纲师·篇幅预算", 0.0, False, weight=0.15,
                           detail="各场都没标「约X字」,写手篇幅无锚")
    elif chapter_target <= 0:
        # 章目标非正数 → 偏差率(drift / chapter_target)没有意义,这项检查不适用。
        # 不能一边 passed=True 一边 score=0.0——不适用就不计分、不进门禁,别伪造数字。
        bud = not_measurable(
            "大纲师·篇幅预算",
            f"章目标 {chapter_target} 非正数,篇幅预算检查不适用(各场合计约 {total_budget} 字)")
    else:
        drift = abs(total_budget - chapter_target)
        ok = drift <= chapter_target * 0.3
        bud = GraderResult("大纲师·篇幅预算",
                           round(max(0.0, 1.0 - drift / chapter_target), 3), ok,
                           weight=0.15,
                           detail=f"各场合计约 {total_budget} 字(章目标 {chapter_target},容差 30%)")
    # 细纲自身篇幅:上限按章目标现算(outline_budget,evalapi 接缝),不是写死的 450。
    # 这一项此前【不存在】——旧的 450 既没 grader 也没 warn 覆盖,改成多少都没有信号
    # 告诉你它对不对,于是 20/20 越线也没人发现(spec §10.4)。
    obudget = outline_budget(chapter_target) if chapter_target > 0 else 0
    if obudget <= 0:
        olen = not_measurable("大纲师·细纲篇幅",
                              "章目标字数 ≤0,细纲上限按它派生,这项无从算起")
    else:
        n = _chars(outline)
        over = max(0, n - obudget)
        olen = GraderResult(
            "大纲师·细纲篇幅", round(max(0.0, 1.0 - over / max(1, obudget)), 3), over == 0,
            weight=0.10, detail=f"{n} 字(上限 {obudget} 字,按 {chapter_target} 字章目标现算)")
    return [olen, inc, cnt, bud]


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
                 must_include: list[str],
                 chapter_target: int) -> list[GraderResult]:
    """编辑产出「本章改稿」;controller 在落 ledger 前会把《本章改动留痕》切出另存到
    .审稿留痕/(loom/agents.py:682-685 `_split_edit_note`),只把干净正文交给下游润色师
    并写进 ledger。所以这里收到的 `edited` 就是 evals.generate.collect_steps 从 ledger
    读出来的那份干净正文——从来不带留痕围栏。

    体检三项(全是 改稿 vs 初稿 的差分):
    - 留痕围栏:**不可测**,标记 [not-measurable]。真实跑必定测不出——不是编辑没写
      留痕,是这份信号在到达 ledger 之前就已经被 controller 剥走了(见上)。
      千万别把它"修回"成真检查:那样每次真实跑都会假失败(围栏在 ledger 里恒为空),
      污染「最弱棒」归因,违反本模块「不造数」的红线。想恢复真覆盖需要新开一个
      loom/evalapi.py 门面去读 .审稿留痕/ 目录,不在这个函数的范围内。
    - 必含要素保持:**初稿有、改稿没了**才算编辑改丢的。初稿本来就缺的不赖它——
      归因必须指对棒,否则闭环会把作者引到错的地方。
    - 篇幅变化:编辑被明令「篇幅保持原稿量级、绝不扩写」,超出 ±30% 就是没守。
      算篇幅前先过一遍 split_edit_note 剥留痕围栏——对真实 ledger 内容是 no-op
      (反正从来没有围栏),但万一未来上游行为变化,这层剥离仍是正确的防线。
    """
    if edited is None or draft is None:
        return [skipped("编辑", "留痕围栏"), skipped("编辑", "必含要素保持"),
                skipped("编辑", "篇幅变化")]

    body, _note = split_edit_note(edited)
    fence = not_measurable(
        "编辑·留痕围栏",
        "留痕围栏在进 ledger 前已被 controller 剥离(loom/agents.py:682-685 "
        "_split_edit_note 把《本章改动留痕》切出另存到 .审稿留痕/,只把干净正文交给"
        "下游润色师并落盘 ledger),这项体检从 ledger 读到的编辑产出永远不含围栏,"
        "测不出来不代表编辑没写留痕")

    must = must_include or []
    dropped = [k for k in must if k in draft and k not in body]
    keep = GraderResult("编辑·必含要素保持",
                        round(1.0 if not must else max(0.0, 1.0 - len(dropped) / len(must)), 3),
                        not dropped, weight=0.35,
                        detail=f"初稿有而改稿没了的必含项:{len(dropped)} 个",
                        evidence=[f"编辑把「{k}」改丢了" for k in dropped])

    size = _toward_target("编辑·篇幅变化", _chars(draft), _chars(body), chapter_target,
                          weight=0.10, label_before="初稿", label_after="改稿")
    return [fence, keep, size]


# ─────────────────────────────── 润色师 ───────────────────────────────

def grade_polisher(polished: str | None, edited: str | None,
                   anchors: list[str],
                   chapter_target: int) -> list[GraderResult]:
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

    size = _toward_target("润色师·篇幅保持", _chars(edited_body), _chars(polished), chapter_target,
                          weight=0.10, label_before="改稿", label_after="终稿")
    return [ai, size]
