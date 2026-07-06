"""外置大脑初稿:从书名 + 题材 + 你的一句话设定,AI 一次性起草 世界观/人物卡/卡章纲 三件套,
让你不必对着空模板发呆——之后在编辑器里改成你的。

和 [AI补充](enrich,learn 后随章追加)不同:这是【开局铺底稿】的一次性动作。
红线:只起草【人维护】的设定/人物/规划草稿,绝不碰写作指纹(voice);只覆盖空白/占位模板,
不动你已经写进去的真内容(防手滑覆盖)。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import events, paths
from .backends import Backend
from .config import load_config
from .fsutil import atomic_write_text
from .guard import DRAFT_SECTION, validate_output
from .parse import PLACEHOLDER_MARKS, split_brain_draft as _split  # 读侧解析共置 parse.py(S7),薄别名保引用面
from .paths import CARD_REL, CHARS_REL, WORLD_REL

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


_SECTIONS = [("世界观", WORLD_REL),
             ("人物卡", CHARS_REL),
             ("卡章纲", CARD_REL)]

_DRAFT_SYSTEM = """你是资深网文设定师。根据【书名 + 题材 + 作者的一句话设定】,起草三份【外置大脑】底稿,\
给作者一个不空的起点(是初稿、不是定稿,作者会接着改)。严格按下面三段输出,用三个分隔标记隔开,\
每段都是可直接落盘的中文 Markdown,具体、能落地、有网文爽感,别写空话:

===世界观===
## 一句话定位
（情绪基调 + 核心冲突）
## 力量体系
（体系名 + 7~9 个等级,每级有可见代价/异化）
## 金手指
（类型 / 核心功能 / 触发条件 / 至少一种硬代价 / 敌人怎么反制 / 升级路径）
## 地理 / 势力
（安全区、危险区、对立势力各一两条）
## 冰山真相
（这个世界藏着的终极秘密一句话）

===人物卡===
## 主角 · <名字>
- 核心欲望 / 缺陷软肋 / 不可退让的底线 / 说话风格 / 一秒反差标签
## 配角 · <名字>
- 立场 / 功能 / 小目标
## 反派 · <名字>
- 对主角的真实威胁 / “合理的恶”（让读者理解但不认同的动机）

===卡章纲===
（前 5 章,每章一行,格式「- 第N章:这章完成什么 + 章末抛什么钩子」;前三章要有清晰的爽点闭环）
- 第1章:
- 第2章:
- 第3章:
- 第4章:
- 第5章:"""


def _genre(project_root: Path) -> str:
    """读项目里选定的题材(skills/题材 下那一份);没有则空。"""
    d = project_root / "skills" / "题材"
    if d.is_dir():
        for f in sorted(d.glob("*.md")):
            if f.stem != "README":
                return f.stem
    return ""


def _is_blank_or_template(path: Path) -> bool:
    """文件缺失 / 空 / 还是占位模板(含占位标记)→ 可安全覆盖;否则保留作者内容。"""
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return True
    return any(m in text for m in PLACEHOLDER_MARKS)


def draft_brain(project_root: Path, idea: str, backend: Backend, progress: Progress = _noop) -> dict:
    """起草三件套并落盘(只覆盖空白/模板文件)。返回 {被写入的名字: 内容}。"""
    cfg = load_config(project_root)
    title = (cfg.title or "").strip() or "（未命名）"
    genre = _genre(project_root)
    progress(events.info("AI 正在起草 世界观 / 人物卡 / 卡章纲…"))
    user = (
        f"书名:{title}\n"
        f"题材:{genre or '（未指定，自己挑一个适合的网文题材）'}\n"
        f"作者的一句话设定:{idea.strip() or '（作者没写——就按书名+题材发挥一个有爽点、能长期写下去的网文设定）'}\n\n"
        f"请按要求起草三份底稿。"
    )
    raw = backend.complete(_DRAFT_SYSTEM, user, max_chars=2600)
    parts = _split(raw)

    written: dict = {}
    skipped: list[str] = []
    for key, rel in _SECTIONS:
        body = parts.get(key, "")
        if not body or validate_output(body, DRAFT_SECTION):  # 缺这段/这段太短 → 跳过(逐段非空,不强求三段齐全)
            continue
        # 目录形态(世界观/、人物/):按 H2 拆节,一节(人)一文件;只写「不存在或仍是占位」的文件
        dir_rel = {"世界观": paths.WORLD_DIR_REL, "人物卡": paths.CHARS_DIR_REL}.get(key)
        if dir_rel and paths.brain_form(project_root, rel, dir_rel) == "dir":
            files = _write_sections_into_dir(project_root, dir_rel, body, drop_unnamed=(key == "人物卡"))
            if files:
                written[key] = body
            else:
                skipped.append(key)
            continue
        path = project_root / rel
        if not _is_blank_or_template(path):     # 你已经填了真内容 → 不覆盖,跳过
            skipped.append(key)
            continue
        header = f"# {key}\n\n> AI 起草的初稿——改成你自己的。每条都可删可改。\n\n"
        atomic_write_text(path, header + body.strip() + "\n")
        written[key] = body
    progress(events.draft_done(list(written.keys()), skipped))
    return {"written": written, "skipped": skipped}


_H2_SPLIT = re.compile(r"^## +", re.M)
_FN_BAD = re.compile(r'[\\/:*?"<>|]')


def _write_sections_into_dir(project_root: Path, dir_rel: str, body: str, *, drop_unnamed: bool) -> list[str]:
    """AI 起草的整份文本按 H2 拆进目录:文件名=节名(人物即「类型·名字」)。
    只写「不存在或仍是占位」的文件——作者写过真内容的一律不碰;
    人物起草成功后,顺手清掉仍是占位的「·未命名」模板卡(免得占位混着真人卡)。"""
    wrote: list[str] = []
    for seg in _H2_SPLIT.split(body)[1:]:
        title, _, sec = seg.partition("\n")
        name = _FN_BAD.sub("·", title.strip().replace(" ", ""))
        if not name:
            continue
        f = project_root / dir_rel / f"{name}.md"
        if not _is_blank_or_template(f):
            continue
        atomic_write_text(f, f"# {title.strip()}\n\n> AI 起草的初稿——改成你自己的。\n\n{sec.strip()}\n")
        wrote.append(name)
    if wrote and drop_unnamed:
        for f in (project_root / dir_rel).glob("*·未命名.md"):
            if _is_blank_or_template(f):
                f.unlink()
    return wrote
