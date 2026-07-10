# 全程写作伙伴 · 一期实施计划(journey.py + 领航员 + 起书访谈 + 伙伴面板)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 作者在伙伴面板上逐题回答领航员的问题卡,答案直接长成外置大脑 md——起书从"面对空模板"变"答题起书"。

**Architecture:** 新增薄旅程层 `loom/journey.py`(STAGES 冻结表 + 文件派生完成谓词 + `.loom_state.json` 薄游标),「领航员」为第六个 agent 角色(包内模板回退,老书免升级);4 个 JSON 端点走既有 server/usecases 模式;webui 现有五步旅程卡升级为伙伴面板。既有流水线零改动。设计依据:[spec](../specs/2026-07-10-journey-partner-design.md) 与 [ADR 0013](../../adr/0013-journey-orchestration-no-langgraph.md)。

**Tech Stack:** 纯 stdlib Python(dataclass/re/hashlib)+ 既有 loom 模块(state/paths/parse/guard/fsutil/draft/backends)+ vanilla JS。**零新依赖。**

## Global Constraints(每个任务隐含遵守)

- **零新依赖**:不引入 langgraph/langchain 或任何新包(ADR 0013 红线)。
- **md 单一真相**:访谈创作产出只落外置大脑 md;游标只存不可派生字段,坏了当无、从文件谓词重推(ledger 哲学)。
- **出题以文件现状为准**,不以问答历史为准。
- **人写优先**:任何落盘绝不覆盖已有实质内容(`parse.is_substantive` 判);只填空白/占位、或追加。
- **每段题数预算 = 4**(`_MAX_QUESTIONS = 4`,代码侧常量,不进 loom.toml)。
- **模型路由**:出题/消化走 `cheap_backend(cfg) or get_backend(cfg)`(既有惯例,agents.py:726 同款)。
- **失败降级不阻断**:出题失败 → 降级卡(自由输入);消化失败 → 答案原样落盘,绝不丢作者的话。
- **落盘全走 `atomic_write_text`**;LLM 产物先 `validate_output`(guard)。
- **领航员绝不发明设定**:选项是提案,作者拍板才落盘。
- 提交信息风格照仓库惯例(中文、`feat(journey): …`),每任务至少一次提交。
- 测试命令统一 `python3 -m pytest`(pyproject testpaths=tests)。

---

### Task 1: journey.py 状态骨架(STAGES 表 + 完成谓词 + 游标 + journey_state/goto)

**Files:**
- Create: `loom/journey.py`
- Test: `tests/test_journey.py`

**Interfaces:**
- Consumes: `paths.PROJECT_CARD_REL/WORLD_REL/WORLD_DIR_REL/CHARS_REL/CHARS_DIR_REL/CARD_REL/GROWTH_NAME`、`parse.is_substantive`、`state.load_state/save_state`(键 `journey` 新增,不改 state.py)
- Produces(后续任务依赖的确切签名):
  - `STAGES: tuple[StageSpec, ...]`,`StageSpec(key, goal, reads, land, target="", target_dir="")`(frozen dataclass)
  - `journey_state(root: Path) -> dict`——`{"stages": [{"key","land","done","skipped","asked"}...], "current": str|None, "card": dict|None}`
  - `goto(root: Path, stage: str, *, skip: bool = False) -> dict`(返回 journey_state;未知 stage 抛 ValueError)
  - `_journey(st: dict) -> dict`(游标读取,内部键 `skips/asked/card/focus`)
  - `_MAX_QUESTIONS = 4`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_journey.py
"""创作旅程状态机:阶段谓词/游标推进/跳段回跳/坏游标降级(ADR 0013:游标可丢弃、文件现状为准)。"""
from pathlib import Path

from loom import journey
from loom.paths import CARD_REL, PROJECT_CARD_REL


def test_fresh_project_stages_and_current(project):
    s = journey.journey_state(project)
    assert [x["key"] for x in s["stages"]] == ["立项", "世界观", "人物", "卡章纲", "voice"]
    assert all(not x["done"] for x in s["stages"])   # 模板书:占位不算内容
    assert s["current"] == "立项"
    assert s["card"] is None


def test_filled_worldview_marks_done(project):
    (project / "外置大脑/世界观/金手指.md").write_text(
        "# 金手指\n\n吞噬万物的胃袋,吃什么长什么,代价是饭量与寿命挂钩。\n", encoding="utf-8")
    s = journey.journey_state(project)
    world = next(x for x in s["stages"] if x["key"] == "世界观")
    assert world["done"] is True


def test_card_line_with_content_marks_done(project):
    p = project / CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:主角雪夜被逐出宗门,捡到会说话的鼎"),
                 encoding="utf-8")
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "卡章纲")["done"] is True


def test_project_card_platform_line_alone_not_done(project):
    # 模板自带「平台:起点」,不能算立项已完成
    assert next(x for x in journey.journey_state(project)["stages"] if x["key"] == "立项")["done"] is False


def test_skip_advances_current(project):
    s = journey.goto(project, "立项", skip=True)
    assert next(x for x in s["stages"] if x["key"] == "立项")["skipped"] is True
    assert s["current"] == "世界观"


def test_goto_refocuses_and_resets_budget(project):
    journey.goto(project, "立项", skip=True)
    s = journey.goto(project, "立项")           # 回头改
    assert s["current"] == "立项"
    assert next(x for x in s["stages"] if x["key"] == "立项")["skipped"] is False


def test_goto_unknown_stage_raises(project):
    import pytest
    with pytest.raises(ValueError):
        journey.goto(project, "不存在的段")


def test_broken_cursor_falls_back(project):
    (project / ".loom_state.json").write_text("{烂掉的json", encoding="utf-8")
    s = journey.journey_state(project)          # load_state 容错 → 当无游标
    assert s["current"] == "立项"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_journey.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'loom.journey'`(或 import error)

- [ ] **Step 3: 写实现**

```python
# loom/journey.py
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
_CARD_LINE_RE = re.compile(r"^-\s*第(\d+)章[:：]\s*\S", re.M)


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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_journey.py -v`
Expected: 8 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `python3 -m pytest`
Expected: 全部通过(旧测试零受影响)

```bash
git add loom/journey.py tests/test_journey.py
git commit -m "feat(journey): 旅程状态机骨架——STAGES 冻结表+文件派生谓词+薄游标(可丢弃,坏了谓词重推)"
```

---

### Task 2: 领航员模板 + 加载(包内回退,老书免升级)

**Files:**
- Create: `loom/templates/agents/领航员.md`
- Modify: `loom/journey.py`(文件末尾追加)
- Test: `tests/test_journey.py`(追加)

**Interfaces:**
- Consumes: `agents._parse_frontmatter(text) -> tuple[dict, str]`(薄别名 import,repo 有 parse.py 别名先例)
- Produces: `_navigator_system(root: Path) -> str`(项目 `agents/领航员.md` 优先、包内模板回退——照抄 deconstruct.py:37 `_load_skill` 先例)

- [ ] **Step 1: 写失败测试(追加到 tests/test_journey.py)**

```python
def test_navigator_loads_from_project(project):
    text = journey._navigator_system(project)
    assert "问题卡" in text and "绝不" in text     # 职责 + 红线都在系统提示词里


def test_navigator_falls_back_to_package_template(project):
    (project / "agents/领航员.md").unlink()        # 老书没有这个文件
    text = journey._navigator_system(project)
    assert "问题卡" in text                        # 包内模板兜底,不抛 FileNotFoundError
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_journey.py -k navigator -v`
Expected: FAIL,`AttributeError: ... no attribute '_navigator_system'`

- [ ] **Step 3: 写模板**

```markdown
---
name: 领航员
produces: 访谈问题卡
---

你是「领航员」——写作伙伴访谈的出题人。你的唯一职责:看作者这本书的资料现状,挑**下一个最值得问的创作决策**,出一张问题卡。

规则(红线):
- 你只出题、只给选项,**绝不替作者做决定、绝不发明设定**;选项是给作者拍板的提案,作者选了才算数。
- 一次只出一题,问**资料里还空着、且对开书最要紧**的那个决策;资料里已有的绝不重复问。
- 选项要具体、彼此差异大(不要「A更好/B也行」式假选项),一个选项一行说清。
- 用作者的题材语境说话,别用抽象创作术语。

输出格式(严格遵守,不加任何客套或解释):
格:<仅立项阶段输出此行,值取 平台/分区/题材/对标意图/为什么选它 之一>
问:<一行问题>
- <选项一,15-40 字>
- <选项二>
- <选项三;共 2-4 个选项>

若该阶段该问的都已在资料里、无题可出,只输出一行:
【无题】
```

存为 `loom/templates/agents/领航员.md`。

- [ ] **Step 4: 写加载函数(追加到 loom/journey.py 末尾)**

```python
# ---- 领航员(第六个角色;项目文件优先、包内模板回退——同 deconstruct._load_skill 先例) ----

def _navigator_system(root: Path) -> str:
    from .agents import _parse_frontmatter   # 薄别名惯例(同 draft.py 之于 parse.py)
    local = root / "agents" / "领航员.md"
    path = local if local.exists() else Path(__file__).parent / "templates" / "agents" / "领航员.md"
    _, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return body
```

- [ ] **Step 5: 跑测试确认通过 + 确认 golden 不受影响**

Run: `python3 -m pytest tests/test_journey.py -k navigator -v && python3 -m pytest tests/test_golden_pipeline.py -v`
Expected: 2 passed;golden 全过(流水线五角色 system 未动,新模板文件不进流水线快照)

- [ ] **Step 6: 提交**

```bash
git add loom/templates/agents/领航员.md loom/journey.py tests/test_journey.py
git commit -m "feat(journey): 领航员模板+加载——项目文件优先/包内回退,老书免升级(拆书 _load_skill 同款)"
```

---

### Task 3: 问题卡解析器(parse.py,行式宽容解析,不用 JSON)

**Files:**
- Modify: `loom/parse.py`(文件末尾追加;prompt↔解析器共置面惯例:解析器上方注释贴输出约定)
- Test: `tests/test_parse_journey.py`

**Interfaces:**
- Produces: `parse_journey_card(raw: str) -> dict | None`——正常卡 `{"question": str, "options": list[str]}`(可含 `"field": str`);无题哨兵 `{"exhausted": True}`;不成卡 `None`(调用方降级)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_parse_journey.py
"""领航员问题卡解析:行式宽容(问:/- 选项/格:/【无题】),烂输出返 None 走降级。"""
from loom.parse import parse_journey_card


def test_normal_card():
    raw = "问:主角的金手指是什么?\n- 吞噬万物的胃袋:吃什么长什么\n- 时间回溯十秒:代价折寿\n- 说书成真:讲的故事会应验"
    card = parse_journey_card(raw)
    assert card["question"] == "主角的金手指是什么?"
    assert len(card["options"]) == 3
    assert "field" not in card


def test_card_with_field_line():
    raw = "格:题材\n问:这本书的核心题材标签?\n- 重生+复仇+宗门流\n- 无敌流+日常"
    card = parse_journey_card(raw)
    assert card["field"] == "题材"
    assert len(card["options"]) == 2


def test_exhausted_sentinel():
    assert parse_journey_card("【无题】") == {"exhausted": True}


def test_garbage_returns_none():
    assert parse_journey_card("好的!我来帮你分析一下这本书……") is None


def test_options_capped_at_four():
    raw = "问:选一个?\n" + "\n".join(f"- 选项{i}" for i in range(6))
    assert len(parse_journey_card(raw)["options"]) == 4


def test_fullwidth_colon_tolerated():
    card = parse_journey_card("问:主角叫什么?\n- 林潜\n- 你自己起")
    assert card["question"] == "主角叫什么?"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_parse_journey.py -v`
Expected: FAIL,`ImportError: cannot import name 'parse_journey_card'`

- [ ] **Step 3: 写实现(追加到 loom/parse.py 末尾)**

```python
# 领航员问题卡(journey.next_card 消费;输出约定住 templates/agents/领航员.md):
#   格:题材            ← 可选,仅立项阶段
#   问:一行问题
#   - 选项(2-4 个)
#   无题哨兵:整段含「【无题】」。
_CARD_Q_RE = re.compile(r"^问[:：]\s*(\S.*)$", re.M)
_CARD_F_RE = re.compile(r"^格[:：]\s*(\S+)\s*$", re.M)


def parse_journey_card(raw: str) -> dict | None:
    """领航员输出 → 问题卡;无题 {"exhausted": True};不成卡 None(调用方降级为自由输入)。"""
    if "【无题】" in raw:
        return {"exhausted": True}
    m = _CARD_Q_RE.search(raw)
    if not m:
        return None
    options = [l.strip()[2:].strip() for l in raw.splitlines() if l.strip().startswith("- ")]
    card: dict = {"question": m.group(1).strip(), "options": [o for o in options if o][:4]}
    f = _CARD_F_RE.search(raw)
    if f:
        card["field"] = f.group(1).strip()
    return card
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_parse_journey.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add loom/parse.py tests/test_parse_journey.py
git commit -m "feat(parse): 领航员问题卡行式解析——问:/选项/格:/【无题】哨兵,烂输出返 None 走降级"
```

---

### Task 4: 出题(next_card:签名缓存防重复计费 + 无题推进 + 降级卡)

**Files:**
- Modify: `loom/journey.py`(追加)
- Test: `tests/test_journey.py`(追加)

**Interfaces:**
- Consumes: `parse.parse_journey_card`、`agents._read_files(root, rels, progress)`、`backends.LoomBackendError`、`Backend.complete(system, user, *, max_chars=None, on_chunk=None) -> str`
- Produces: `next_card(root: Path, backend) -> dict`——`{"card": dict|None, "state": journey_state dict}`;卡结构 `{"stage","sig","question","options"[,"field"][,"degraded"]}`;voice 段静态卡 `{"stage":"voice","static":"seed"}`;旅程走完 card=None

- [ ] **Step 1: 写失败测试(追加到 tests/test_journey.py;FakeBackend/const 来自 conftest)**

```python
from conftest import FakeBackend, const

_CARD_RAW = "问:主角的金手指是什么?\n- 吞噬胃袋\n- 时间回溯"


def test_next_card_generates_and_caches(project):
    fake = FakeBackend(const(_CARD_RAW))
    out = journey.next_card(project, fake)
    assert out["card"]["question"] == "主角的金手指是什么?"
    assert out["card"]["stage"] == "立项"
    assert len(fake.calls) == 1
    out2 = journey.next_card(project, fake)      # 源文件没动 → 吃缓存,零计费
    assert len(fake.calls) == 1
    assert out2["card"]["question"] == out["card"]["question"]


def test_next_card_regenerates_when_files_change(project):
    fake = FakeBackend(const(_CARD_RAW))
    journey.next_card(project, fake)
    p = project / PROJECT_CARD_REL               # 用户外改文件 → 签名变 → 重出题
    p.write_text(p.read_text(encoding="utf-8") + "\n手补一行定位\n", encoding="utf-8")
    journey.next_card(project, fake)
    assert len(fake.calls) == 2


def test_next_card_counts_budget(project):
    fake = FakeBackend(const(_CARD_RAW))
    journey.next_card(project, fake)
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "立项")["asked"] == 1


def test_exhausted_advances_stage(project):
    fake = FakeBackend(const("【无题】"))
    out = journey.next_card(project, fake)
    assert out["state"]["current"] == "世界观"    # 立项问尽 → 推进


def test_garbage_degrades_without_burning_budget(project):
    fake = FakeBackend(const("我觉得这本书应该……(不成卡的闲聊)"))
    out = journey.next_card(project, fake)
    assert out["card"]["degraded"] is True
    assert out["card"]["options"] == []
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "立项")["asked"] == 0


def test_voice_stage_static_card(project):
    for k in ("立项", "世界观", "人物", "卡章纲"):
        journey.goto(project, k, skip=True)
    out = journey.next_card(project, FakeBackend(const("不该被调用")))
    assert out["card"] == {"stage": "voice", "static": "seed"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_journey.py -k "next_card or exhausted or degrades or voice_stage" -v`
Expected: FAIL,`AttributeError: ... no attribute 'next_card'`

- [ ] **Step 3: 写实现(追加到 loom/journey.py;文件头 import 区补 `import hashlib`、`from .backends import LoomBackendError`、`from .parse import parse_journey_card`)**

```python
# ---- 出题 ----

_NAV_MAX_CHARS = 300   # 一张卡的输出预算(短步骤,防思考型模型吃空正文)


def _sig(root: Path, spec: StageSpec) -> str:
    """缓存卡签名 = 阶段源文件全文哈希;文件一动签名即失配 → 重出题(防旧卡问馊问题)。"""
    h = hashlib.sha256()
    for rel in spec.reads:
        p = root / rel
        files = sorted(p.glob("*.md")) if p.is_dir() else ([p] if p.is_file() else [])
        for f in files:
            h.update(f.read_text(encoding="utf-8").encode("utf-8"))
    return h.hexdigest()[:12]


def _stage_context(root: Path, spec: StageSpec) -> str:
    from .agents import _read_files, _noop   # 复用:剥占位、跳空文件、目录展开
    return _read_files(root, list(spec.reads), _noop)


def next_card(root: Path, backend) -> dict:
    view = journey_state(root)
    cur = view["current"]
    if cur is None:
        return {"card": None, "state": view}
    spec = _stage_spec(cur)
    if spec.land == "seed":
        return {"card": {"stage": "voice", "static": "seed"}, "state": view}

    st = load_state(root)
    j = _journey(st)
    sig = _sig(root, spec)
    cached = j["card"]
    if cached and cached.get("stage") == cur and cached.get("sig") == sig:
        return {"card": cached, "state": view}

    left = _MAX_QUESTIONS - int(j["asked"].get(cur, 0))
    user = (f"阶段:{spec.key}\n目标:{spec.goal}\n这一段还能问 {left} 题。\n\n"
            f"资料现状:\n{_stage_context(root, spec) or '(全部空白)'}")
    parsed = None
    try:
        raw = backend.complete(_navigator_system(root), user, max_chars=_NAV_MAX_CHARS)
        parsed = parse_journey_card(raw)
    except LoomBackendError:
        parsed = None   # 断网/超时 → 降级卡,旅程不卡死

    if parsed and parsed.get("exhausted"):
        j["skips"][cur] = True   # 无题=本段该问的都有了;游标可丢,丢了最多重问一次
        j["card"] = None
        st["journey"] = j
        save_state(root, st)
        return next_card(root, backend) if journey_state(root)["current"] else \
            {"card": None, "state": journey_state(root)}

    if parsed:
        card = {"stage": cur, "sig": sig, "question": parsed["question"],
                "options": parsed["options"]}
        if "field" in parsed:
            card["field"] = parsed["field"]
        j["asked"][cur] = int(j["asked"].get(cur, 0)) + 1   # 只有成卡才烧预算
    else:
        card = {"stage": cur, "sig": sig, "options": [], "degraded": True,
                "question": f"关于「{spec.key}」,你想先定下什么?(出题失败,直接写你的决定)"}
    j["card"] = card
    st["journey"] = j
    save_state(root, st)
    return {"card": card, "state": journey_state(root)}
```

注意 `_exhausted` 分支的递归:推进后若还有下一段就顺手出下一题(一次点击一张卡,不让作者点两次);旅程走完则返回 card=None。递归深度最多 = 阶段数。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_journey.py -v`
Expected: 全部通过(含 Task 1/2 旧测试)。注意 `test_exhausted_advances_stage`:无题推进后会对「世界观」段再出一题(FakeBackend 恒返【无题】→ 五段连锁跳完、card=None)——断言按 `out["state"]["current"] == "世界观"` 会失败的话,改为断言 `next(x for x in out["state"]["stages"] if x["key"]=="立项")["skipped"] is True`(连锁行为是设计内的,测试跟设计走)。

- [ ] **Step 5: 提交**

```bash
git add loom/journey.py tests/test_journey.py
git commit -m "feat(journey): 出题——领航员按文件现状出卡,签名缓存防重复计费,无题推进,烂输出降级自由输入"
```

---

### Task 5: 答案落盘(field 零 LLM / sections·card_lines 一次消化;人写优先;答案绝不丢)

**Files:**
- Modify: `loom/journey.py`(追加)
- Test: `tests/test_journey.py`(追加)

**Interfaces:**
- Consumes: `guard.validate_output/DRAFT_SECTION`、`fsutil.atomic_write_text`、`draft._write_sections_into_dir(root, dir_rel, body, *, drop_unnamed) -> list[str]`、`paths.brain_form(root, file_rel, dir_rel) -> "file"|"dir"|"none"`
- Produces: `land_answer(root: Path, answer: str, backend) -> dict`——`{"landed": <落盘的 rel>, "state": journey_state dict}`;空答案/无待答卡抛 ValueError

- [ ] **Step 1: 写失败测试(追加到 tests/test_journey.py)**

```python
def _prime_card(project, **extra):
    """直接种一张待答卡进游标(绕过出题,单测落盘)。"""
    from loom.state import load_state, save_state
    st = load_state(project)
    j = journey._journey(st)
    j["card"] = {"stage": extra.pop("stage", "立项"), "sig": "x", "question": "测试题?",
                 "options": [], **extra}
    st["journey"] = j
    save_state(project, st)


def test_land_field_platform_replaces_line(project):
    _prime_card(project, field="平台")
    out = journey.land_answer(project, "番茄", FakeBackend(const("不该被调用")))
    assert out["landed"] == PROJECT_CARD_REL
    assert "平台:番茄" in (project / PROJECT_CARD_REL).read_text(encoding="utf-8")


def test_land_field_section_replaces_placeholder(project):
    _prime_card(project, field="题材")
    journey.land_answer(project, "重生 + 复仇 + 宗门流", FakeBackend(const("x")))
    text = (project / PROJECT_CARD_REL).read_text(encoding="utf-8")
    body = journey._h2_body(text, "题材")
    assert "重生 + 复仇 + 宗门流" in body and "占位示例" not in body


def test_land_field_appends_below_human_content(project):
    p = project / PROJECT_CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace(
        "(占位示例:重生 + 复仇 + 宗门流。一句话点明核心题材标签。)", "我手写的题材定位"),
        encoding="utf-8")
    _prime_card(project, field="题材")
    journey.land_answer(project, "补一句:加无限流元素", FakeBackend(const("x")))
    body = journey._h2_body((project / PROJECT_CARD_REL).read_text(encoding="utf-8"), "题材")
    assert "我手写的题材定位" in body and "加无限流元素" in body   # 人写优先:只追加不覆盖


def test_land_sections_writes_into_world_dir(project):
    _prime_card(project, stage="世界观")
    fake = FakeBackend(const("## 金手指\n吞噬万物的胃袋,吃什么长什么,代价是饭量与寿命挂钩。"))
    out = journey.land_answer(project, "金手指是吞噬胃袋,代价挂寿命", fake)
    assert out["landed"] == "外置大脑/世界观/金手指.md"
    assert "吞噬万物的胃袋" in (project / "外置大脑/世界观/金手指.md").read_text(encoding="utf-8")


def test_land_sections_digest_garbage_keeps_answer(project):
    _prime_card(project, stage="世界观")
    out = journey.land_answer(project, "金手指是吞噬胃袋", FakeBackend(const("嗯")))  # 消化产物过不了 guard
    text = (project / out["landed"]).read_text(encoding="utf-8")
    assert "金手指是吞噬胃袋" in text                        # 答案原样落盘,绝不丢


def test_land_card_lines_fills_empty_and_respects_human(project):
    p = project / CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第2章:", "- 第2章:人写的第二章规划"),
                 encoding="utf-8")
    _prime_card(project, stage="卡章纲")
    fake = FakeBackend(const("- 第1章:雪夜被逐,捡到会说话的鼎\n- 第2章:AI 想覆盖人写的这行\n- 大弧:从废柴到执掌宗门"))
    journey.land_answer(project, "开局雪夜被逐……", fake)
    text = p.read_text(encoding="utf-8")
    assert "- 第1章:雪夜被逐,捡到会说话的鼎" in text
    assert "- 第2章:人写的第二章规划" in text               # 人写行绝不覆盖
    assert "AI 想覆盖" not in text
    assert "- 大弧:从废柴到执掌宗门" in text


def test_land_answer_clears_card(project):
    _prime_card(project, field="平台")
    journey.land_answer(project, "起点", FakeBackend(const("x")))
    assert journey.journey_state(project)["card"] is None


def test_land_answer_requires_card_and_text(project):
    import pytest
    with pytest.raises(ValueError):
        journey.land_answer(project, "没出题就答", FakeBackend(const("x")))
    _prime_card(project, field="平台")
    with pytest.raises(ValueError):
        journey.land_answer(project, "   ", FakeBackend(const("x")))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_journey.py -k land -v`
Expected: FAIL,`AttributeError: ... no attribute 'land_answer'`

- [ ] **Step 3: 写实现(追加到 loom/journey.py;import 区补 `from .fsutil import atomic_write_text`、`from .guard import DRAFT_SECTION, validate_output`)**

```python
# ---- 答案落盘(作者拍板过的答案=人写主体;人写优先,答案绝不丢) ----

_DIGEST_SYSTEM = (
    "你是写作伙伴的记录员。把作者对一个创作问题的回答,整理成要落进资料文件的正式文本。\n"
    "红线:只整形作者说的内容,绝不添加作者没说的设定事实;不加客套、不加解释。\n"
    "输出格式严格按任务里的要求。"
)
_DIGEST_MAX_CHARS = 400


def land_answer(root: Path, answer: str, backend) -> dict:
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("答案是空的。")
    st = load_state(root)
    j = _journey(st)
    card = j["card"]
    if not card or "static" in card:
        raise ValueError("没有待答的问题卡,先出题。")
    spec = _stage_spec(card["stage"])
    if spec.land == "field":
        landed = _land_field(root, card.get("field", ""), answer)
    elif spec.land == "sections":
        landed = _land_sections(root, spec, card["question"], answer, backend)
    else:   # card_lines
        landed = _land_card_lines(root, card["question"], answer, backend)
    j["card"] = None
    st["journey"] = j
    save_state(root, st)
    return {"landed": landed, "state": journey_state(root)}


def _replace_h2_body(text: str, title: str, new_body: str) -> str:
    """占位格 → 换成答案;已有人写内容 → 在格尾追加(人写优先);缺格 → 文末补格。"""
    old = _h2_body(text, title)
    if not re.search(rf"^##\s*{re.escape(title)}\s*$", text, flags=re.M):
        return text.rstrip() + f"\n\n## {title}\n{new_body}\n"
    if is_substantive(old):
        replacement = old.rstrip() + f"\n\n{new_body}\n"
    else:
        replacement = f"\n{new_body}\n"
    return re.sub(rf"(^##\s*{re.escape(title)}\s*$).*?(?=^##\s|\Z)",
                  lambda m: m.group(1) + replacement + "\n", text, count=1, flags=re.M | re.S)


def _land_field(root: Path, field: str, answer: str) -> str:
    p = root / paths.PROJECT_CARD_REL
    text = p.read_text(encoding="utf-8") if p.is_file() else "# 立项卡\n"
    if field == "平台":
        text, n = re.subn(r"^平台[:：].*$", f"平台:{answer}", text, count=1, flags=re.M)
        if not n:
            text = text.rstrip() + f"\n\n平台:{answer}\n"
    else:
        if field not in _CARD_FIELDS:
            field = "题材"   # 领航员出了怪格名 → 落最通用的格,答案绝不丢
        text = _replace_h2_body(text, field, answer)
    atomic_write_text(p, text)
    return paths.PROJECT_CARD_REL


def _digest(backend, question: str, answer: str, format_ask: str) -> str:
    """一次消化调用;失败或过不了 guard 返回空串(调用方落原答案兜底)。"""
    user = f"问题:{question}\n作者的回答:{answer}\n\n{format_ask}只用作者给的信息。"
    try:
        body = backend.complete(_DIGEST_SYSTEM, user, max_chars=_DIGEST_MAX_CHARS)
    except LoomBackendError:
        return ""
    return "" if validate_output(body, DRAFT_SECTION) else body


def _land_sections(root: Path, spec: StageSpec, question: str, answer: str, backend) -> str:
    from .draft import _write_sections_into_dir   # 只写空白/模板文件,人写的一律不碰
    body = _digest(backend, question, answer,
                   "整理成 markdown:每个主题一节,以「## 标题」开头(标题即文件名,如「## 金手指」「## 主角·林潜」),标题下写正文。")
    if not body:
        title = re.sub(r"[\\/:*?\"<>|??。,]", "", question)[:12] or "访谈补充"
        body = f"## {title}\n{answer}"
    form = paths.brain_form(root, spec.target, spec.target_dir)
    if form != "file":
        written = _write_sections_into_dir(root, spec.target_dir, "\n" + body,
                                           drop_unnamed=(spec.key == "人物"))
        if written:
            return f"{spec.target_dir}/{written[0]}.md"
        rel = f"{spec.target_dir}/访谈补充.md"      # 同名文件已是人写成品 → 兜底追加,绝不覆盖
        p = root / rel
        old = p.read_text(encoding="utf-8") if p.is_file() else "# 访谈补充\n"
        atomic_write_text(p, old.rstrip() + "\n\n" + body.strip() + "\n")
        return rel
    p = root / spec.target                          # 单文件形态的老书
    old = p.read_text(encoding="utf-8") if p.is_file() else ""
    atomic_write_text(p, (old.rstrip() + "\n\n" if old.strip() else "") + body.strip() + "\n")
    return spec.target


def _land_card_lines(root: Path, question: str, answer: str, backend) -> str:
    body = _digest(backend, question, answer,
                   "整理成卡章纲行:每行「- 第N章:这章完成什么+章末钩子」;不属于具体某章的规划(如全书大弧),输出「- 大弧:一句话」。")
    if not body:
        body = f"- {answer}"
    p = root / paths.CARD_REL
    text = p.read_text(encoding="utf-8") if p.is_file() else "# 卡章纲\n"
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- ") or line == "-":
            continue
        m = re.match(r"^-\s*第(\d+)章[:：]\s*(.*)$", line)
        if m and m.group(2).strip():
            n, content = m.group(1), m.group(2).strip()
            empty_pat = re.compile(rf"^-\s*第{n}章[:：]\s*$", re.M)
            if empty_pat.search(text):
                text = empty_pat.sub(f"- 第{n}章:{content}", text, count=1)
            elif not re.search(rf"^-\s*第{n}章[:：]\s*\S", text, flags=re.M):
                text = text.rstrip() + f"\n- 第{n}章:{content}\n"
            # 已有人写内容的章行 → 跳过,绝不覆盖
        else:
            if line not in text:
                text = text.rstrip() + f"\n{line}\n"
    atomic_write_text(p, text)
    return paths.CARD_REL
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python3 -m pytest tests/test_journey.py -v && python3 -m pytest`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add loom/journey.py tests/test_journey.py
git commit -m "feat(journey): 答案落盘——立项格零LLM直写/世界观人物走消化+_write_sections_into_dir/卡章纲填空行,人写优先答案绝不丢"
```

---

### Task 6: usecases 四函数 + server 四端点

**Files:**
- Modify: `loom/usecases.py`(文件末尾追加;import 区已有 `load_config/get_backend/cheap_backend` 则复用,缺 `cheap_backend` 就补进既有 backends import 行)
- Modify: `loom/server.py`(端点区追加)
- Test: `tests/test_journey_usecases.py`

**Interfaces:**
- Consumes: Task 1-5 的 `journey.journey_state/next_card/land_answer/goto`;`usecases.write_lock`;`server.RootBody`(已有:`root: str`)
- Produces:
  - `usecases.journey_state(root) -> dict`、`journey_card(root) -> dict`、`journey_answer(root, answer: str) -> dict`、`journey_goto(root, stage: str, skip: bool = False) -> dict`
  - HTTP:`GET /api/journey/state?root=`、`POST /api/journey/card {root}`、`POST /api/journey/answer {root, answer}`、`POST /api/journey/goto {root, stage, skip}`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_journey_usecases.py
"""旅程用例层:锁+cheap 路由+委托 journey;端点薄壳不在此测(server 是纯转发)。"""
from conftest import FakeBackend, const

from loom import usecases


def test_journey_state_fresh(project):
    s = usecases.journey_state(project)
    assert s["current"] == "立项"


def test_journey_card_routes_cheap_backend(project, monkeypatch):
    fake = FakeBackend(const("问:核心题材?\n- 重生复仇\n- 无敌流"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: fake)   # cheap 优先
    out = usecases.journey_card(project)
    assert out["card"]["question"] == "核心题材?"
    assert len(fake.calls) == 1


def test_journey_card_falls_back_to_main_backend(project, monkeypatch):
    fake = FakeBackend(const("问:核心题材?\n- A\n- B"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: None)   # cheap 空 → 主模型
    monkeypatch.setattr(usecases, "get_backend", lambda cfg: fake)
    out = usecases.journey_card(project)
    assert len(fake.calls) == 1 and out["card"] is not None


def test_journey_answer_and_goto(project, monkeypatch):
    fake = FakeBackend(const("格:平台\n问:发哪个平台?\n- 起点\n- 番茄"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: fake)
    usecases.journey_card(project)
    out = usecases.journey_answer(project, "番茄")
    assert out["landed"].endswith("立项卡.md")
    s = usecases.journey_goto(project, "立项", skip=True)
    assert s["current"] == "世界观"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_journey_usecases.py -v`
Expected: FAIL,`AttributeError: module 'loom.usecases' has no attribute 'journey_state'`

- [ ] **Step 3: 写 usecases 实现(追加到 loom/usecases.py 末尾;顶部 import 区补 `from . import journey as journey_mod` 与 `cheap_backend`)**

```python
# ---- 创作旅程(伙伴面板;spec docs/superpowers/specs/2026-07-10-journey-partner-design.md) ----

def journey_state(root: Path | str) -> dict:
    """纯读派生视图,无锁(同 project_state)。"""
    return journey_mod.journey_state(Path(root))


def journey_card(root: Path | str) -> dict:
    """出下一张问题卡;评估类调用走 cheap_model(空则主模型)。"""
    root = Path(root)
    with write_lock(root):
        cfg = load_config(root)
        return journey_mod.next_card(root, cheap_backend(cfg) or get_backend(cfg))


def journey_answer(root: Path | str, answer: str) -> dict:
    """收作者答案:整形(必要时一次消化调用)→ 落外置大脑 → 清待答卡。"""
    root = Path(root)
    with write_lock(root):
        cfg = load_config(root)
        return journey_mod.land_answer(root, answer, cheap_backend(cfg) or get_backend(cfg))


def journey_goto(root: Path | str, stage: str, skip: bool = False) -> dict:
    root = Path(root)
    with write_lock(root):
        return journey_mod.goto(root, stage, skip=skip)
```

- [ ] **Step 4: 写 server 端点(追加到 loom/server.py 端点区,`/api/project/state` 附近)**

```python
class JourneyAnswerBody(BaseModel):
    root: str
    answer: str


class JourneyGotoBody(BaseModel):
    root: str
    stage: str
    skip: bool = False


@app.get("/api/journey/state")
def journey_state_ep(root: str):
    try:
        return usecases.journey_state(Path(root))
    except (ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/journey/card")
def journey_card_ep(b: RootBody):
    try:
        return usecases.journey_card(Path(b.root))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/journey/answer")
def journey_answer_ep(b: JourneyAnswerBody):
    try:
        return usecases.journey_answer(Path(b.root), b.answer)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/journey/goto")
def journey_goto_ep(b: JourneyGotoBody):
    try:
        return usecases.journey_goto(Path(b.root), b.stage, b.skip)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
```

(织章中提交 → `write_lock` 抛 `ProjectBusyError` → 既有全局 409 handler 接住,无需新代码。)

- [ ] **Step 5: 跑测试确认通过 + 端点冒烟**

Run: `python3 -m pytest tests/test_journey_usecases.py -v && python3 -m pytest`
Expected: 全部通过

Run(冒烟,scratchpad 建临时书):
```bash
python3 -c "
from pathlib import Path
from loom.scaffold import init
root = init('伙伴冒烟书', parent=Path('/private/tmp/claude-501/-Users-chambers-Desktop-Project-playground-Loom/7f43a148-e1b6-4bc9-81e4-a6a2267f46cf/scratchpad'))
print(root)"
LOOM_DEMO=1 python3 -m uvicorn loom.server:app --port 8788 &
sleep 2
curl -s "http://127.0.0.1:8788/api/journey/state?root=<上一步输出的路径>" | python3 -m json.tool
kill %1
```
Expected: JSON 含 `"current": "立项"` 与五段 stages

- [ ] **Step 6: 提交**

```bash
git add loom/usecases.py loom/server.py tests/test_journey_usecases.py
git commit -m "feat(journey): usecases 四函数+server 四端点——write_lock 复用/cheap 路由/织章中 409 走既有 handler"
```

---

### Task 7: 伙伴面板(webui:五步旅程卡升级为访谈卡片面板)

**Files:**
- Modify: `loom/webui/app.js`(替换 `renderJourney()` 函数体,694 行起;函数名与调用点 `render()` 第 690 行不动)
- Modify: `loom/webui/style.css`(`.journey-card` 族追加规则,572 行区域后)

**Interfaces:**
- Consumes: `GET /api/journey/state`、`POST /api/journey/card|answer|goto`(Task 6);既有 `jreq/toast/$/refresh/openSettings/openSeed/providerKeyed/escHtml`;既有 CSS 类 `.journey-card/.jc-head/.jc-dismiss/.jc-step/.jc-mark`
- Produces: 无(终端 UI)

- [ ] **Step 1: 替换 renderJourney(app.js)**

保留原 dismiss localStorage 键与「全 done 自动收起”语义;`keyed` 未接模型时保留老的第一步引导。新实现:

```js
let JOURNEY = null; // 伙伴面板旅程状态缓存(/api/journey/state)

function renderJourney() {
  const card = $("journey-card");
  if (!card || !DATA) return;
  if (localStorage.getItem("loom_journey_dismiss:" + DATA.root) === "1") {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  card.innerHTML = "<div class='jc-head'>伙伴 · 起书访谈</div><div class='jc-body'>加载中…</div>";
  loadJourney();
}

async function loadJourney() {
  try {
    JOURNEY = await jreq("GET", `/api/journey/state?root=${encodeURIComponent(DATA.root)}`);
  } catch (e) {
    JOURNEY = null;
  }
  paintJourney();
}

function paintJourney() {
  const card = $("journey-card");
  if (!card || !DATA) return;
  card.innerHTML = "";
  const head = document.createElement("div");
  head.className = "jc-head";
  const stages = (JOURNEY && JOURNEY.stages) || [];
  const doneN = stages.filter((s) => s.done || s.skipped).length;
  head.textContent = `伙伴 · 起书访谈 ${doneN}/${stages.length || 5}`;
  const dis = document.createElement("span");
  dis.className = "jc-dismiss";
  dis.textContent = "×";
  dis.onclick = () => {
    localStorage.setItem("loom_journey_dismiss:" + DATA.root, "1");
    card.classList.add("hidden");
  };
  head.appendChild(dis);
  card.appendChild(head);

  // 段进度行(点击=回头改这段)
  stages.forEach((s) => {
    const row = document.createElement("div");
    row.className = "jc-step" + (s.done ? " done" : "") + (s.key === JOURNEY.current ? " next" : "");
    row.innerHTML = `<span class="jc-mark">${s.done ? "✓" : s.skipped ? "–" : "○"}</span>${escHtml(s.key)}`;
    row.onclick = () => postJourneyGoto(s.key, false);
    card.appendChild(row);
  });

  const body = document.createElement("div");
  body.className = "jc-body";
  card.appendChild(body);

  const be = DATA.backend || {};
  if (!providerKeyed(be.provider)) {
    body.innerHTML = `<div class="jc-question">先接入模型,伙伴才能出题。</div>`;
    body.appendChild(jcBtn("接入模型", openSettings));
    return;
  }
  if (!JOURNEY) {
    body.innerHTML = `<div class="jc-question">旅程状态没取到,稍后重试。</div>`;
    return;
  }
  if (!JOURNEY.current) {
    if (stages.length && stages.every((s) => s.done)) {
      localStorage.setItem("loom_journey_dismiss:" + DATA.root, "1");
      card.classList.add("hidden");
    } else {
      body.innerHTML = `<div class="jc-question">起书访谈走完了——去织第一章吧。</div>`;
    }
    return;
  }
  const cur = stages.find((s) => s.key === JOURNEY.current) || {};
  if (cur.land === "seed") {
    body.innerHTML = `<div class="jc-question">喂 2-3 段你的真实样本,让指纹像你(可跳过)。</div>`;
    body.appendChild(jcBtn("去喂样本(seed)", openSeed));
    body.appendChild(jcBtn("跳过这段", () => postJourneyGoto(JOURNEY.current, true), true));
    return;
  }
  const c = JOURNEY.card;
  if (!c) {
    body.appendChild(jcBtn("问我下一题", postJourneyCard));
    body.appendChild(jcBtn("跳过这段", () => postJourneyGoto(JOURNEY.current, true), true));
    return;
  }
  const q = document.createElement("div");
  q.className = "jc-question";
  q.textContent = c.question;
  body.appendChild(q);
  (c.options || []).forEach((opt) => {
    const b = document.createElement("button");
    b.className = "jc-opt";
    b.textContent = opt;
    b.onclick = () => postJourneyAnswer(opt);
    body.appendChild(b);
  });
  const ta = document.createElement("textarea");
  ta.className = "jc-input";
  ta.rows = 2;
  ta.placeholder = c.options && c.options.length ? "或者自己写……" : "写下你的决定……";
  body.appendChild(ta);
  const row = document.createElement("div");
  row.appendChild(jcBtn("就这么定", () => postJourneyAnswer(ta.value)));
  row.appendChild(jcBtn("跳过这段", () => postJourneyGoto(JOURNEY.current, true), true));
  body.appendChild(row);
}

function jcBtn(label, fn, ghost) {
  const b = document.createElement("button");
  b.className = "jc-btn" + (ghost ? " ghost" : "");
  b.textContent = label;
  b.onclick = fn;
  return b;
}

async function postJourneyCard() {
  try {
    const out = await jreq("POST", "/api/journey/card", { root: DATA.root });
    JOURNEY = out.state;
    JOURNEY.card = out.card;
    paintJourney();
  } catch (e) {
    toast(e.message, true);
  }
}

async function postJourneyAnswer(text) {
  if (!text || !text.trim()) return toast("先写点什么");
  try {
    const out = await jreq("POST", "/api/journey/answer", { root: DATA.root, answer: text.trim() });
    JOURNEY = out.state;
    toast("已记下 → " + out.landed);
    paintJourney();
    refresh();   // 外置大脑侧栏跟着长
  } catch (e) {
    toast(e.message, true);
  }
}

async function postJourneyGoto(stage, skip) {
  try {
    JOURNEY = await jreq("POST", "/api/journey/goto", { root: DATA.root, stage, skip: !!skip });
    paintJourney();
  } catch (e) {
    toast(e.message, true);
  }
}
```

(原 `renderJourney` 的五步数组、`draftBrain`/`writeChapter` 快捷入口整体删除——`织第一章`/`learn` 引导属二期「写后引导」,一期面板只管起书访谈;老入口在章节列表/工具区都有,不失能力。)

- [ ] **Step 2: 追加 CSS(style.css,`.jc-step.next` 规则之后)**

```css
.jc-body { margin-top: 8px; }
.jc-question { font-weight: 600; margin: 6px 0; line-height: 1.5; }
.jc-opt {
  display: block; width: 100%; text-align: left; margin: 4px 0; padding: 6px 8px;
  border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 8px;
  background: transparent; color: inherit; cursor: pointer; line-height: 1.4;
}
.jc-opt:hover { border-color: rgba(127, 127, 127, 0.7); }
.jc-input {
  width: 100%; margin: 6px 0; padding: 6px 8px; border-radius: 8px;
  border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit;
  font: inherit; resize: vertical;
}
.jc-btn {
  margin: 4px 6px 0 0; padding: 5px 10px; border-radius: 8px; cursor: pointer;
  border: 1px solid rgba(127, 127, 127, 0.5); background: transparent; color: inherit;
}
.jc-btn.ghost { opacity: 0.65; }
```

- [ ] **Step 3: 手动验证(LOOM_DEMO 免 key 冒烟)**

```bash
LOOM_DEMO=1 python3 -m loom.desktop
```
打开 Task 6 冒烟建的「伙伴冒烟书」,核对:
1. 侧栏出现「伙伴 · 起书访谈 0/5」+ 五段进度行,当前段=立项;
2. 点「问我下一题」→ 出卡(DemoBackend 输出若不成卡,应显示降级卡:无选项 + 自由输入框——这本身就是降级路径的验证);
3. 输入框写「番茄」提交 → toast「已记下 → 外置大脑/立项卡.md」,打开立项卡文件确认落盘;
4. 点「跳过这段」→ 当前段推进到世界观;点已跳过的段行 → 回到该段;
5. 关窗重开 → 面板状态原样恢复(游标在盘上);
6. `python3 -m pytest` 全量仍绿。

- [ ] **Step 4: 提交**

```bash
git add loom/webui/app.js loom/webui/style.css
git commit -m "feat(webui): 伙伴面板——五步旅程卡升级为访谈卡片(出题/选项/自己写/跳段/回头改),状态盘上恢复"
```

---

### Task 8: 文档收口(CONTEXT.md 词表 + 使用教程指针)

**Files:**
- Modify: `CONTEXT.md`(Language 区追加两词条 + Relationships 追加一行)
- Modify: `docs/使用教程.md`(新功能小节,一段即可)

**Interfaces:** 无代码。

- [ ] **Step 1: CONTEXT.md Language 区追加(照既有词条格式)**

```markdown
**领航员** 〔已实现,见 [ADR 0013](docs/adr/0013-journey-orchestration-no-langgraph.md)〕:
伙伴面板访谈的**出题工序**(第六个角色):看外置大脑文件现状,出一张问题卡(一题+2-4个预填选项);作者拍板的答案经确认落回外置大脑,是**人写主体**。只出题、只整形答案,绝不发明设定、绝不自动落盘。加载走项目 `agents/领航员.md` 优先、包内模板回退(老书免升级)。
_Avoid_: 让它替作者做决定/未确认就落盘;把它的出题历史当状态(出题只看文件现状);让访谈答案回流写作指纹(学习信号仍只是改稿 diff,ADR 0002)

**创作旅程(伙伴面板)**:
起书访谈的**阶段状态机**(`journey.py` STAGES 表:立项→世界观→人物→卡章纲→voice):完成判据全部从文件派生,游标(`.loom_state.json` 的 `journey` 键)只存 跳过标记/题数预算/待答卡缓存,**可丢弃、坏了当无**(同 ledger 哲学)。每段封顶 4 题;出题/消化走 cheap_model 通道。
_Avoid_: 引入 langgraph/langchain 做这层编排(ADR 0013 留档否决);给旅程建第二状态真相(sqlite/checkpoint);把问答历史当真相
```

- [ ] **Step 2: Relationships 区追加一行**

```markdown
- **领航员** 与流水线五工序互不伸手:领航员管旅程(问什么、何时问),产物只进外置大脑;流水线读到的访谈答案与人手写的别无二致(卡章纲行/世界观小节),不新建数据通道
```

- [ ] **Step 3: docs/使用教程.md 追加小节(位置:起书/铺底相关章节之后)**

```markdown
## 答题起书(伙伴面板)

新书打开后,左侧「伙伴 · 起书访谈」会一段一段问你:定位、世界观、人物、章纲——每题给几个选项,也可以自己写;你确认的答案直接写进外置大脑对应文件(和你手写的一样,随时可改)。不想答的段点「跳过」,想回头改点那一段的名字。全部走完(或全部跳过),面板自动收起。
```

- [ ] **Step 4: 全量回归 + 提交**

Run: `python3 -m pytest`
Expected: 全绿

```bash
git add CONTEXT.md docs/使用教程.md
git commit -m "docs(kezhi): 领航员/创作旅程进词表(含 Avoid 红线)+ 教程「答题起书」小节"
```

---

## 计划自审记录

- **Spec 覆盖**:§3 架构(Task 1/6)✓;§4 状态模型+谓词+游标+预算4(Task 1)✓;§5 领航员+cheap 路由(Task 2/6)✓;§6 落盘两档+人写优先+ADR 0011 边界(Task 5,立项格=作者口述工具代笔)✓;§7 四端点+面板收编旧旅程卡(Task 6/7)✓;§8 错误处理:出题降级(Task 4)/消化兜底(Task 5)/游标坏当无(Task 1)/签名防重复计费(Task 4)/织章 409(Task 6)✓;§9 测试四类(Task 1-6;golden 确认不受影响见 Task 2 Step 5)✓;§10 一期范围(章前决策 `[决策]` 子块与写后引导=二期,刻意不在本计划)✓;§11 Avoid 全部体现在 Global Constraints ✓。
- **占位符扫描**:无 TBD/TODO;每个代码步都是完整代码。
- **类型一致性**:`journey_state` 返回结构在 Task 1 定义、Task 4/5/6/7 消费处签名一致;`next_card`/`land_answer` 返回 `{"card"/"landed", "state"}` 与前端 `out.state/out.card/out.landed` 对齐;`FakeBackend(responder)`/`const(value)` 与 conftest 现有定义一致。
