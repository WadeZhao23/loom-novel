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

from .backends import Backend
from .config import load_config
from .fsutil import atomic_write_text

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


_SECTIONS = [("世界观", "外置大脑/世界观.md"),
             ("人物卡", "外置大脑/人物卡.md"),
             ("卡章纲", "外置大脑/卡章纲.md")]

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
    """文件缺失 / 空 / 还是占位模板(含「占位示例」「待 seed/填充」)→ 可安全覆盖;否则保留作者内容。"""
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return True
    return ("占位示例" in text) or ("待 seed" in text) or ("待填充" in text)


def _split(raw: str) -> dict:
    out: dict = {}
    for key in ("世界观", "人物卡", "卡章纲"):
        m = re.search(rf"==={key}===\s*(.*?)(?=\n===|\Z)", raw, re.DOTALL)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()
    return out


def draft_brain(project_root: Path, idea: str, backend: Backend, progress: Progress = _noop) -> dict:
    """起草三件套并落盘(只覆盖空白/模板文件)。返回 {被写入的名字: 内容}。"""
    cfg = load_config(project_root)
    title = (cfg.title or "").strip() or "（未命名）"
    genre = _genre(project_root)
    progress({"type": "info", "message": "AI 正在起草 世界观 / 人物卡 / 卡章纲…"})
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
        if not body:
            continue
        path = project_root / rel
        if not _is_blank_or_template(path):     # 你已经填了真内容 → 不覆盖,跳过
            skipped.append(key)
            continue
        header = f"# {key}\n\n> AI 起草的初稿——改成你自己的。每条都可删可改。\n\n"
        atomic_write_text(path, header + body.strip() + "\n")
        written[key] = body
    progress({"type": "draft_done", "written": list(written.keys()), "skipped": skipped})
    return {"written": written, "skipped": skipped}
