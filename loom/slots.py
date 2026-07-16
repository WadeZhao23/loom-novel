"""槽位扫描器:把外置大脑的骨架行读成可寻址的槽位(容器×键)。

槽位真相 = 书里的文件正文,不是代码侧的表:作者删掉一行骨架,那个槽就没了。
纯派生、零存储、零模型、每次现算。五种 at:line/h2/row(本文件)+ filename/file(见下)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .journey import StageSpec, _CARD_FIELDS, _h2_body
from .parse import _EMPTY_ROW_RE, _PAREN_SPAN_RE, is_substantive

_ROW_RE = re.compile(r"^-\s*([^:：(（]+?)\s*(?:[(（][^)）]*[)）])?\s*[:：](.*)$")
# 捕获:键(冒号/括注前的名)、括注后冒号后的正文。hint 另取括注原文。
_HINT_RE = re.compile(r"[(（]([^)）]*)[)）]")
_PLATFORM_RE = re.compile(r"^平台[ \t]*[:：][ \t]*(.*)$", re.M)


def _preview(val: str) -> str:
    return val.strip()[:24]


def _row_slots(root: Path, rel: str) -> list[Slot]:
    """一个骨架行文件 → row 槽(每 - 键: 行一个)。"""
    p = root / rel
    if not p.is_file():
        return []
    out: list[Slot] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        # hint 只从「键到冒号」的模板部分找括注,不进冒号后的用户值——用同一次 _ROW_RE 匹配
        # 定位那个终结键的冒号(m.start(2) 前一个字符),不用字符串切分:括注内本就可能含冒号
        # (如「核心功能(补主角哪块短板:资源…):」),按冒号切分会把这类括注切断。
        before_colon = line[:m.start(2) - 1]
        hm = _HINT_RE.search(before_colon)
        # 「空表单行」判定复用 is_substantive 的口径:剥括注后冒号后无实字 = 空
        filled = bool(_PAREN_SPAN_RE.sub("", line).split("：")[-1].split(":")[-1].strip()) or bool(val)
        out.append(Slot(id=f"{rel}#{key}", label=key[:10], container=rel, at="row",
                        key=key, hint=hm.group(1).strip() if hm else "",
                        filled=filled, preview=_preview(val)))
    return out


@dataclass(frozen=True)
class Slot:
    id: str        # "<容器rel>#<键>"
    label: str     # ≤10 字,实体容器带前缀
    container: str # 容器文件 rel
    at: str        # "line"|"h2"|"row"|"filename"|"file"
    key: str       # 行/H2 键;filename="@name";file="@body"
    hint: str      # 模板括注原文(喂 prompt,不上屏)
    filled: bool
    preview: str   # 已填值前 24 字


def _project_slots(root: Path) -> list[Slot]:
    """立项卡:平台行(line)+ 四个 H2(h2)。"""
    rel = paths.PROJECT_CARD_REL
    p = root / rel
    text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    out: list[Slot] = []
    pm = _PLATFORM_RE.search(text)
    plat_val = pm.group(1).strip() if pm else ""
    out.append(Slot(id=f"{rel}#平台", label="平台", container=rel, at="line", key="平台",
                    hint="发哪个平台", filled=bool(plat_val), preview=_preview(plat_val)))
    for f in _CARD_FIELDS:
        body = _h2_body(text, f)
        out.append(Slot(id=f"{rel}#{f}", label=f, container=rel, at="h2", key=f,
                        hint="", filled=is_substantive(body), preview=_preview(body)))
    return out


def stage_slots(root: Path, spec: StageSpec) -> list[Slot]:
    if spec.key == "立项":
        return _project_slots(root)
    if spec.key == "世界观":
        # 目录里每个 .md 文件按 slot_order 收 row 槽(filename/file 兜底见 Task 3)
        slots: list[Slot] = []
        base = paths.WORLD_DIR_REL
        for stem in spec.slot_order:
            slots += _row_slots(root, f"{base}/{stem}.md")
        return slots
    return []   # 人物/卡章纲/voice 留后续任务
