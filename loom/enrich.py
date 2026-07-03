"""外置大脑增量补全:learn 接受一章后,从【手改定稿】里蒸馏出【这章新冒出来的】
世界观设定 / 人物信息,以物理隔离的「[AI补充]」块【追加】到 世界观.md / 人物卡.md。

让外置大脑真正"随故事生长"(CONTEXT),但人始终拥有最终所有权。和 recap(写后摘要)
同源、同红线:
- 只读手改定稿(正文/第N章.md),不是 .原稿 快照。
- 只管 what(设定/人物),绝不喂写作指纹(红线①,见 ADR 0001/0002)。
- write-once:同章重复 learn 不重复追加(红线②,人写优先)。
- 只【追加】到文件末尾的 [AI补充] 区,逐字保留作者手写的上文,绝不改、绝不覆盖。
- 不引入实体库/打分/向量(红线③)。
- 删章时连同 [AI回顾] 一起清掉本章的 [AI补充](见 chapters.delete_chapter),
  否则同号重新生成后会被 write-once 挡住、留着已删旧章的设定。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .backends import Backend
from .fsutil import atomic_write_text
from .paths import CHARS_REL, WORLD_REL, chapter_path

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass
_SUPP_SECTION = "## AI 补充(loom learn 后随章自动追加,你可改可删;绝不覆盖你上面手写的)"

_ENRICH_SYSTEM = """你是设定连续性记录员。我给你:① 现有【世界观】;② 现有【人物卡】;③ 这一章的【作者定稿正文】。

只挑出这一章里【新冒出来、且现有世界观/人物卡里还没记下】的硬设定与人物信息(管 what,不评文笔、不复述剧情过程)。\
已经记过的、纯剧情流水、临时情绪,一律不要。每条写成一句具体、可回查的短句。

严格按下面两段输出,只输出这两段、不要任何解释;某段确实没有新东西,就在该段下只写「- 无」:

【世界观补充】
- (新规则/新力量层级/新地点/新势力/新金手指代价/新埋的世界级伏笔…)

【人物卡补充】
- 人物名:这章新确立的身份/能力/关系/动机/底线(新人物,或对已有人物的新事实)"""


def _already_supplemented(text: str, n: int) -> bool:
    return f"[AI补充·第{n}章]" in text


def _clean_section(body: str) -> str:
    """只留 `- ` 条目行,滤掉「无」占位与空行;返回干净的多行块(可能为空串)。"""
    keep: list[str] = []
    for raw in body.splitlines():
        s = raw.strip()
        if not s.startswith(("-", "•", "・")):
            continue
        inner = s.lstrip("-•・ ").strip()
        if not inner or inner in ("无", "无。", "(无)", "(无)"):
            continue
        keep.append("- " + inner)
    return "\n".join(keep)


def _parse_sections(raw: str) -> tuple[str, str]:
    """把 LLM 两段输出拆成 (世界观补充, 人物卡补充);各自已清洗,空段返回空串。"""
    text = raw.strip()
    wm = re.search(r"【世界观补充】\s*(.*?)(?=【人物卡补充】|$)", text, re.DOTALL)
    cm = re.search(r"【人物卡补充】\s*(.*)$", text, re.DOTALL)
    world = _clean_section(wm.group(1)) if wm else ""
    chars = _clean_section(cm.group(1)) if cm else ""
    return world, chars


def _append_supplement(text: str, n: int, body: str) -> str | None:
    """把 body 作为「### [AI补充·第N章]」块追加到文末;已存在(write-once)返回 None。"""
    if _already_supplemented(text, n):
        return None
    out = text.rstrip("\n")
    if _SUPP_SECTION not in out:
        out += "\n\n" + _SUPP_SECTION
    out += f"\n\n### [AI补充·第{n}章]\n{body.rstrip()}\n"
    return out


def enrich_chapter(project_root: Path, chapter_n: int,
                   backend: Backend, progress: Progress = _noop) -> dict | None:
    """从第 N 章定稿蒸馏新设定/新人物,追加进世界观/人物卡。返回本次追加的 {世界观, 人物卡}。"""
    final_path = chapter_path(project_root, chapter_n)
    if not final_path.exists():
        return None  # 没正文不报错(enrich 是附赠,绝不阻断 learn)
    world_path = project_root / WORLD_REL
    chars_path = project_root / CHARS_REL
    if not world_path.exists() and not chars_path.exists():
        return None

    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""
    w_done = bool(world) and _already_supplemented(world, chapter_n)
    c_done = bool(chars) and _already_supplemented(chars, chapter_n)
    # 两边都没处可补(文件缺失)或都已补过这章 → 跳过,连一次 LLM 都不浪费
    if (not world_path.exists() or w_done) and (not chars_path.exists() or c_done):
        progress({"type": "enrich_skip", "chapter": chapter_n})
        return None

    final = final_path.read_text(encoding="utf-8").strip()
    progress({"type": "info", "message": f"正在看第 {chapter_n} 章给世界观/人物卡补设定…"})
    user = (f"## 现有世界观\n{world.strip() or '(还没有)'}\n\n"
            f"## 现有人物卡\n{chars.strip() or '(还没有)'}\n\n"
            f"## 第 {chapter_n} 章定稿正文\n{final}")
    raw = backend.complete(_ENRICH_SYSTEM, user, max_chars=700)
    if not raw.strip():  # 模型没产出 → 干净跳过(附赠功能,绝不阻断、也不吓人)
        progress({"type": "enrich_skip", "chapter": chapter_n})
        return None
    world_body, chars_body = _parse_sections(raw)

    result = {"chapter": chapter_n, "世界观": "", "人物卡": ""}
    if world_path.exists() and not w_done and world_body:
        new = _append_supplement(world, chapter_n, world_body)
        if new is not None:
            atomic_write_text(world_path, new)
            result["世界观"] = world_body
    if chars_path.exists() and not c_done and chars_body:
        new = _append_supplement(chars, chapter_n, chars_body)
        if new is not None:
            atomic_write_text(chars_path, new)
            result["人物卡"] = chars_body

    if result["世界观"] or result["人物卡"]:
        progress({"type": "enrich_done", "chapter": chapter_n,
                  "世界观": result["世界观"], "人物卡": result["人物卡"]})
    else:
        progress({"type": "enrich_skip", "chapter": chapter_n})
    return result


def extract_supplement(text: str, n: int) -> str:
    """从一份文件文本里取出第 N 章的 [AI补充] 块正文(给界面展示);没有则空串。"""
    lines = text.splitlines()
    head = f"[AI补充·第{n}章]"
    for i, ln in enumerate(lines):
        if head in ln and ln.lstrip().startswith("#"):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("#"):   # 到下一个标题(下一章块/别的小节)即止
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    return ""


def _supp_span(lines: list[str], n: int) -> tuple[int, int] | None:
    """定位第 N 章 [AI补充] 块的行区间 [start, end);含其后空行,到下一个标题/EOF 止。"""
    head = f"[AI补充·第{n}章]"
    for i, ln in enumerate(lines):
        if head in ln and ln.lstrip().startswith("#"):
            k = i + 1
            while k < len(lines) and not lines[k].lstrip().startswith("#"):
                k += 1
            return i, k
    return None


def _strip_one(path: Path, n: int) -> str | None:
    """从单个文件里删掉第 N 章的 [AI补充] 块;若删完整个 [AI补充] 区已空,连区头一起清掉。
    返回被删文本,没有则 None。"""
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    span = _supp_span(lines, n)
    if span is None:
        return None
    s, e = span
    removed = "\n".join(lines[s:e]).strip()
    lines = lines[:s] + lines[e:]
    # 该章是最后一块 → [AI补充] 区已空,把区头也清掉(连同其前后空行收尾)
    if not any("[AI补充·第" in ln for ln in lines):
        lines = [ln for ln in lines if ln.strip() != _SUPP_SECTION.strip()]
    new = "\n".join(lines).rstrip("\n")
    atomic_write_text(path, (new + "\n") if raw.endswith("\n") else new)
    return removed


def strip_supplement(project_root: Path, chapter_n: int) -> str | None:
    """删章时:清掉第 N 章在世界观/人物卡里的 [AI补充] 块(只删 loom 写的,留作者手写)。
    返回被删内容拼合(供回收站留底),没有则 None。"""
    parts: list[str] = []
    for rel in (WORLD_REL, CHARS_REL):
        removed = _strip_one(project_root / rel, chapter_n)
        if removed:
            parts.append(f"【{rel}】\n{removed}")
    return "\n\n".join(parts) if parts else None
