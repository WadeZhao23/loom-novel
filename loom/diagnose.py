"""整书诊断:读已写小说的采样章,cheap LLM 把已有设定提炼成候选(带正文出处),不落盘。

红线(spec §7 / ADR 0014 诊断四边界):
- 候选只从作者正文提炼、逐条带出处(第N章),有出处=提炼、无出处=发明;
- 确认前不落盘(本模块只 return 候选,commit 在别处);
- 立项段永不进诊断(正文无平台/对标意图);
- 走 cheap_model,不沾指纹/voice。
"""

from __future__ import annotations

import re

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
            body = strip_title(p.read_text(encoding="utf-8")).strip()[:3500]
            parts.append(f"【第{n}章】\n{body}")
    return "\n\n".join(parts)


def _land_candidate_sections(root: Path, file_rel: str, dir_rel: str, body: str,
                              *, drop_unnamed: bool) -> list[str]:
    """世界观/人物候选落盘,双形态兼容(补 brain_form 检查,免得单文件老书落进断链新目录=孤儿):
    单文件形态(老书/外置大脑/世界观.md 这类)→ 追加进单文件末尾(人写优先,不覆盖);
    目录/none 形态(新书)→ 按小节落目录(_write_sections_into_dir,人写优先,撞车即丢弃)。"""
    if paths.brain_form(root, file_rel, dir_rel) == "file":
        from .fsutil import atomic_write_text
        p = root / file_rel
        old = p.read_text(encoding="utf-8") if p.is_file() else ""
        atomic_write_text(p, (old.rstrip() + "\n\n" if old.strip() else "") + body.strip() + "\n")
        return [file_rel]
    from .draft import _write_sections_into_dir
    got = _write_sections_into_dir(root, dir_rel, "\n" + body, drop_unnamed=drop_unnamed)
    return [f"{dir_rel}/{n}.md" for n in got]


def commit(root: Path, picks: dict) -> dict:
    """把作者确认的候选落盘:世界观/人物走 _land_candidate_sections(单文件/目录双形态,人写优先),
    卡章纲走 _apply_card_lines(候选撞车即丢弃,不强塞);
    主角指认:picks['protagonist'] 指明主角名 → 该人物节改名 ## 主角 · 名字,落成 主角·名字.md。立项永不碰。"""
    from .journey import _apply_card_lines
    landed: list[str] = []
    world = (picks.get("世界观") or "").strip()
    if world:
        landed += _land_candidate_sections(root, paths.WORLD_REL, paths.WORLD_DIR_REL, world,
                                            drop_unnamed=False)
    chars = _reheader_protagonist(picks.get("人物卡") or "", (picks.get("protagonist") or "").strip())
    if chars.strip():
        landed += _land_candidate_sections(root, paths.CHARS_REL, paths.CHARS_DIR_REL, chars,
                                            drop_unnamed=True)
    card = (picks.get("卡章纲") or "").strip()
    if card:
        landed.append(_apply_card_lines(root, card))   # fallback 默认空:候选撞车丢弃,不强塞
    return {"landed": landed}


def _reheader_protagonist(chars_body: str, protagonist: str) -> str:
    """把候选人物卡里名字全等 protagonist 的那节标题归一「## 主角 · 名字」(全等,免子串误吞同姓 沈砚/沈砚秋)。"""
    if not protagonist:
        return chars_body

    def _fix(m):
        head = m.group(0)
        body = head.lstrip("#").strip()          # 「类型 · 名字」或「名字」
        name = body
        for sep in ("·", "・", "•"):
            if sep in body:
                name = body.split(sep, 1)[1].strip()
                break
        return f"## 主角 · {protagonist}" if name == protagonist else head

    return re.sub(r"^##\s*[^\n]*$", _fix, chars_body, flags=re.M)


def scan(root: Path, backend) -> dict:
    """读采样章 → LLM 出三段候选 dict(世界观/人物卡/卡章纲);不落盘。无章 → {};
    后端失败(欠费/断网/超时)自然上抛,由调用端点 catch→_err_json 带 code,不吞成假的「没提炼到」。"""
    sample = _sample_chapters(root)
    if not sample:
        return {}
    user = f"作者已写好的小说正文(采样):\n\n{sample}\n\n按三段格式,把正文里已有的设定提炼成候选。"
    raw = backend.complete(_SYSTEM, user, max_chars=_MAX_CHARS)   # 失败自然上抛,端点→_err_json带code
    return split_brain_draft(raw)   # {"世界观":..,"人物卡":..,"卡章纲":..},缺段不进;不成三段则 {}(垃圾输出降级)
