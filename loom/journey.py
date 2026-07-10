"""创作旅程状态机:领航员访谈的阶段表 + 完成谓词 + 薄游标。

设计(docs/superpowers/specs/2026-07-10-journey-partner-design.md、ADR 0013):
- 出题以文件现状为准,不以问答历史为准;游标可丢弃(坏了当无,谓词重推)。
- 创作产出只落外置大脑 md(单一真相);游标只存不可派生的最少字段。
- 拓扑住代码侧表(同 agents.STEPS 模式),不下放用户可编辑文件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .parse import is_substantive
from .state import load_state, save_state

_MAX_QUESTIONS = 4   # 每段题数预算(交互从简;代码侧常量,不进 loom.toml)


@dataclass(frozen=True)
class StageSpec:
    key: str                  # 阶段名(面板展示 + 游标键)
    goal: str                 # 出题目标一句话,进领航员 user prompt
    reads: tuple[str, ...]    # 出题上下文(rel;也是缓存卡签名源;目录=读整目录)
    land: str                 # 落盘模式:field | sections | card_lines | seed
    target: str = ""          # field/card_lines 的目标文件;sections 的单文件形态
    target_dir: str = ""      # sections 的目录形态


STAGES: tuple[StageSpec, ...] = (
    StageSpec("立项", "问清这本书的定位:平台/分区/题材/对标意图/为什么选它",
              (paths.PROJECT_CARD_REL,), "field", target=paths.PROJECT_CARD_REL),
    StageSpec("世界观", "问出核心世界观:力量体系、金手指及其代价、关键地理与势力",
              (paths.WORLD_REL, paths.WORLD_DIR_REL), "sections",
              target=paths.WORLD_REL, target_dir=paths.WORLD_DIR_REL),
    StageSpec("人物", "问出主角与关键配角/反派:名字、动机、底牌、软肋",
              (paths.CHARS_REL, paths.CHARS_DIR_REL), "sections",
              target=paths.CHARS_REL, target_dir=paths.CHARS_DIR_REL),
    StageSpec("卡章纲", "问出开局钩子、前 5 章一句话章纲、全书大弧",
              (paths.CARD_REL,), "card_lines", target=paths.CARD_REL),
    StageSpec("voice", "喂 2-3 段你的真实样本让指纹像你(走 seed,不出题)",
              (), "seed"),
)
_STAGE_KEYS = tuple(s.key for s in STAGES)

_CARD_FIELDS = ("分区", "题材", "对标意图", "为什么选它")
_CARD_LINE_RE = re.compile(r"^-\s*第(\d+)章[:：][ \t]*\S", re.M)


def _stage_spec(key: str) -> StageSpec:
    for s in STAGES:
        if s.key == key:
            return s
    raise ValueError(f"未知阶段:{key}")


# ---- 完成谓词(全部文件派生,零存储) ----

def _h2_body(text: str, title: str) -> str:
    m = re.search(rf"^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def _project_card_done(root: Path) -> bool:
    """任一格有实质内容即算(模板自带的「平台:起点」默认行不算)。"""
    p = root / paths.PROJECT_CARD_REL
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    return any(is_substantive(_h2_body(text, f)) for f in _CARD_FIELDS)


def _rel_has_content(root: Path, rel: str) -> bool:
    p = root / rel
    if p.is_dir():
        return any(f.name != paths.GROWTH_NAME and is_substantive(f.read_text(encoding="utf-8"))
                   for f in sorted(p.glob("*.md")))
    return p.is_file() and is_substantive(p.read_text(encoding="utf-8"))


def stage_done(root: Path, spec: StageSpec) -> bool:
    if spec.land == "seed":
        return load_state(root).get("fingerprint_source", "default") != "default"
    if spec.land == "field":
        return _project_card_done(root)
    if spec.land == "card_lines":
        p = root / spec.target
        return p.is_file() and bool(_CARD_LINE_RE.search(p.read_text(encoding="utf-8")))
    return any(_rel_has_content(root, rel) for rel in spec.reads)


# ---- 薄游标(挂 .loom_state.json 的 journey 键;整键可丢弃) ----

def _journey(st: dict) -> dict:
    j = st.get("journey")
    if not isinstance(j, dict):
        j = {}
    j.setdefault("skips", {})
    j.setdefault("asked", {})   # {stage: 已出题数}
    j.setdefault("card", None)  # 待答卡缓存 {stage,sig,question,options,...}
    j.setdefault("focus", "")   # goto 显式聚焦(空=按顺序派生)
    return j


def journey_state(root: Path) -> dict:
    st = load_state(root)
    j = _journey(st)
    stages = [{"key": s.key, "land": s.land,
               "done": stage_done(root, s),
               "skipped": bool(j["skips"].get(s.key)),
               "asked": int(j["asked"].get(s.key, 0))}
              for s in STAGES]
    open_keys = [x["key"] for x in stages if not x["done"] and not x["skipped"]]
    current = j["focus"] if j["focus"] in open_keys else ""
    if not current:
        nxt = next((x for x in stages if x["key"] in open_keys and x["asked"] < _MAX_QUESTIONS), None)
        current = nxt["key"] if nxt else ""
    card = j["card"] if (j["card"] and j["card"].get("stage") == current) else None
    return {"stages": stages, "current": current or None, "card": card}


def goto(root: Path, stage: str, *, skip: bool = False) -> dict:
    _stage_spec(stage)   # 未知段名即 ValueError
    st = load_state(root)
    j = _journey(st)
    if skip:
        j["skips"][stage] = True
        if j["focus"] == stage:
            j["focus"] = ""
    else:
        j["skips"].pop(stage, None)
        j["focus"] = stage
        j["asked"][stage] = 0   # 回头改=重开本段预算
    if j["card"] and j["card"].get("stage") == stage:
        j["card"] = None        # 换段/跳段即作废待答卡
    st["journey"] = j
    save_state(root, st)
    return journey_state(root)


# ---- 领航员(第六个角色;项目文件优先、包内模板回退——同 deconstruct._load_skill 先例) ----

def _navigator_system(root: Path) -> str:
    from .agents import _parse_frontmatter   # 薄别名惯例(同 draft.py 之于 parse.py)
    local = root / "agents" / "领航员.md"
    path = local if local.exists() else Path(__file__).parent / "templates" / "agents" / "领航员.md"
    _, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return body
