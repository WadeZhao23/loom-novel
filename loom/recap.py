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

from .backends import Backend
from .fsutil import atomic_write_text

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


CARD_REL = "外置大脑/卡章纲.md"
_RECAP_MARK = "[AI回顾]"   # 物理隔离标记

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
    final_path = project_root / "正文" / f"第{chapter_n}章.md"
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
        progress({"type": "recap_skip", "chapter": chapter_n})
        return None

    final = final_path.read_text(encoding="utf-8").strip()
    progress({"type": "info", "message": f"正在为第 {chapter_n} 章补写后摘要…"})
    raw = backend.complete(_RECAP_SYSTEM, f"第 {chapter_n} 章定稿正文:\n\n{final}", max_chars=600)
    block = _format_block(chapter_n, raw)

    new_card = _append_recap(card, chapter_n, block)
    if new_card is None:           # 没找到该章规划行 / 已存在
        progress({"type": "recap_skip", "chapter": chapter_n})
        return None
    atomic_write_text(card_path, new_card)
    progress({"type": "recap_done", "chapter": chapter_n, "path": str(card_path)})
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


def _format_block(n: int, raw: str) -> str:
    # 把 LLM 两段输出折成卡章纲下的缩进子块;截断摘要 ≤150 字硬保险
    text = raw.strip()
    m = re.search(r"摘要[:：]\s*(.+?)(?=\n伏笔|$)", text, re.DOTALL)
    summary = (m.group(1).strip() if m else text)[:150]
    fm = re.search(r"伏笔[:：]?\s*\n(.+)$", text, re.DOTALL)
    fore = fm.group(1).strip() if fm else "- 无"
    foreshadow = "\n".join("    " + l.strip() for l in fore.splitlines() if l.strip())
    return (f"  - {_RECAP_MARK} 摘要:{summary}\n"
            f"    伏笔:\n{foreshadow}")


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
