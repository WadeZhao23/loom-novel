"""篇幅校准:把「写 N 字」换算成「写 P 段」——给模型一个它数得过来的整数。

**为什么**:大模型数不准字数(LIFEBench 等基准的普遍结论:连 GPT-4 级模型也做不到),
但对**小整数的结构计数**跟随得好得多。Loom 手上从粗到细的结构单位是:

    场次(2-6)  →  段落(几十)  →  句子(近百)  →  字(上千)

场次那一层细纲已经有了(`artifacts._outline_contract` 的「拆 N 场 + 每场约X字」);
这里补段落这一层。真机量过样例书:1200 字 ≈ 63 段 ≈ 92 句——**段落是唯一那个既够细、
又还在模型数得清的量级里的单位**。

**换算系数不写死,从这本书的已有正文现算**。理由有两条:
① 段落节奏因人而异(样例书实测 18.9 字/段),写死常数等于把别人的节奏塞给作者;
② 这正是研究里说的 few-shot length calibration,只不过用确定性测量代替了喂样例——
   顺带地,它测的东西本身就是文风的一部分。

红线:只读、不发 LLM、不打分;样本不够就返回 0(= 没有校准),宁可不给结构目标,
也绝不拿一个编出来的系数糊弄。
"""

from __future__ import annotations

from pathlib import Path

from . import paths

_MIN_CHAPTERS = 2   # 少于两章不足以谈「这个作者的节奏」,不给系数
_MIN_PARAS = 6      # 段落太少(占位/极短章)算出来的系数没有意义


def _visible(text: str) -> int:
    return len("".join(text.split()))


def chars_per_para(root: Path | str, upto_n: int | None = None) -> float:
    """作者已写章节的实测「每段多少字」。样本不够返回 0.0。

    读的是 `正文/第N章.md`(**手改后的定稿**,不是 `.原稿` 快照)——要测的是作者的节奏,
    不是 AI 的。标题行剥掉:它是 H1、不是正文段落,且绝不参与文风(ADR 0009)。
    """
    from .chaptertext import strip_title
    root = Path(root)
    nums = paths.chapter_numbers(root)
    if upto_n is not None:
        nums = [n for n in nums if n <= upto_n]
    chars = paras = 0
    used = 0
    for n in nums:
        p = paths.chapter_path(root, n)
        try:
            body = strip_title(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        lines = [l for l in body.splitlines() if l.strip()]
        if len(lines) < _MIN_PARAS:
            continue
        chars += _visible(body)
        paras += len(lines)
        used += 1
    if used < _MIN_CHAPTERS or paras <= 0:
        return 0.0
    return chars / paras


def para_target(root: Path | str, chapter_target: int, upto_n: int | None = None) -> int:
    """本章目标字数 → 目标段落数。没有校准(或目标为 0)时返回 0 = 不给结构目标。"""
    if chapter_target <= 0:
        return 0
    cpp = chars_per_para(root, upto_n)
    if cpp <= 0:
        return 0
    return max(1, round(chapter_target / cpp))
