"""写后摘要:learn 接受一章后,从【手改终稿】抽 ≤150 字摘要 + 伏笔行,
write-once 回填卡章纲对应章行下的「AI回顾」子块。

红线:
- 只读手改终稿(正文/第N章.md),不是 .原稿 快照。
- 摘要/伏笔只管 what(剧情脊柱),进卡章纲,绝不喂写作指纹(红线①)。
- write-once:同章重复 learn 不覆盖、不重复追加(红线②,人写优先)。
- 不引入实体库/打分/向量(红线③)。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import events
from .backends import Backend
from .fsutil import atomic_write_text
from .parse import _RECAP_MARK  # [AI回顾] 标记单一真相在 parse.py(S7),薄别名保引用面
from .parse import format_recap_block as _format_block
from .paths import CARD_REL, chapter_path

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


_RECAP_SYSTEM = """你是剧情脊柱记录员。我给你某一章的【作者定稿正文】。
请只描述这一章【实际写成了什么】(管 what,不管文笔好坏、不评价风格)。
严格输出下面两段,不要任何额外解释:
摘要:<一句话到三句话,≤150字,这章发生了什么、推进到哪>
伏笔:
- [埋设] <这章新埋的悬念/线索;没有就省略这行>
- [推进] <这章把某条已有线索往前推了;没有就省略>
- [回收] <这章兑现/闭合了之前的某个悬念;没有就省略>
若某类伏笔没有就不输出那一行;三类都没有则伏笔下写「- 无」。"""


def _ch_line(n: int) -> re.Pattern:
    return re.compile(rf"^- 第{n}章[:：]")


def recap_chapter(project_root: Path, chapter_n: int,
                  backend: Backend, progress: Progress = _noop) -> Path | None:
    final_path = chapter_path(project_root, chapter_n)
    if not final_path.exists():
        return None  # 没正文不报错(recap 是附赠,不阻断 learn)
    card_path = project_root / CARD_REL
    if not card_path.exists():
        return None

    # 前置检查:没这章规划行(没处可挂)或已有 [AI回顾] 子块,都直接跳过,绝不浪费一次 LLM 调用
    card = card_path.read_text(encoding="utf-8")
    if not any(_ch_line(chapter_n).match(ln) for ln in card.splitlines()):
        return None
    if _already_recapped(card, chapter_n):
        progress(events.recap_skip(chapter_n))
        return None

    final = final_path.read_text(encoding="utf-8").strip()
    progress(events.info(f"正在为第 {chapter_n} 章补写后摘要…"))
    raw = backend.complete(_RECAP_SYSTEM, f"第 {chapter_n} 章定稿正文:\n\n{final}", max_chars=600)
    if not raw.strip():  # 模型没产出 → 干净跳过(附赠功能,绝不阻断 learn)
        progress(events.recap_skip(chapter_n))
        return None
    block = _format_block(chapter_n, raw)

    new_card = _append_recap(card, chapter_n, block)
    if new_card is None:           # 没找到该章规划行 / 已存在
        progress(events.recap_skip(chapter_n))
        return None
    atomic_write_text(card_path, new_card)
    progress(events.recap_done(chapter_n, card_path))
    return card_path


def _already_recapped(card: str, n: int) -> bool:
    lines = card.splitlines()
    for i, ln in enumerate(lines):
        if _ch_line(n).match(ln):
            for nxt in lines[i + 1:]:
                if nxt and not nxt.startswith((" ", "\t")):  # 到下一条顶格章行就停
                    break
                if _RECAP_MARK in nxt:
                    return True
            return False
    return False


def _append_recap(card: str, n: int, block: str) -> str | None:
    lines = card.splitlines()
    for i, ln in enumerate(lines):
        if _ch_line(n).match(ln):
            # 跳过该章已有的缩进子块/空行,插在其末尾(不动作者手写的规划行)
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                if _RECAP_MARK in lines[j]:
                    return None   # write-once:已存在
                j += 1
            lines.insert(j, block)
            return "\n".join(lines) + ("\n" if card.endswith("\n") else "")
    return None  # 卡章纲里没有这章的规划行


def _recap_span(lines: list[str], n: int) -> tuple[int, int] | None:
    """定位第 N 章 [AI回顾] 自动子块的行区间 [start, end);没有就 None。

    子块 = `  - [AI回顾]…` 那一行 + 紧随其后【缩进更深】的伏笔子行;遇到空行、
    同级兄弟项或下一条顶格章行即止——只圈 loom 自己写的那块,不碰作者手写的规划行。
    """
    for i, ln in enumerate(lines):
        if not _ch_line(n).match(ln):
            continue
        j = i + 1
        while j < len(lines):
            cur = lines[j]
            if cur.strip() and not cur.startswith((" ", "\t")):
                return None                      # 到下一条顶格行仍没 [AI回顾]
            if _RECAP_MARK in cur:
                base = len(cur) - len(cur.lstrip())
                k = j + 1
                while k < len(lines):
                    nxt = lines[k]
                    if nxt.strip() and (len(nxt) - len(nxt.lstrip())) > base:
                        k += 1                   # 该块的伏笔子行(缩进更深),一起删
                    else:
                        break
                return j, k
            j += 1
        return None
    return None


def strip_recap(project_root: Path, chapter_n: int) -> str | None:
    """删掉第 N 章在卡章纲下的 [AI回顾] 自动子块(只删 loom 自己写的那块,
    不碰作者手写的顶格规划行)。返回被删文本(供回收站留底),没有则 None。

    给删章用:章一删除,它那条 [AI回顾] 就成了悬空的陈旧记忆——留着会让"同章号
    重新生成后再 learn"因 write-once 跳过补写,卡章纲里显示的还是【已删旧章】的回顾。
    """
    card_path = project_root / CARD_REL
    if not card_path.exists():
        return None
    raw = card_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    span = _recap_span(lines, chapter_n)
    if span is None:
        return None
    s, e = span
    removed = "\n".join(lines[s:e])
    new_lines = lines[:s] + lines[e:]
    atomic_write_text(card_path, "\n".join(new_lines) + ("\n" if raw.endswith("\n") else ""))
    return removed


def remap_recap_keys(project_root: Path, mapping: dict[int, int]) -> None:
    """章节重编号时:把卡章纲里各章的 [AI回顾] 子块搬到新章号的规划行下。

    两段式(与 chapters._renumber 搬文件同法):先把受影响章的子块全部摘下,再按新章号
    逐个挂回,防 2↔3 互换互相覆盖。只搬 loom 自己写的 [AI回顾] 子块,人手写的规划行
    一字不动(章号同步仍靠 SYNC_NOTE 提示作者)。新章号在卡章纲里还没有规划行(或该行下
    已有别的 [AI回顾])→ 该子块无处可挂,放弃——宁可丢一条 AI 回顾,也不猜着造/改人写的规划行。
    """
    mapping = {o: n for o, n in mapping.items() if o != n}
    card_path = project_root / CARD_REL
    if not mapping or not card_path.exists():
        return
    raw = card_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    moved: list[tuple[int, str]] = []
    for old, new in mapping.items():       # 段一:摘下(逐个重定位——删行后下标会变)
        span = _recap_span(lines, old)
        if span is None:
            continue
        s, e = span
        moved.append((new, "\n".join(lines[s:e])))
        lines = lines[:s] + lines[e:]
    if not moved:
        return
    card = "\n".join(lines) + ("\n" if raw.endswith("\n") else "")
    for new, block in moved:               # 段二:挂回新章行下
        updated = _append_recap(card, new, block)
        if updated is not None:
            card = updated
    atomic_write_text(card_path, card)
