"""状态账本:跨章状态的单一真相(物品/人物状态/规则数值/故事时钟),住 外置大脑/状态账本.md。

设计与红线(docs/design/proposals/除虫闭环.md §1):
- markdown 是唯一真相,这里只是读写法——不建实体库、不打分、不向量(三库调研红线③)。
- AI 只【追加新章节】,write-once 按「## 第N章」节判重;已有节绝不改(人写优先)。
- 删章摘除/重编号搬运由 chapters.py 与 [AI回顾]/[AI补充] 同批调用,模式照抄 recap。
- 存活快照(进大纲师/写手 prompt):近 _WINDOW 章四类行原样;远章只留「消耗类物品行+全部规则行」
  ——防「第2章吞掉的药胚第40章复活」「因果锁定 100% 漂成 10%」;[状态][时钟] 滚动窗外丢弃。
"""

from __future__ import annotations

import re
from pathlib import Path

from .fsutil import atomic_write_text
from .paths import STATEBOOK_REL

_SEC_RE = re.compile(r"^##\s*第(\d+)章\s*$")
_LINE_RE = re.compile(r"^-\s*\[(物品|状态|规则|时钟)\]\s*(.+?)\s*$")
_CONSUMED_KW = ("消耗", "失去", "损毁", "赠出", "用尽", "吞服", "服用", "报废", "耗尽")
_WINDOW = 8   # 与 budget.WINDOW 同窗口;独立常量——账本折叠语义与回顾折叠不同,别误共用

_HEADER = (
    "# 状态账本\n\n"
    "> 跨章状态的流水账。每章「除虫」后 AI 自动记一节——你可改可删,AI 只追加新章节、绝不动已有的节。\n"
    "> 四类行:[物品] 得失与消耗 / [状态] 人物境界伤势处境 / [规则] 金手指与体系数值 / [时钟] 章末故事时间。\n"
)


def _path(project_root: Path) -> Path:
    return Path(project_root) / STATEBOOK_REL


def parse_book(text: str) -> dict[int, list[tuple[str, str]]]:
    """全文 → {章号: [(类别, 内容)]}。节外内容与不合式行一律忽略(宽容读)。"""
    book: dict[int, list[tuple[str, str]]] = {}
    cur: int | None = None
    for line in text.splitlines():
        m = _SEC_RE.match(line.strip())
        if m:
            cur = int(m.group(1))
            book.setdefault(cur, [])
            continue
        if cur is None:
            continue
        lm = _LINE_RE.match(line.strip())
        if lm:
            book[cur].append((lm.group(1), lm.group(2)))
    return book


def has_section(text: str, n: int) -> bool:
    return any(_SEC_RE.match(l.strip()) and int(_SEC_RE.match(l.strip()).group(1)) == n
               for l in text.splitlines())


def append_section(project_root: Path, n: int, lines: list[str]) -> bool:
    """write-once 追加「## 第N章」节。已有该节/空 lines → False 不动盘。"""
    lines = [l for l in lines if _LINE_RE.match(l.strip())]
    if not lines:
        return False
    p = _path(project_root)
    text = p.read_text(encoding="utf-8") if p.exists() else _HEADER
    if has_section(text, n):
        return False
    block = f"\n## 第{n}章\n" + "\n".join(l.strip() for l in lines) + "\n"
    atomic_write_text(p, text.rstrip() + "\n" + block)
    return True


def snapshot_for(project_root: Path, upto_n: int) -> str:
    """存活快照(截至第 upto_n 章,含):每行「- 第N章 [类别] 内容」。空账本/无存活行返回空串。"""
    p = _path(project_root)
    if upto_n < 1 or not p.exists():
        return ""
    book = parse_book(p.read_text(encoding="utf-8"))
    out: list[str] = []
    for n in sorted(k for k in book if k <= upto_n):
        recent = n > upto_n - _WINDOW
        for kind, content in book[n]:
            keep = recent or kind == "规则" or (kind == "物品" and any(k in content for k in _CONSUMED_KW))
            if keep:
                out.append(f"- 第{n}章 [{kind}] {content}")
    return "\n".join(out)


def strip_section(project_root: Path, n: int) -> str:
    """摘除「## 第N章」整节,返回被摘文本(调用方留底回收站)。文件缺失/无该节返回空串。"""
    p = _path(project_root)
    if not p.exists():
        return ""
    lines = p.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    removed: list[str] = []
    in_target = False
    for line in lines:
        m = _SEC_RE.match(line.strip())
        if m:
            in_target = int(m.group(1)) == n
        (removed if in_target else kept).append(line)
    if not removed:
        return ""
    atomic_write_text(p, "\n".join(kept).rstrip() + "\n")
    return "\n".join(removed).strip() + "\n"


def remap_keys(project_root: Path, mapping: dict[int, int]) -> None:
    """节标题章号键按 mapping 两段式换号(old→占位→new),防 2↔3 互换撞键。与 recap/enrich 同模式。"""
    p = _path(project_root)
    if not p.exists() or not mapping:
        return
    text = p.read_text(encoding="utf-8")
    for old in mapping:
        text = re.sub(rf"^##\s*第{old}章\s*$", f"## 第__rn{old}__章", text, flags=re.M)
    for old, new in mapping.items():
        text = text.replace(f"## 第__rn{old}__章", f"## 第{new}章")
    atomic_write_text(p, text)
