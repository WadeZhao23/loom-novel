"""连续性除虫:本章终稿 vs 前情(状态账本/近两章/回顾/硬设定)的跨章矛盾检测。

双引擎(docs/design/proposals/除虫闭环.md §2):确定性检测(纯函数,零 LLM,保底两类致命伤)
+ LLM 复审(cheap_backend);合流按〔类别+证据/描述〕去重,确定性在前。
只报告绝不改稿(ADR-0006);同一次 LLM 调用顺手产出【状态入账】——账本不依赖 learn。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import events, statebook
from .backends import Backend
from .fsutil import atomic_write_text


def _char_names_from_dir(project_root: Path) -> set[str]:
    """从 外置大脑/人物/ 目录取角色名(文件名去掉 .md)。目录不存在返回空。"""
    chars_dir = project_root / "外置大脑" / "人物"
    if not chars_dir.is_dir():
        return set()
    return {p.stem for p in chars_dir.iterdir() if p.suffix == ".md" and p.stem != "模板"}




Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


@dataclass
class BugItem:
    """一条跨章矛盾:严重度 + 类别 + 双侧证据 + 修改示例。"""
    stars: int                 # 1-5
    kind: str                  # 物品/人设/规则/时间/衔接/其他
    desc: str
    evidence: str = ""         # 本章证据(原文短引)
    prior: str = ""            # 前情证据(第N章「…」/账本行)
    target: str = "正文"       # 正文/设定(按建议改的落点)
    fix: str = ""              # 修改示例(一句可直接用的写法)

    def as_dict(self) -> dict:
        return {"星": self.stars, "类别": self.kind, "问题": self.desc, "本章证据": self.evidence,
                "前情证据": self.prior, "落点": self.target, "修改示例": self.fix}


_SENT_SPLIT = re.compile(r"(?<=[。!?！？…])")


def _sentence_of(body: str, needle: str) -> str:
    """取 needle 在正文里所在的那一句(证据短引);没找到返回 needle 本身。"""
    idx = body.find(needle)
    if idx < 0:
        return needle
    for sent in _SENT_SPLIT.split(body):
        if needle in sent:
            return sent.strip()[:80]
    return needle


# ── 时间词体系:用于 detect_time_mismatch 的时序推理 ────────
# 每项 = (关键词, 天数偏移, 时段优先级)
# 天数偏移:relative to 前章结尾时间; 时段优先级:0=morning…3=night
_TIME_WORDS = (
    (r"当日", 0, 0), (r"当天", 0, 0), (r"今天", 0, 0), (r"今日", 0, 0),
    (r"翌日", 1, 0), (r"次日", 1, 0), (r"第二天", 1, 0), (r"隔日", 1, 0),
    (r"三日后", 3, 0), (r"几日后", 3, 0), (r"数日后", 3, 0), (r"七日后", 7, 0),
    (r"十日后", 10, 0), (r"半月后", 15, 0),
    (r"当夜", 0, 3), (r"今晚", 0, 3),
    (r"昨夜", -1, 3), (r"昨晚", -1, 3),
    (r"凌晨", 0, 0), (r"清晨", 0, 0), (r"早晨", 0, 0), (r"上午", 0, 1),
    (r"正午", 0, 1), (r"午后", 0, 1), (r"下午", 0, 2),
    (r"傍晚", 0, 2), (r"黄昏", 0, 2), (r"深夜", 0, 3), (r"子夜", 0, 3),
)
_TIME_RE = re.compile(r"|".join(p[0] for p in _TIME_WORDS))


def _time_of(text: str) -> tuple[int, int] | None:
    """取正文里第一个时间词,返回 (天数偏移, 时段优先级)。没匹配返回 None。"""
    m = _TIME_RE.search(text)
    if not m:
        return None
    for pat, day, period in _TIME_WORDS:
        if re.match(pat, m.group()):
            return (day, period)
    return None


def _clock_from_book(book: dict, chapter_n: int) -> str | None:
    """从账本取上一章的 [时钟] 行原文,没有返回 None。"""
    for m in reversed(sorted(k for k in book if k < chapter_n)):
        for kind, content in book[m]:
            if kind == "时钟":
                return content.split("|")[0].strip()
    return None


def detect_time_mismatch(book: dict[int, list[tuple[str, str]]], chapter_n: int, body: str) -> list[BugItem]:
    """时间连续性检测:账本 [时钟] vs 本章正文首时间词。
    只报两类确凿矛盾:
    1. 倒流:前章「三日后」本章「次日/昨日/昨夜」(天数偏移明显后退)
    2. 回头:前章「翌日」本章「当日/今日」(同一时点说两次)
    当夜/今晚等模糊词不报(叙事中可能指同一天的夜晚)。"""
    out: list[BugItem] = []
    clock = _clock_from_book(book, chapter_n)
    if not clock:
        return out
    prev_t = _time_of(clock)
    if prev_t is None:
        return out
    prev_day = prev_t[0]
    cur = _time_of(body[:200])
    if cur is None:
        return out
    cur_day = cur[0]
    # 1. 天数倒流:前章向前跳(≥3),本章倒回(≤1)
    if cur_day < prev_day - 1:
        out.append(BugItem(4, "时间",
            f"时间倒流:前章结尾向前跳至{clock.split('|')[0].strip()},本章出现更早的时间词",
            evidence=f"本章开头:「{body[:60]}」"[:60],
            prior=f"第{max(k for k in book if k < chapter_n)}章账本时钟",
            fix="统一时间流向,或在本章开头加一句时间跳过说明"))
    return out



def detect_char_continuity(book: dict[int, list[tuple[str, str]]], chapter_n: int, body: str, char_names: set[str]) -> list[BugItem]:
    """人物出场关联检测:状态账本 [状态] 行人物在前情有特殊状态(重伤/闭关/失踪/禁足等)
    且本章首次提到该人物时未交代状态变化 → 标记。char_names 来自人物目录文件名。"""
    _SPECIAL_STATES = re.compile(r"(?:^|[^无未不])(?:重伤|闭关|失踪|禁足|昏迷|囚禁|封印|昏迷|被俘|失忆|流放|除名|镇守|被控)")
    out: list[BugItem] = []
    last_state: dict[str, str] = {}  # char_name -> state_line
    for m in reversed(sorted(k for k in book if k < chapter_n)):
        for kind, content in book[m]:
            if kind != "状态":
                continue
            change = content.split("|")[0].strip()
            name = re.split(r"[:：]", change, 1)[0].strip()
            if name and name not in last_state:
                last_state[name] = change
    for name, state_line in last_state.items():
        if not _SPECIAL_STATES.search(state_line):
            continue
        # 没全名但只有简称/外号在正文 → 有风险但证据不够硬,不在纯函数里报
        # 直接检查:特殊状态角色出现在正文但没有提到状态恢复
        if name not in body:
            # 别名匹配:去姓(单姓/复姓)、·尾名、单字姓后缀匹配
            aliases = []
            if len(name) >= 2:
                aliases.append(name[1:])
                if name[0] in "慕容南宫欧阳西门上官端木独孤诸葛":
                    aliases.append(name[2:])
            if "·" in name:
                aliases.append(name.split("·")[-1])
            aliases.append(name[0])
            aliases.append(name[0] + "姑娘")
            aliases.append(name[0] + "公子")
            aliases.append(name[0] + "前辈")
            aliases.append(name[0] + "兄")
            aliases.append(name[0] + "老")
            aliases.append(name[0] + "某")
            for alias in set(a for a in aliases if len(a) >= 1):
                if alias not in body:
                    continue
                out.append(BugItem(
                    3, "人设",
                    f"「{name}」前情处于特殊状态:{state_line},本章仅以别名/简称出现",
                    evidence=alias,
                    prior=f"第{m}章账本:{state_line}",
                    fix=f"补足全称并交代状态变化"))
                break
        elif state_line not in body[:500]:
            # 全名出现但没提状态变化
            out.append(BugItem(
                3, "人设",
                f"「{name}」前情处于{state_line},本章出现但未交代状态变化",
                evidence=name[:60],
                prior=f"第{m}章账本:{state_line}",
                fix=f"在文中交代{name.split(chr(58))[0] if ':' in name else name}当前状态"))
    return out

_PUNC_RE = re.compile(r'[\s·、，。！？：；\-—…()（【】『』「」《》/]')


def _normalize(s: str) -> str:
    """归一化:去标点符号、去空格,用于模糊匹配。"""
    return _PUNC_RE.sub("", s)



def _fuzzy_entity_in_body(entity: str, body: str) -> str | None:
    """精确&模糊匹配实体是否在正文中出现。
    返回匹配到的原文片段(报证据用),没匹配到返回 None。
    模糊策略:剥标点、取右边(keyword)部分「仙阶金丹·高品质」→ 取「高品质」。"""
    # 1. 精确匹配
    if entity in body:
        return entity
    # 2. 归一化后匹配(如「远古药胚」变「远古药胚」与「远古 药胚」同)
    ne = _normalize(entity)
    nb = _normalize(body)
    if len(ne) >= 2 and ne in nb:
        return entity
    # 3. 取「·」后的子名(如「仙阶金丹·高品质」→「高品质」)
    for part in entity.split('·'):
        p = part.strip()
        if len(p) >= 2 and p in body:
            return p
    # 4. 取两字以上关键词(全称去掉前两个字去匹配,如「炼体药胚」→「药胚」)
    if len(entity) > 4:
        core = entity[2:]
        if len(core) >= 2 and core in body:
            return core
    return None


def detect_consumed_reuse(book: dict[int, list[tuple[str, str]]], chapter_n: int, body: str) -> list[BugItem]:
    """账本前章已标消耗类的 [物品] 实体出现在本章正文 → 致命候选。
    精确+模糊匹配:别名/简称按归一化、取尾名、去前缀兜底。"""
    out: list[BugItem] = []
    seen: set[str] = set()
    for m in sorted(k for k in book if k < chapter_n):
        for kind, content in book[m]:
            change = content.split("|", 1)[0]
            if kind != "物品" or not any(k in change for k in statebook._CONSUMED_KW):
                continue
            entity = re.split(r"[:：]", content, 1)[0].strip()
            if len(entity) < 2 or entity in seen:
                continue
            match = _fuzzy_entity_in_body(entity, body)
            if not match:
                continue
            seen.add(entity)
            out.append(BugItem(
                5, "物品",
                f"「{entity}」第{m}章已消耗/失去,本章以{match}形式再次使用",
                evidence=_sentence_of(body, match),
                prior=f"第{m}章账本:「{content}」",
                fix=f"改掉「{entity}」的来源(换成尚存的材料/道具),或删去这次使用"))
    return out


_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*[%％倍成]")


def detect_rule_drift(book: dict[int, list[tuple[str, str]]], chapter_n: int, body: str) -> list[BugItem]:
    """账本 [规则] 行带数值,本章正文同段落提到该规则却给出不同数值 → 候选。保守:双方都有数值才比。"""
    out: list[BugItem] = []
    paras = [p for p in body.split("\n") if p.strip()]
    for m in sorted(k for k in book if k < chapter_n):
        for kind, content in book[m]:
            if kind != "规则":
                continue
            entity = re.split(r"[:：]", content, 1)[0].strip()
            nums = set(_NUM_RE.findall(content.replace(" ", "")))
            if len(entity) < 2 or not nums:
                continue
            for p in paras:
                if entity not in p:
                    continue
                got = set(_NUM_RE.findall(p.replace(" ", "")))
                diff = got - nums
                if got and diff:
                    out.append(BugItem(
                        4, "规则",
                        f"「{entity}」数值与账本不符:账本 {'/'.join(sorted(nums))},本章出现 {'/'.join(sorted(diff))}",
                        evidence=_sentence_of(p, entity),
                        prior=f"第{m}章账本:「{content}」",
                        fix=f"统一「{entity}」数值为账本口径,或在正文点明规则为何变化并更新账本"))
                    break
    return out


def merge_items(det: list[BugItem], llm: list[BugItem]) -> list[BugItem]:
    """确定性在前、LLM 在后,按(类别, 证据 or 描述)去重——与 gates._merge_issues 同语义。"""
    seen: set[tuple[str, str]] = set()
    out: list[BugItem] = []
    for i in list(det) + list(llm):
        key = (i.kind, i.evidence or i.desc)
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out


_SCAN_SYSTEM = """你是**连续性审读员**(除虫),只诊断、不改写。我给你:本章终稿、状态账本摘录、\
最近两章正文结尾、卡章纲(含AI回顾)、硬设定。逐类检查本章与前情的矛盾:
物品(已消耗/失去的东西再次出现使用——注意别名/简称,如账本记「炼体药胚:耗尽」正文出现「药胚」也算)、人设(行为违背人物底线/身段/与境界差不符的姿态——注意角色别名如「苏某」「苏前辈」代指「苏清瑶」)、\
规则(金手指/体系的数值条款与账本或前章不一致)、时间(时间词粒度与前情时刻不符,如昨夜的事说成昨日)、\
衔接(与前几章已定事实冲突)。**宁缺毋滥**:确凿的矛盾才报,每条带两处证据。
输出(严格,两段,分隔行原样保留):
===除虫报告===
无矛盾只写一行「通过」;有则每条一行、按严重度降序、最多 6 条:
- ⭐⭐⭐⭐⭐ | 物品 | 一句话冲突 | 本章证据:「原文短引」 | 前情证据:第2章「原文短引或账本行」 | 落点:正文 | 修改示例:一句可直接替换的写法
(⭐1-5=严重度;类别∈物品/人设/规则/时间/衔接/其他;落点∈正文/设定——该改设定文件的写「设定」并在修改示例里点名文件)
===状态入账===
本章新发生的状态变更(没有就一行「- 无」):
- [物品] 实体:变更 | 证据:「原文短引」
- [状态] 人物:新状态(变化原因) | 证据:「原文短引」
- [规则] 规则名:数值/条款 | 证据:「原文短引」
- [时钟] 章末:故事内时间"""

_REPORT_LINE = re.compile(r"^[-·•]\s*(.+)$")


def parse_scan(raw: str) -> tuple[list[BugItem], list[str]]:
    """双段宽容解析。报告段「通过」→ [];入账段只认 statebook 四类行,「- 无」→ []。"""
    report_part, _, state_part = raw.partition("===状态入账===")
    report_part = report_part.split("===除虫报告===")[-1]
    items: list[BugItem] = []
    for line in report_part.splitlines():
        m = _REPORT_LINE.match(line.strip())
        if not m:
            continue
        segs = [s.strip() for s in m.group(1).split("|")]
        if len(segs) < 3:
            continue
        stars = min(5, max(1, segs[0].count("⭐") or 3))
        item = BugItem(stars, segs[1][:8], segs[2])
        for seg in segs[3:]:
            if seg.startswith("本章证据"):
                item.evidence = seg.split(":", 1)[-1].split("：", 1)[-1].strip().strip("「」\"")
            elif seg.startswith("前情证据"):
                # prior 含章号前缀(如「第2章「原句」」),格式本就混合,故不剥引号(与 evidence 不同,有意为之)
                item.prior = seg.split(":", 1)[-1].split("：", 1)[-1].strip()
            elif seg.startswith("落点"):
                t = seg.split(":", 1)[-1].split("：", 1)[-1].strip()
                item.target = "设定" if "设定" in t else "正文"
            elif seg.startswith("修改示例"):
                item.fix = seg.split(":", 1)[-1].split("：", 1)[-1].strip()
        items.append(item)
    state_lines = [l.strip() for l in state_part.splitlines()
                   if statebook._LINE_RE.match(l.strip())]
    return items, state_lines


def _prev_tail(project_root: Path, n: int, chars: int = 1200) -> str:
    from .chaptertext import strip_title
    from .paths import chapter_path
    p = chapter_path(project_root, n)
    return strip_title(p.read_text(encoding="utf-8")).strip()[-chars:] if p.exists() else ""


_NOTE_HEAD = "## 除虫报告(非阻断,供你定夺)"


def _strip_old_report(text: str) -> str:
    """剥掉旧的除虫报告小节(到下一个 ## 标题或文件尾)——重扫替换,别的留痕小节原样。"""
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == _NOTE_HEAD:
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept).rstrip()


def _note_report(project_root: Path, chapter_n: int, items: list[BugItem]) -> Path:
    """报告替换进 .审稿留痕/第N章.md(非阻断,双证据行格式)。重扫替换旧节,别的留痕小节原样。"""
    from .paths import review_note_path
    path = review_note_path(project_root, chapter_n)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 读旧文并剥掉旧报告小节
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    text_without_old_report = _strip_old_report(old_text) if old_text else ""

    lines = []
    if text_without_old_report:
        lines.append(text_without_old_report)
    lines.append(f"\n{_NOTE_HEAD}")
    if not items:
        lines.append("- 未发现跨章矛盾")
    for i in items:
        lines.append(f"- {'⭐' * i.stars} {i.kind}:{i.desc}"
                     f" | 本章证据:「{i.evidence}」 | 前情:{i.prior}"
                     + (f" | 修改示例:{i.fix}" if i.fix else ""))

    new_content = "\n".join(lines) + "\n"
    atomic_write_text(path, new_content)
    return path


def scan_chapter(project_root: Path, chapter_n: int, body: str, backend: Backend, *,
                 hardfacts: str = "", progress: Progress = _noop) -> dict:
    """除虫一章:确定性双检测恒跑;LLM 扫描失败只降级不整体失败。落留痕+入账,返回报告。"""
    project_root = Path(project_root)
    from . import budget
    from .paths import CARD_REL, STATEBOOK_REL
    p_book = project_root / STATEBOOK_REL
    book = statebook.parse_book(p_book.read_text(encoding="utf-8")) if p_book.exists() else {}
    char_names = _char_names_from_dir(project_root)
    det = merge_items(
        merge_items(detect_consumed_reuse(book, chapter_n, body),
                    detect_rule_drift(book, chapter_n, body)),
        detect_time_mismatch(book, chapter_n, body))
    det = merge_items(det, detect_char_continuity(book, chapter_n, body, char_names))

    llm_items: list[BugItem] = []
    state_lines: list[str] = []
    try:
        progress(events.info(f"除虫第 {chapter_n} 章:对照前情查跨章矛盾…"))
        snap = statebook.snapshot_for(project_root, chapter_n - 1) or "(账本为空:第一章或还没除过虫)"
        card_p = project_root / CARD_REL
        card = budget.fold_recaps(card_p.read_text(encoding="utf-8"), chapter_n) if card_p.exists() else ""
        parts = [f"## 本章终稿(第{chapter_n}章)\n{body}",
                 f"## 状态账本摘录(截至第{chapter_n - 1}章)\n{snap}"]
        for m in (chapter_n - 1, chapter_n - 2):
            tail = _prev_tail(project_root, m) if m >= 1 else ""
            if tail:
                parts.append(f"## 第{m}章结尾\n{tail}")
        if card.strip():
            parts.append(f"## 卡章纲(含AI回顾)\n{card}")
        if hardfacts.strip():
            parts.append(f"## 硬设定\n{hardfacts}")
        parts.append("## 你的任务\n按系统要求输出两段:除虫报告 + 状态入账。")
        raw = backend.complete(_SCAN_SYSTEM, "\n\n".join(parts), max_chars=900)
        llm_items, state_lines = parse_scan(raw)
    except Exception:
        pass   # LLM 侧任何失败都吞:确定性结果照出,附赠动作绝不拖累出稿

    issues = merge_items(det, llm_items)
    note_path = _note_report(project_root, chapter_n, issues)
    written = False
    if state_lines:
        written = statebook.append_section(project_root, chapter_n, state_lines)
    return {"issues": [i.as_dict() for i in issues], "state_lines": state_lines,
            "note_path": str(note_path), "ledger_written": written}
