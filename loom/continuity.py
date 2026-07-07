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


def detect_consumed_reuse(book: dict[int, list[tuple[str, str]]], chapter_n: int, body: str) -> list[BugItem]:
    """账本前章已标消耗类的 [物品] 实体名(精确≥2字)出现在本章正文 → 致命候选。
    诚实局限:别名/简称靠 LLM 兜,这里只精确匹配保底;回忆式提及也会报(非阻断,作者定夺)。"""
    out: list[BugItem] = []
    seen: set[str] = set()
    for m in sorted(k for k in book if k < chapter_n):
        for kind, content in book[m]:
            change = content.split("|", 1)[0]   # 只看变更描述段,别让证据引文里的动词误命中(如「耗尽力气」)
            if kind != "物品" or not any(k in change for k in statebook._CONSUMED_KW):
                continue
            entity = re.split(r"[:：]", content, 1)[0].strip()
            if len(entity) < 2 or entity in seen or entity not in body:
                continue
            seen.add(entity)
            out.append(BugItem(
                5, "物品",
                f"「{entity}」第{m}章已消耗/失去,本章正文再次出现使用",
                evidence=_sentence_of(body, entity),
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
物品(已消耗/失去的东西再次出现使用)、人设(行为违背人物底线/身段/与境界差不符的姿态)、\
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
    det = merge_items(detect_consumed_reuse(book, chapter_n, body),
                      detect_rule_drift(book, chapter_n, body))

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
