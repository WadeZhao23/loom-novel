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

# 立项卡四个 H2 格的 hint(素材来自模板占位 loom/templates/外置大脑/立项卡.md,提炼成短句):
# 模板本身对这四格没有像 row 槽那样的行内括注可抓,之前一直是空 hint——真机暴露的缺陷正是
# 由此而来(模型不知道「分区」是什么,把平台名塞进分区槽)。
_CARD_FIELD_HINTS = {
    "分区": "投稿分区/题材归类(如玄幻·东方玄幻),不是平台",
    "题材": "核心题材标签,如重生+复仇+宗门流",
    "对标意图": "想写成哪本书那种爽感节奏",
    "为什么选它": "选这个定位的理由/初心备忘",
}


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
    for f in _CARD_FIELDS:
        body = _h2_body(text, f)
        out.append(Slot(id=f"{rel}#{f}", label=f, container=rel, at="h2", key=f,
                        hint=_CARD_FIELD_HINTS.get(f, ""), filled=is_substantive(body), preview=_preview(body)))
    # 平台挪到立项最后一格(FB-平台):建书不再逼选/预填平台,领航员先聊分区/题材/对标(创作的),
    # 平台留最后、可选可跳(它只影响违禁词自检松紧,非阻断;作者不填就用默认档)。
    pm = _PLATFORM_RE.search(text)
    plat_val = pm.group(1).strip() if pm else ""
    out.append(Slot(id=f"{rel}#平台", label="平台", container=rel, at="line", key="平台",
                    hint="发哪个平台(可选)", filled=bool(plat_val), preview=_preview(plat_val)))
    return out


def _container_slots(root: Path, rel: str, *, entity: bool) -> list[Slot]:
    """一个容器文件 → 槽位。entity=True(人物)时未命名出 filename 槽、压住 row。"""
    p = root / rel
    if not p.is_file():
        return []
    stem = Path(rel).stem
    text = p.read_text(encoding="utf-8", errors="replace")
    if entity and "未命名" in stem:
        role = stem.split("·")[0].split("・")[0].split("•")[0]
        return [Slot(id=f"{rel}#@name", label=f"给{role}起个名字"[:10], container=rel,
                     at="filename", key="@name", hint="改文件名为「类型·名字」,逐字直送写手",
                     filled=False, preview="")]
    rows = _row_slots(root, rel)
    if rows:
        if entity:   # 实体容器:label 带名字前缀「林潜 · 软肋」
            name = stem
            for sep in ("·", "・", "•"):
                if sep in name:
                    name = name.split(sep, 1)[-1]
                    break
            rows = [Slot(id=s.id, label=f"{name} · {s.key}"[:10], container=s.container,
                         at=s.at, key=s.key, hint=s.hint, filled=s.filled, preview=s.preview)
                    for s in rows]
        return rows
    # 无 row、无可寻址骨架 → file 兜底
    quote = next((l[1:].strip() for l in text.splitlines() if l.startswith(">")), "")
    return [Slot(id=f"{rel}#@body", label=stem[:10], container=rel, at="file", key="@body",
                 hint=quote, filled=is_substantive(text), preview=_preview(text))]


def _dir_container_slots(root: Path, dir_rel: str, order: tuple[str, ...], *, entity: bool) -> list[Slot]:
    """目录段(世界观/人物):按 order 收各容器槽,再 round-robin 交错未填槽。"""
    per: list[list[Slot]] = []
    files = [f for f in paths.brain_dir_files(root, dir_rel) if f.name != paths.GROWTH_NAME]
    def rank(f: Path) -> int:
        for i, stem in enumerate(order):
            if f.stem.startswith(stem):
                return i
        return len(order)
    for f in sorted(files, key=rank):
        per.append(_container_slots(root, f"{dir_rel}/{f.name}", entity=entity))
    # round-robin:逐容器取第 k 个,交错拼;filled 与未填分开(未填优先展示由消费方决定,这里只保稳定序)
    out: list[Slot] = []
    for k in range(max((len(x) for x in per), default=0)):
        for x in per:
            if k < len(x):
                out.append(x[k])
    return out


def stage_slots(root: Path, spec: StageSpec) -> list[Slot]:
    if spec.key == "立项":
        return _project_slots(root)
    if spec.key == "世界观":
        return _dir_container_slots(root, paths.WORLD_DIR_REL, spec.slot_order, entity=False)
    if spec.key == "人物":
        return _dir_container_slots(root, paths.CHARS_DIR_REL, spec.slot_order, entity=True)
    if spec.key == "卡章纲":
        return _row_slots(root, paths.CARD_REL)   # 章行「- 第N章:」/「- 大弧:」都是 row 形态
    return []   # voice:P2 需要时再加
