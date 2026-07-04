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

from pathlib import Path
from typing import Callable

from . import events
from .backends import Backend
from .fsutil import atomic_write_text
from .parse import parse_enrich_sections as _parse_sections  # 读侧解析共置 parse.py(S7)
from . import paths
from .paths import CHARS_REL, WORLD_REL, chapter_path

# [AI补充] 可能住的全部文件(重映射/删章清理都扫这一份清单;缺失的自动跳过):
# 老书=世界观.md/人物卡.md 文末;目录形态=各目录的 成长档案.md(AI 自留地,物理隔离)
_SUPP_RELS = (WORLD_REL, CHARS_REL,
              f"{paths.WORLD_DIR_REL}/{paths.GROWTH_NAME}",
              f"{paths.CHARS_DIR_REL}/{paths.GROWTH_NAME}")

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


def _supp_head(n: int) -> str:
    """第 N 章 [AI补充] 块的标题键——write-once 判定 / 删除 / 重编号都认这一个键。"""
    return f"[AI补充·第{n}章]"


def _already_supplemented(text: str, n: int) -> bool:
    return _supp_head(n) in text


def _append_supplement(text: str, n: int, body: str) -> str | None:
    """把 body 作为「### [AI补充·第N章]」块追加到文末;已存在(write-once)返回 None。"""
    if _already_supplemented(text, n):
        return None
    out = text.rstrip("\n")
    if _SUPP_SECTION not in out:
        out += "\n\n" + _SUPP_SECTION
    out += f"\n\n### {_supp_head(n)}\n{body.rstrip()}\n"
    return out


def _supp_target(project_root: Path, file_rel: str, dir_rel: str) -> tuple[Path | None, str, str]:
    """AI 补充的落点与上下文:(写入文件, write-once 检查文本, 喂 LLM 的现有内容)。

    老书单文件 → 追加到该文件文末(既有行为);目录形态 → 落 成长档案.md(AI 自留地,
    物理隔离,永不碰人写的文件),上下文=整个目录拼起来(模型要知道已有设定才不重复补)。"""
    form = paths.brain_form(project_root, file_rel, dir_rel)
    if form == "file":
        p = project_root / file_rel
        text = p.read_text(encoding="utf-8")
        return p, text, text
    if form == "dir":
        ctx = "\n\n".join(f.read_text(encoding="utf-8")
                          for f in paths.brain_dir_files(project_root, dir_rel))
        g = project_root / dir_rel / paths.GROWTH_NAME
        return g, (g.read_text(encoding="utf-8") if g.is_file() else ""), ctx
    return None, "", ""


def enrich_chapter(project_root: Path, chapter_n: int,
                   backend: Backend, progress: Progress = _noop) -> dict | None:
    """从第 N 章定稿蒸馏新设定/新人物,追加进世界观/人物卡(目录形态落成长档案)。"""
    final_path = chapter_path(project_root, chapter_n)
    if not final_path.exists():
        return None  # 没正文不报错(enrich 是附赠,绝不阻断 learn)
    world_path, world_target, world_ctx = _supp_target(project_root, WORLD_REL, paths.WORLD_DIR_REL)
    chars_path, chars_target, chars_ctx = _supp_target(project_root, CHARS_REL, paths.CHARS_DIR_REL)
    if world_path is None and chars_path is None:
        return None

    w_done = bool(world_target) and _already_supplemented(world_target, chapter_n)
    c_done = bool(chars_target) and _already_supplemented(chars_target, chapter_n)
    # 两边都没处可补或都已补过这章 → 跳过,连一次 LLM 都不浪费
    if (world_path is None or w_done) and (chars_path is None or c_done):
        progress(events.enrich_skip(chapter_n))
        return None

    final = final_path.read_text(encoding="utf-8").strip()
    progress(events.info(f"正在看第 {chapter_n} 章给世界观/人物卡补设定…"))
    user = (f"## 现有世界观\n{world_ctx.strip() or '(还没有)'}\n\n"
            f"## 现有人物卡\n{chars_ctx.strip() or '(还没有)'}\n\n"
            f"## 第 {chapter_n} 章定稿正文\n{final}")
    raw = backend.complete(_ENRICH_SYSTEM, user, max_chars=700)
    if not raw.strip():  # 模型没产出 → 干净跳过(附赠功能,绝不阻断、也不吓人)
        progress(events.enrich_skip(chapter_n))
        return None
    world_body, chars_body = _parse_sections(raw)

    result = {"chapter": chapter_n, "世界观": "", "人物卡": ""}
    if world_path is not None and not w_done and world_body:
        new = _append_supplement(world_target, chapter_n, world_body)
        if new is not None:
            atomic_write_text(world_path, new)
            result["世界观"] = world_body
    if chars_path is not None and not c_done and chars_body:
        new = _append_supplement(chars_target, chapter_n, chars_body)
        if new is not None:
            atomic_write_text(chars_path, new)
            result["人物卡"] = chars_body

    if result["世界观"] or result["人物卡"]:
        progress(events.enrich_done(chapter_n, result["世界观"], result["人物卡"]))
    else:
        progress(events.enrich_skip(chapter_n))
    return result


def extract_supplement(text: str, n: int) -> str:
    """从一份文件文本里取出第 N 章的 [AI补充] 块正文(给界面展示);没有则空串。"""
    lines = text.splitlines()
    head = _supp_head(n)
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
    head = _supp_head(n)
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
    for rel in _SUPP_RELS:
        removed = _strip_one(project_root / rel, chapter_n)
        if removed:
            parts.append(f"【{rel}】\n{removed}")
    return "\n\n".join(parts) if parts else None


def remap_supplement_keys(project_root: Path, mapping: dict[int, int]) -> None:
    """章节重编号时:把世界观/人物卡里 [AI补充·第N章] 的章号键按 {old: new} 重映射。

    两段式(old→占位→new,与 chapters._renumber 搬文件同法)防 2↔3 互换时新键撞旧键;
    只改块标题行上的章号键,块内容与位置一字不动,人手写的主体更不碰。
    不重映射的后果是真 bug:键还指旧章号 → learn 被 write-once 挡住、界面显示错章的设定。
    """
    mapping = {o: n for o, n in mapping.items() if o != n}
    if not mapping:
        return
    for rel in _SUPP_RELS:
        path = project_root / rel
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        hit = False
        for i, ln in enumerate(lines):          # 段一:old → 占位键(先全摘下)
            if not ln.lstrip().startswith("#"):
                continue                        # 只认标题行上的键(与 _supp_span 同口径)
            for old in mapping:
                if _supp_head(old) in ln:
                    lines[i] = ln.replace(_supp_head(old), f"[AI补充·第__rn{old}__章]")
                    hit = True
                    break
        if not hit:
            continue
        for i, ln in enumerate(lines):          # 段二:占位 → new
            for old, new in mapping.items():
                ph = f"[AI补充·第__rn{old}__章]"
                if ph in ln:
                    lines[i] = ln.replace(ph, _supp_head(new))
                    break
        atomic_write_text(path, "\n".join(lines) + ("\n" if raw.endswith("\n") else ""))
