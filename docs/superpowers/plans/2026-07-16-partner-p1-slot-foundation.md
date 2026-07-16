# 书房伙伴 P1:槽位地基(扫描器 + 定址落盘器)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 建成两块纯派生、离线可测、零模型零 UI 的地基——`loom/slots.py`(把外置大脑的骨架行读成可寻址的槽位)与 `journey._land_slot`(把「容器#键 + 内容」定址写进正确的骨架行),供后续 P2 对话循环的「看地基」工具、环境快照与拍板落盘直接调用。

**Architecture:** 槽位真相 = 书里的文件正文(骨架行),不是代码里的第四份表。扫描器把三种形状(平格/每实体一套/列表)统一成「容器×键」,五种 `at` 类型(line/h2/row/filename/file)。落盘器按 `at` 分派,复用现有 `_replace_h2_body`/`_apply_card_lines` 三条落盘铁律(人写优先/答案绝不丢/只碰空白模板)。全程零 LLM 调用。

**Tech Stack:** Python 3.11 + pytest(现 449 绿)。无新依赖。

**设计来源(权威):** 〔[两层卡设计](../specs/2026-07-15-navigator-two-layer-card-design.md)〕§2(槽位模型)、§5(定址落盘表)——本计划实现它俩;〔[书房伙伴设计](../specs/2026-07-16-navigator-agent-design.md)〕§5.3「看地基」工具、§6 落盘表继承这两块。

## Global Constraints

- **零模型调用、零新依赖、零 UI、零服务端改动**。P1 只碰:新建 `loom/slots.py`、改 `loom/journey.py`(加 `slot_order` 字段 + `_land_slot` + 微调 STAGES)、改 `loom/templates/外置大脑/卡章纲.md`(补一行)、新建 `tests/test_slots.py` + 扩 `tests/test_journey.py`。
- **既有测试红了 = 实现错了,回滚实现,禁改测试断言**。特别是 `tests/test_journey.py:207-347` 的 `test_land_*`(人写优先/答案绝不丢 13 条)、`tests/test_placeholder.py`、`tests/test_journey_usecases.py`。
- **落盘三铁律**(所有 `_land_*` 贯穿,`_land_slot` 必须守):① 人写优先(占位/模板才覆盖,人写实质只追加);② 答案绝不丢(每条路径有兜底);③ 只碰空白/模板文件。
- **`slot_order` 是排序不是值域**:文件不在表里只是排后面,不影响可达性——绝不能实现成白名单(那正是 ADR 0011:19 反对的)。
- **命名公约**:盘上/代码一律「slot / 槽位」,不引入「chip」(那是二期作废的 UI 词);`Slot.at` 五值固定字符串。
- 提交信息 `type(scope): 中文摘要`,末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件,绝不 `git add -A`。
- 环境 `.venv/bin/python`;测试 `.venv/bin/python -m pytest`;测试夹具 `tests/conftest.py` 的 `project` fixture(真实项目骨架)。

---

### Task 1: StageSpec 加 `slot_order` + 模板补 `- 大弧:` 行

**Files:**
- Modify: `loom/journey.py:26-49`(StageSpec 字段 + STAGES 五段填 slot_order)
- Modify: `loom/templates/外置大脑/卡章纲.md`(`- 第5章:` 后补 `- 大弧:`)
- Test: `tests/test_slots.py`(新建,先放本任务的两条)

**Interfaces:**
- Produces: `StageSpec.slot_order: tuple[str, ...]`(默认 `()`);`STAGES` 各段的 slot_order 值供 Task 2/3 的扫描器排序消费。

**背景:** `slot_order` 是文件 stem 的优先序(世界观有 5 个容器文件,`sorted(glob)` 是 Unicode 码点序会抖动)。`- 大弧:` 今天只存在于 digest 指令和测试夹具,模板里没有——补上新书才有大弧槽(老书没这行则卡章纲只有 5 个章槽,不合成假槽)。

- [ ] **Step 1: 写两个失败测试**

新建 `tests/test_slots.py`:

```python
"""槽位扫描器:把外置大脑骨架行读成可寻址槽位。纯派生、零模型。"""
from loom.journey import STAGES, _stage_spec


def test_stagespec_has_slot_order():
    world = _stage_spec("世界观")
    assert world.slot_order == ("一句话定位", "力量体系", "金手指", "地理与势力", "冰山真相")
    assert _stage_spec("voice").slot_order == ()


def test_template_card_has_arc_line(project):
    text = (project / "外置大脑/卡章纲.md").read_text(encoding="utf-8")
    assert "- 大弧:" in text
    assert text.index("- 第5章:") < text.index("- 大弧:")   # 大弧在五章之后
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_slots.py -v`
Expected: 两条 FAIL——`slot_order` AttributeError;`卡章纲.md` 无 `- 大弧:`。

- [ ] **Step 3: 实现**

`loom/journey.py` StageSpec 加字段(在 `target_dir` 后):

```python
    target_dir: str = ""      # sections 的目录形态
    slot_order: tuple[str, ...] = ()   # 槽位扫描的容器 stem 优先序(round-robin 轮转用;空=按现有顺序)
```

STAGES 五段补 slot_order(只世界观/人物有多容器需要序;立项/卡章纲单容器,voice 无):

```python
STAGES: tuple[StageSpec, ...] = (
    StageSpec("立项", "问清这本书的定位:平台/分区/题材/对标意图/为什么选它",
              (paths.PROJECT_CARD_REL,), "field", target=paths.PROJECT_CARD_REL),
    StageSpec("世界观", "问出核心世界观:力量体系、金手指及其代价、关键地理与势力",
              (paths.WORLD_REL, paths.WORLD_DIR_REL), "sections",
              target=paths.WORLD_REL, target_dir=paths.WORLD_DIR_REL,
              slot_order=("一句话定位", "力量体系", "金手指", "地理与势力", "冰山真相")),
    StageSpec("人物", "问出主角与关键配角/反派:名字、动机、底牌、软肋",
              (paths.CHARS_REL, paths.CHARS_DIR_REL), "sections",
              target=paths.CHARS_REL, target_dir=paths.CHARS_DIR_REL,
              slot_order=("主角", "配角", "反派")),
    StageSpec("卡章纲", "问出开局钩子、前 5 章一句话章纲、全书大弧",
              (paths.CARD_REL,), "card_lines", target=paths.CARD_REL),
    StageSpec("voice", "喂 2-3 段你的真实样本让指纹像你(走 seed,不出题)",
              (), "seed"),
)
```

`loom/templates/外置大脑/卡章纲.md` 在 `- 第5章:` 行后加一行 `- 大弧:`(保持文件其余不动)。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/test_slots.py tests/test_journey.py -q`
Expected: 全绿。注意 `test_journey.py` 里若有断言卡章纲章数/内容的测试,确认 `- 大弧:` 未破它们(大弧不匹配 `_CARD_LINE_RE` 的 `- 第N章:`,`stage_done` 的 card_lines 判定不受影响)。

- [ ] **Step 5: Commit**

```bash
git add loom/journey.py loom/templates/外置大脑/卡章纲.md tests/test_slots.py
git commit -m "$(cat <<'EOF'
feat(slots): StageSpec 加 slot_order 排序字段 + 模板补「- 大弧:」行

slot_order=文件stem优先序(防 sorted(glob) 的 unicode 码点序抖动);它是排序
非值域,文件不在表里只排后面不影响可达性(守 ADR 0011 不搞白名单)。大弧行今天
只在 digest 指令里,模板没有——补上新书才有大弧槽,老书无此行则不合成假槽。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `slots.py` 扫描器——line/h2/row 三种平坦 `at`(立项+世界观骨架)

**Files:**
- Create: `loom/slots.py`
- Test: `tests/test_slots.py`(扩)

**Interfaces:**
- Consumes: `journey.StageSpec`、`parse.is_substantive`/`_EMPTY_ROW_RE`/`_PAREN_SPAN_RE`、`journey._h2_body`、`paths` 常量。
- Produces:
  ```python
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
  def stage_slots(root: Path, spec: StageSpec) -> list[Slot]
  ```
  本任务只实现 line/h2/row(立项段与世界观的骨架行文件);filename/file/round-robin 留 Task 3。

**背景(骨架行事实,scout 核实):**
- 立项卡.md:第 7 行 `平台:起点`(at=line,全库唯一可解析行);第 9/12/15/18 行 `## 分区/题材/对标意图/为什么选它`(at=h2,带占位)。
- 金手指.md:第 4-11 行 8 个 `- 键(括注):`;力量体系/地理与势力各 3 行;冰山真相 1 行。
- `_EMPTY_ROW_RE = ^-\s*[^:：]{0,40}[:：]\s*$`(parse.py:172)判空骨架行;`_PAREN_SPAN_RE`(:176)剥行内括注。`is_substantive` 已在用它俩。
- **row 的 hint = 括注原文**:`- 代价·限制(至少一种硬代价,不能无敌到没冲突):` 的 hint 是「至少一种硬代价,不能无敌到没冲突」——`_PAREN_SPAN_RE` 今天把它剥掉扔了,槽位层要留它喂 prompt。

- [ ] **Step 1: 写失败测试**

`tests/test_slots.py` 追加:

```python
from loom.slots import stage_slots, Slot


def _ids(slots): return [s.id for s in slots]


def test_project_stage_slots_line_and_h2(project):
    slots = stage_slots(project, _stage_spec("立项"))
    d = {s.key: s for s in slots}
    assert d["平台"].at == "line" and d["平台"].filled is True       # 模板预填「起点」
    assert d["题材"].at == "h2" and d["题材"].filled is False        # 占位不算实质
    assert d["题材"].container == "外置大脑/立项卡.md"


def test_row_slots_carry_hint_and_fill(project):
    # 金手指 8 行 row,hint 取括注原文,填了才 filled
    p = project / "外置大脑/世界观/金手指.md"
    slots = [s for s in stage_slots(project, _stage_spec("世界观")) if s.container.endswith("金手指.md")]
    cost = next(s for s in slots if "代价" in s.key)
    assert cost.at == "row"
    assert "硬代价" in cost.hint          # 括注原文进 hint
    assert cost.filled is False
    p.write_text(p.read_text(encoding="utf-8").replace(
        "- 代价·限制(至少一种硬代价,不能无敌到没冲突):",
        "- 代价·限制(至少一种硬代价,不能无敌到没冲突):每用一次折寿三天"), encoding="utf-8")
    cost2 = next(s for s in stage_slots(project, _stage_spec("世界观"))
                 if s.container.endswith("金手指.md") and "代价" in s.key)
    assert cost2.filled is True
    assert "折寿三天" in cost2.preview
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_slots.py -v -k "line_and_h2 or hint_and_fill"`
Expected: FAIL——`loom.slots` ImportError。

- [ ] **Step 3: 实现 `loom/slots.py`(line/h2/row 部分)**

```python
"""槽位扫描器:把外置大脑的骨架行读成可寻址的槽位(容器×键)。

槽位真相 = 书里的文件正文,不是代码侧的表:作者删掉一行骨架,那个槽就没了。
纯派生、零存储、零模型、每次现算。五种 at:line/h2/row(本文件)+ filename/file(见下)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .journey import StageSpec, _h2_body
from .parse import _EMPTY_ROW_RE, _PAREN_SPAN_RE, is_substantive

_ROW_RE = re.compile(r"^-\s*([^:：(（]+?)\s*(?:[(（][^)）]*[)）])?\s*[:：](.*)$")
# 捕获:键(冒号/括注前的名)、括注后冒号后的正文。hint 另取括注原文。
_HINT_RE = re.compile(r"[(（]([^)）]*)[)）]")
_PLATFORM_RE = re.compile(r"^平台\s*[:：]\s*(.*)$", re.M)


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
        hm = _HINT_RE.search(line)
        # 「空表单行」判定复用 is_substantive 的口径:剥括注后冒号后无实字 = 空
        filled = bool(_PAREN_SPAN_RE.sub("", line).split("：")[-1].split(":")[-1].strip()) or bool(val)
        out.append(Slot(id=f"{rel}#{key}", label=key[:10], container=rel, at="row",
                        key=key, hint=hm.group(1).strip() if hm else "",
                        filled=filled, preview=_preview(val)))
    return out


@dataclass(frozen=True)
class Slot:
    id: str
    label: str
    container: str
    at: str
    key: str
    hint: str
    filled: bool
    preview: str


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
    from .journey import _CARD_FIELDS
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
```

(注:`_EMPTY_ROW_RE` import 保留给 Task 3 的 file 兜底判定;本任务 row 的 filled 用剥括注后取冒号后实字的口径,与 `is_substantive` 一致。)

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_slots.py -q`
Expected: Task 1+2 的测试全绿。

- [ ] **Step 5: Commit**

```bash
git add loom/slots.py tests/test_slots.py
git commit -m "$(cat <<'EOF'
feat(slots): 扫描器 line/h2/row——立项平台行/四格 + 世界观骨架行

槽位真相=书里骨架行,复用 parse 的 _EMPTY_ROW_RE/_PAREN_SPAN_RE/is_substantive
判空;row 的 hint 取模板括注原文(今天被剥掉扔了,喂 prompt 用)。纯派生零模型。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 扫描器 filename/file 两种 `at` + round-robin 轮转(人物命名 + 散文兜底)

**Files:**
- Modify: `loom/slots.py`
- Test: `tests/test_slots.py`(扩)

**Interfaces:**
- Consumes: Task 2 的 `Slot`/`_row_slots`;`paths.brain_dir_files`/`GROWTH_NAME`、`journey._NAME_SEP`。
- Produces: `stage_slots` 完成人物段(filename)、世界观/人物的 file 兜底、跨容器 round-robin。

**三条死规则(scout 核实,每条对应一个致命洞):**
- **(a) filename:** 容器 stem 含「未命名」→ 出**一个** `at="filename"` 槽(`key="@name"`,label「给主角起个名字」)并**压住该容器全部 row 槽**;stem 已带真名 → 正常出 row 槽。不加则作者填满 5 格 `_protagonist_done` 仍假,`writing_unlocked` 永久锁死。
- **(b) file:** 容器既无 row 也无可寻址骨架 → 整份一个 `at="file"` 槽(`key="@body"`,`filled=is_substantive(全文)`,hint 取 `>` 引导行)。`一句话定位.md` 零骨架行必须走这条;也是散文化老书/导入书的自动降级(永不归零)。
- **round-robin:** 未填槽按 `slot_order` 交错,不按文件深钻——否则金手指 8 行霸屏,「代价」排第 12 新书永不可达。

- [ ] **Step 1: 写失败测试**

`tests/test_slots.py` 追加:

```python
def test_unnamed_protagonist_yields_filename_slot(project):
    # 未命名主角:出一个 @name 槽,压住 5 个 row 槽
    slots = [s for s in stage_slots(project, _stage_spec("人物")) if "主角" in s.container]
    assert len(slots) == 1 and slots[0].at == "filename" and slots[0].key == "@name"


def test_named_protagonist_yields_row_slots(project):
    d = project / "外置大脑/人物"
    (d / "主角·未命名.md").rename(d / "主角·林潜.md")
    slots = [s for s in stage_slots(project, _stage_spec("人物")) if "林潜" in s.container]
    assert all(s.at == "row" for s in slots) and len(slots) >= 4
    assert any("林潜" in s.label for s in slots)     # 实体容器 label 带前缀


def test_headerless_file_yields_file_slot(project):
    # 一句话定位.md 零骨架行 → 一个 @body file 槽
    slots = [s for s in stage_slots(project, _stage_spec("世界观")) if s.container.endswith("一句话定位.md")]
    assert len(slots) == 1 and slots[0].at == "file" and slots[0].key == "@body"
    assert slots[0].filled is False


def test_prose_rewrite_degrades_to_file_slot(project):
    # 作者把金手指改成一段散文 → 退化成 1 个 file 槽,不归零
    p = project / "外置大脑/世界观/金手指.md"
    p.write_text("# 金手指\n\n主角能吞噬万物,代价是每吞一次折寿。\n", encoding="utf-8")
    slots = [s for s in stage_slots(project, _stage_spec("世界观")) if s.container.endswith("金手指.md")]
    assert len(slots) == 1 and slots[0].at == "file" and slots[0].filled is True


def test_round_robin_interleaves_containers(project):
    # 前几个未填槽应跨容器交错,不是一个文件全排完
    unfilled = [s for s in stage_slots(project, _stage_spec("世界观")) if not s.filled][:4]
    containers = [s.container for s in unfilled]
    assert len(set(containers)) >= 2      # 前 4 个未填槽来自 ≥2 个文件
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_slots.py -v -k "protagonist or file_slot or round_robin"`
Expected: FAIL(人物段返 `[]`;世界观无 file 兜底、无轮转)。

- [ ] **Step 3: 实现**

`loom/slots.py` 加 filename/file 扫描 + 轮转,替换 `stage_slots`:

```python
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
            name = stem.split("·", 1)[-1] if "·" in stem else stem
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
    return []   # 卡章纲/voice:卡章纲的 row 槽在 P2 需要时再加(章行是 - 第N章: 形态,_row_slots 已能认);voice 无槽
```

(注:卡章纲的 `- 第N章:`/`- 大弧:` 也是 row 形态,`_row_slots` 能认——但 P1 的落盘器 Task 4/5 覆盖它,`stage_slots` 的卡章纲分支等 P2 环境快照需要时接一行 `_row_slots(root, paths.CARD_REL)` 即可,本任务不强求。)

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_slots.py tests/test_journey.py -q`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add loom/slots.py tests/test_slots.py
git commit -m "$(cat <<'EOF'
feat(slots): filename/file 两种 at + round-robin——修三个致命洞

(a)未命名主角出 @name filename 槽压住 row 槽(否则填满 5 格 _protagonist_done
仍假、writing_unlocked 永久锁死);(b)零骨架文件出 @body file 槽(一句话定位必须
走这条,也是散文化/导入书自动降级,槽位永不归零);round-robin 交错防金手指 8 行
霸屏、代价槽新书永不可达。实体容器 label 带名字前缀。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `_land_slot` 落盘器——line/h2/row 分派(复用现有落盘通道)

**Files:**
- Modify: `loom/journey.py`(加 `_land_slot`)
- Test: `tests/test_journey.py`(扩,与既有 `test_land_*` 同区)

**Interfaces:**
- Consumes: `slots.stage_slots`(校验 slot_id 合法)、现有 `_land_field`(平台行整行替换)、`_replace_h2_body`、`_apply_card_lines`。
- Produces: `journey._land_slot(root: Path, slot_id: str, answer: str) -> str`(返回落盘的 rel);本任务只做 line/h2/row,filename/file 留 Task 5。

**背景(scout 核实的复用点):**
- `_land_field(root, field, answer)`(journey.py:379):平台格整行替换(subn count=1,无则文末补);其余 field 走 `_replace_h2_body`。
- `_replace_h2_body(text, title, new_body)`(journey.py:366):缺格→补;占位格→整体换;人写实质→格尾追加。
- `_apply_card_lines(root, body, *, fallback="")`(journey.py:456):`- 第N章:内容` 空章行填空/缺章行追加/已有人写跳过。
- **row 落盘规则**(spec §6):空行填冒号后;已填→整行替换(卡面已渲染旧值,作者知情替换);括注一个字不剥。

- [ ] **Step 1: 写失败测试**

`tests/test_journey.py` 的落盘测试区(`test_land_*` 附近)追加:

```python
def test_land_slot_line_replaces_platform(project):
    from loom.journey import _land_slot
    rel = _land_slot(project, "外置大脑/立项卡.md#平台", "番茄")
    assert rel.endswith("立项卡.md")
    assert "平台:番茄" in (project / "外置大脑/立项卡.md").read_text(encoding="utf-8")


def test_land_slot_h2_fills_placeholder(project):
    from loom.journey import _land_slot
    _land_slot(project, "外置大脑/立项卡.md#题材", "重生+复仇+宗门流")
    body = (project / "外置大脑/立项卡.md").read_text(encoding="utf-8")
    assert "重生+复仇+宗门流" in body


def test_land_slot_row_fills_after_colon_keeps_paren(project):
    from loom.journey import _land_slot
    _land_slot(project, "外置大脑/世界观/金手指.md#代价·限制", "每吞一次折寿三天")
    text = (project / "外置大脑/世界观/金手指.md").read_text(encoding="utf-8")
    assert "- 代价·限制(至少一种硬代价,不能无敌到没冲突):每吞一次折寿三天" in text  # 括注一字不剥


def test_land_slot_row_refilled_replaces_line(project):
    from loom.journey import _land_slot
    p = project / "外置大脑/世界观/金手指.md"
    _land_slot(project, "外置大脑/世界观/金手指.md#类型", "系统面板")
    _land_slot(project, "外置大脑/世界观/金手指.md#类型", "随身空间")   # 回头改
    text = p.read_text(encoding="utf-8")
    assert "随身空间" in text and text.count("系统面板") == 0        # 整行替换,旧值不残留
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_journey.py -v -k "land_slot"`
Expected: FAIL——`_land_slot` ImportError。

- [ ] **Step 3: 实现**

`loom/journey.py` 加(放在 `_land_field` 附近):

```python
_SLOT_ROW_FILL_RE_TMPL = r"^(-\s*{key}\s*(?:[(（][^)）]*[)）])?\s*[:：])(.*)$"


def _land_slot(root: Path, slot_id: str, answer: str) -> str:
    """按 slot 的 at 类型定址落盘。slot_id = "<容器rel>#<键>"。守落盘三铁律。

    P1 覆盖 line/h2/row;filename/file 见 Task 5。slot_id 必须来自 stage_slots(防越界)。"""
    from .slots import stage_slots
    answer = answer.strip()
    if not answer:
        raise ValueError("答案不能为空")
    rel, _, key = slot_id.partition("#")
    # 从 slot 集合定位 at(单一真相:落点类型由扫描器说了算,不在这里重新推断)
    slot = next((s for spec in STAGES for s in stage_slots(root, spec) if s.id == slot_id), None)
    if slot is None:
        raise ValueError(f"未知槽位:{slot_id}")
    p = root / rel
    text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    if slot.at == "line":       # 平台行:复用 _land_field 的整行替换裁量
        return _land_field(root, "平台", answer)
    if slot.at == "h2":
        atomic_write_text(p, _replace_h2_body(text, key, answer))
        return rel
    if slot.at == "row":
        pat = re.compile(_SLOT_ROW_FILL_RE_TMPL.format(key=re.escape(key)), re.M)
        if slot.key.startswith("第") or key == "大弧":   # 卡章纲行走既有 _apply_card_lines 兜底
            atomic_write_text(p, _apply_card_lines(root, f"- {key}:{answer}", fallback=answer))
            return rel
        new, n = pat.subn(lambda m: f"{m.group(1)}{answer}", text, count=1)
        if not n:   # 骨架行不在(被作者删了)→ 文末补一行,答案绝不丢
            new = text.rstrip() + f"\n- {key}:{answer}\n"
        atomic_write_text(p, new)
        return rel
    raise ValueError(f"P1 未支持的落点类型:{slot.at}(filename/file 见 Task 5)")
```

- [ ] **Step 4: 跑测试确认通过 + 全量落盘回归**

Run: `.venv/bin/python -m pytest tests/test_journey.py tests/test_slots.py -q`
Expected: 全绿。**特别看住 `test_land_*` 既有 13 条一条不红**(`_land_slot` 是新入口,不改旧 `land_answer`)。

- [ ] **Step 5: Commit**

```bash
git add loom/journey.py tests/test_journey.py
git commit -m "$(cat <<'EOF'
feat(journey): _land_slot 定址落盘 line/h2/row——复用现有落盘通道守三铁律

按 slot.at 分派:line 复用 _land_field 平台整行替换、h2 复用 _replace_h2_body
(占位换/人写追加)、row 空行填冒号后/已填整行替换且括注一字不剥;卡章纲行走
_apply_card_lines。at 类型由扫描器说了算不在此重推(单一真相)。骨架行被删则文末
补一行(答案绝不丢)。新入口,不动旧 land_answer。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `_land_slot` filename 重命名(含撞车拒绝)+ file 追加

**Files:**
- Modify: `loom/journey.py`(`_land_slot` 补 filename/file 分支)
- Test: `tests/test_journey.py`(扩)

**Interfaces:**
- Consumes: Task 4 的 `_land_slot`;`draft._FN_BAD`(文件名消毒)、`is_substantive`。
- Produces: `_land_slot` 完成五种 at。

**背景(spec §6,全设计唯一拒绝落盘点):**
- **filename:** 重命名 `主角·未命名.md` → `主角·<答案>.md`;答案取第一行截 12 字、过 `draft._FN_BAD` 消毒;**目标已存在且有实质 → 抛 ValueError 不落盘**(文件名逐字直送写手,合并两人后果太重);目标存在但仍占位 → unlink 后改名。
- **file:** 无实质→追加在标题/引导行后;有实质→追加文末。只追加。

- [ ] **Step 1: 写失败测试**

```python
def test_land_slot_filename_renames_and_unlocks(project):
    from loom.journey import _land_slot, _protagonist_done
    d = project / "外置大脑/人物"
    # 先给未命名主角填点实质(否则改名后仍非实质,门禁不认)
    unnamed = d / "主角·未命名.md"
    unnamed.write_text(unnamed.read_text(encoding="utf-8").replace(
        "- 核心欲望", "- 核心欲望:复仇\n- 旧核心欲望"), encoding="utf-8")
    _land_slot(project, "外置大脑/人物/主角·未命名.md#@name", "林潜")
    assert (d / "主角·林潜.md").is_file()
    assert not (d / "主角·未命名.md").exists()
    assert _protagonist_done(project) is True       # 门禁解锁


def test_land_slot_filename_collision_refuses(project):
    from loom.journey import _land_slot
    import pytest
    d = project / "外置大脑/人物"
    (d / "主角·林潜.md").write_text("# 主角 · 林潜\n\n- 核心欲望:复仇\n", encoding="utf-8")  # 已有实质
    with pytest.raises(ValueError):
        _land_slot(project, "外置大脑/人物/主角·未命名.md#@name", "林潜")
    assert (d / "主角·未命名.md").exists()           # 原文件没被吞


def test_land_slot_file_appends(project):
    from loom.journey import _land_slot
    _land_slot(project, "外置大脑/世界观/一句话定位.md#@body", "灵气复苏的现代都市,旧秩序崩塌")
    text = (project / "外置大脑/世界观/一句话定位.md").read_text(encoding="utf-8")
    assert "灵气复苏的现代都市" in text
    assert text.index("#") < text.index("灵气复苏")   # 追加在标题之后
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_journey.py -v -k "filename or file_appends"`
Expected: FAIL——`_land_slot` 对 filename/file 抛「P1 未支持」。

- [ ] **Step 3: 实现**

`loom/journey.py` 的 `_land_slot` 末尾 `raise ValueError(f"P1 未支持...")` 之前插入:

```python
    if slot.at == "filename":
        from .draft import _FN_BAD
        name = _FN_BAD.sub("·", answer.splitlines()[0].strip())[:12] or "未命名"
        role = Path(rel).stem.split("·")[0].split("・")[0].split("•")[0]
        target = p.with_name(f"{role}·{name}.md")
        if target.exists() and is_substantive(target.read_text(encoding="utf-8", errors="replace")):
            raise ValueError(f"已经有一个叫「{name}」的{role}了——换个名字,或先合并那张卡")
        if target.exists():   # 占位残卡,让位
            target.unlink()
        p.rename(target)
        return str(target.relative_to(root))
    if slot.at == "file":
        joiner = "\n" if text.endswith("\n") else "\n\n"
        atomic_write_text(p, (text.rstrip() + joiner + answer + "\n") if text.strip() else f"{answer}\n")
        return rel
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿(449 基线 + P1 新增测试)。

- [ ] **Step 5: Commit**

```bash
git add loom/journey.py tests/test_journey.py
git commit -m "$(cat <<'EOF'
feat(journey): _land_slot 补 filename 重命名(撞车拒绝)+ file 追加

filename:重命名未命名卡→主角·名字.md(_FN_BAD 消毒、截12字),目标已有实质则抛
ValueError 不落盘(文件名逐字直送写手,合并两人后果太重,全设计唯一拒绝点),占位
残卡则让位。file:无实质追加在标题后、有实质追加文末,只追加。五种 at 齐。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: P1 全量回归 + 边界巡查(控制者亲验)

**Files:** 无代码改动;只验证。

- [ ] **Step 1: 全量测试 + eval 门禁**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m evals.run_eval --gate`
Expected: 全绿;eval 门禁 PASS。

- [ ] **Step 2: 离线烟测——扫描器+落盘器闭环(zero model)**

在 scratchpad 建一本新书,`.venv/bin/python` 脚本跑一遍:`stage_slots` 各段计数(立项 5 / 世界观应含 file+row / 人物 3 个 filename / 卡章纲 6 含大弧)→ 对每个未填槽 `_land_slot` 填值 → 再扫确认 filled 翻真、`writing_unlocked` 随主角命名解锁。**先钉临时书,绝不碰真书。**

- [ ] **Step 3: 汇报**

向用户报:P1 新增测试计数、各段槽位数、落盘闭环截图/输出。不合并——P1 是 P2/P3 的地基,等三块齐了统一终审。

---

## P2 / P3 预告(本计划不含,各自另立)

| 计划 | 内容 | 依赖 |
|---|---|---|
| **P2 对话循环** | `partner.py`(assemble/loop/registry)+ parse 工具协议(`用:`/`键:值`+流式行缓冲纪律)+ `.伙伴对话/` jsonl 存储 + 三工具(读文件/看地基=stage_slots/提设定)+ 环境快照(stage_slots 投影)+ ScriptedBackend | P1(看地基/落盘直接调) |
| **P3 接线与迁移** | server /api/partner/say(流式+锁裁量)/confirm/new/history + 双形态对话 UI + 退役卡片机(next_card/land_answer/goto)+ demo 罐头多轮 + CLI 护栏伙伴变体 + ADR 0015/0014 修订 + CONTEXT/领航员.md 改写 | P1+P2 |

设计权威:〔[书房伙伴设计](../specs/2026-07-16-navigator-agent-design.md)〕。三块齐后统一走全分支终审 + finishing-a-development-branch。
