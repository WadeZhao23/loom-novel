"""整书诊断:读已写小说的采样章,cheap LLM 把已有设定提炼成候选(带正文出处),不落盘。

红线(spec §7 / ADR 0014 诊断四边界):
- 候选只从作者正文提炼、逐条带出处(第N章),有出处=提炼、无出处=发明;
- 确认前不落盘(本模块只 return 候选,commit 在别处);
- 立项段永不进诊断(正文无平台/对标意图);
- 走 cheap_model,不沾指纹/voice。
"""

from __future__ import annotations

from pathlib import Path

from . import paths
from .chaptertext import strip_title
from .parse import split_brain_draft

_SAMPLE_HEAD = 3   # 前 3 章(定人设/金手指)
_SAMPLE_TAIL = 2   # 最近 2 章(定当前状态)
_MAX_CHARS = 2600  # 出题预算(仿 draft)

_SYSTEM = (
    "你是写作助手的记录员。作者给你他已写好的小说正文片段,你要把正文里**已经存在**的设定"
    "提炼成可落盘的资料卡。红线:只写正文里有的,逐条在括号里标出处(第N章);正文没写的绝不编造。\n"
    "严格按三段输出,用分隔标记隔开,每段可直接落盘的中文 Markdown;某段正文里看不出就整段留空:\n"
    "===世界观===\n(## 小节标题 + 正文;如力量体系/金手指/地理势力,各条带(第N章)出处)\n"
    "===人物卡===\n(## 主角 · 名字 / ## 配角 · 名字 / ## 反派 · 名字,各挂人物要点,带(第N章)出处)\n"
    "===卡章纲===\n(- 第N章:这章讲了什么,一行一章)\n"
    "不要写立项卡/平台/题材(正文里没有)。"
)


def _sample_chapters(root: Path) -> str:
    nums = paths.chapter_numbers(root)
    if not nums:
        return ""
    picked = sorted(set(nums[:_SAMPLE_HEAD] + nums[-_SAMPLE_TAIL:]))
    parts = []
    for n in picked:
        p = paths.chapter_path(root, n)
        if p.is_file():
            body = strip_title(p.read_text(encoding="utf-8")).strip()
            parts.append(f"【第{n}章】\n{body}")
    return "\n\n".join(parts)


def commit(root: Path, picks: dict) -> dict:
    """把作者确认的候选落盘:世界观/人物走 _write_sections_into_dir(人写优先),卡章纲走 _apply_card_lines;
    主角指认:picks['protagonist'] 指明主角名 → 该人物节改名 ## 主角 · 名字,落成 主角·名字.md。立项永不碰。"""
    from .draft import _write_sections_into_dir
    from .journey import _apply_card_lines
    landed: list[str] = []
    world = (picks.get("世界观") or "").strip()
    if world:
        got = _write_sections_into_dir(root, paths.WORLD_DIR_REL, "\n" + world, drop_unnamed=False)
        landed += [f"{paths.WORLD_DIR_REL}/{n}.md" for n in got]
    chars = _reheader_protagonist(picks.get("人物卡") or "", (picks.get("protagonist") or "").strip())
    if chars.strip():
        got = _write_sections_into_dir(root, paths.CHARS_DIR_REL, "\n" + chars, drop_unnamed=True)
        landed += [f"{paths.CHARS_DIR_REL}/{n}.md" for n in got]
    card = (picks.get("卡章纲") or "").strip()
    if card:
        landed.append(_apply_card_lines(root, card))
    return {"landed": landed}


def _reheader_protagonist(chars_body: str, protagonist: str) -> str:
    """把候选人物卡里名为 protagonist 的那节标题归一为「## 主角 · 名字」(主角谓词要这个命名)。"""
    if not protagonist:
        return chars_body
    import re as _re

    def _fix(m):
        head = m.group(0)
        return f"## 主角 · {protagonist}" if protagonist in head else head

    return _re.sub(r"^##\s*[^\n]*$", _fix, chars_body, flags=_re.M)


def scan(root: Path, backend) -> dict:
    """读采样章 → LLM 出三段候选 dict(世界观/人物卡/卡章纲);不落盘。失败/空/无章 → {}。"""
    from .backends import LoomBackendError
    sample = _sample_chapters(root)
    if not sample:
        return {}
    user = f"作者已写好的小说正文(采样):\n\n{sample}\n\n按三段格式,把正文里已有的设定提炼成候选。"
    try:
        raw = backend.complete(_SYSTEM, user, max_chars=_MAX_CHARS)
    except LoomBackendError:
        return {}
    return split_brain_draft(raw)   # {"世界观":..,"人物卡":..,"卡章纲":..},缺段不进;不成三段则 {}
