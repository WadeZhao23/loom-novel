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
            if kind != "物品" or not any(k in content for k in statebook._CONSUMED_KW):
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
