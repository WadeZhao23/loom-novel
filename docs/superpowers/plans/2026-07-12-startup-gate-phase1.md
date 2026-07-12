# 起书完整性硬门禁 · 一期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 起书资料(立项+世界观+主角+前几章纲)没填齐,就不给写第一章——新书冷启动硬门禁完整生效。

**Architecture:** `journey.py` 当唯一完整性权威(新增 `writing_unlocked` 纯文件派生谓词);`write_precheck` 单点接门禁(force 之前);门禁仅当「无 Loom 织章(无任何 `.原稿` 快照)」时启用——存量书零伤害、导入书照拦。前端收编 `brain_ready` 软拦为门禁引导卡。二期(导入诊断)与 IP 形象设计另拆。设计依据:[spec](../specs/2026-07-12-startup-completeness-gate-design.md)。

**Tech Stack:** 纯 stdlib Python(re/pathlib)+ 既有 loom 模块(journey/paths/parse/state/scaffold)+ vanilla JS。零新依赖。

## Global Constraints(每个任务隐含遵守)

- **门禁只住 `write_precheck`,绝不下沉 `run_pipeline`**(否则 golden/流水线测试全炸,违单点)。
- **force 不越门禁**:门禁检查放 force 短路之前;force 只豁免"已存在/漂移"。
- **作用域 = 无 Loom 织章即拦**:本书无任何 `.原稿` 快照时才启用门禁。判据 `paths.snapshot_path(root, n).exists()`,纯文件派生、零迁移。
- **完整性四项 = 立项 + 世界观 + 主角 + 卡章纲**(voice 不进门禁);谓词全部纯文件派生、无第二状态真相。
- **主角硬判**:只填反派卡不算过(与专名册同源口径:带分隔符 `·/・/•`、非占位/未命名)。
- **立项/章纲放宽救导入**:格式命中 OR 整体有实质非模板内容。
- **落盘一律 `atomic_write_text`**;`is_substantive`/`strip_placeholder_hints` 来自 `loom.parse`。
- 门禁错误 `code="brain_incomplete"`,带 `missing[]`+`stage`;前端**按 code 分支**,绝不渲染成"已存在+覆盖重写"。
- 提交信息中文、`feat(gate)/fix/docs`;测试统一 `.venv/bin/python -m pytest`。

---

### Task 1: 完整性谓词(journey.py)——放宽立项/章纲、收紧主角、writing_unlocked

**Files:**
- Modify: `loom/journey.py`(谓词区 64-94 附近)
- Test: `tests/test_gate_predicate.py`

**Interfaces:**
- Consumes: `paths.PROJECT_CARD_REL/CARD_REL/CHARS_REL/CHARS_DIR_REL/GROWTH_NAME`、`paths.brain_form/brain_dir_files`、`parse.is_substantive`、既有 `stage_done/_project_card_done/_h2_body/_CARD_FIELDS/_CARD_LINE_RE/STAGES`
- Produces:
  - `writing_unlocked(root: Path) -> tuple[bool, list[str]]`(缺项用 STAGES key,顺序 立项/世界观/人物/卡章纲)
  - `_protagonist_done(root: Path) -> bool`
  - `stage_done` 行为变更:人物段=`_protagonist_done`;立项/章纲段放宽(整体实质兜底)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_gate_predicate.py
"""起书完整性谓词:立项/章纲放宽救导入、主角硬判、writing_unlocked 四项。"""
from pathlib import Path

from loom import journey
from loom.paths import PROJECT_CARD_REL, CARD_REL


def test_fresh_template_book_locked(project):
    ok, missing = journey.writing_unlocked(project)
    assert ok is False
    assert missing == ["立项", "世界观", "人物", "卡章纲"]   # 模板书四项全缺、voice 不算


def test_kaczhang_prose_form_unlocks(project):
    # 段落式章纲(导入形态,无「- 第N章:」行)也算达标
    (project / CARD_REL).write_text("# 卡章纲\n\n开局主角雪夜被逐出宗门,捡到会说话的青铜鼎,立誓复仇。\n", encoding="utf-8")
    assert "卡章纲" not in journey.writing_unlocked(project)[1]


def test_project_card_imported_heading_unlocks(project):
    # 导入立项卡内容拼在「## 来自:xxx」头下,四格谓词抓不到,但整卡有实质→算达标
    (project / PROJECT_CARD_REL).write_text(
        "# 立项卡\n\n## 来自:我的设定.md\n番茄男频,重生权谋朝堂争斗流,对标《庆余年》。\n", encoding="utf-8")
    assert "立项" not in journey.writing_unlocked(project)[1]


def test_only_villain_card_does_not_pass_protagonist(project):
    (project / "外置大脑/人物/反派·魔尊.md").write_text("# 反派\n\n手段狠辣的魔道尊主。\n", encoding="utf-8")
    assert journey._protagonist_done(project) is False
    assert "人物" in journey.writing_unlocked(project)[1]


def test_protagonist_card_passes(project):
    (project / "外置大脑/人物/主角·林潜.md").write_text("# 主角\n\n废柴出身,吞噬万物的胃袋金手指。\n", encoding="utf-8")
    assert journey._protagonist_done(project) is True


def test_all_four_unlocks(project):
    (project / PROJECT_CARD_REL).write_text("# 立项卡\n\n## 题材\n重生权谋\n", encoding="utf-8")
    (project / "外置大脑/世界观/金手指.md").write_text("# 金手指\n\n吞噬胃袋,代价挂寿命。\n", encoding="utf-8")
    (project / "外置大脑/人物/主角·林潜.md").write_text("# 主角\n\n废柴逆袭。\n", encoding="utf-8")
    p = project / CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:雪夜被逐,捡到鼎"), encoding="utf-8")
    ok, missing = journey.writing_unlocked(project)
    assert ok is True and missing == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_gate_predicate.py -v`
Expected: FAIL,`AttributeError: ... 'writing_unlocked'`

- [ ] **Step 3: 写实现(journey.py)**

在谓词区(`_CARD_FIELDS/_CARD_LINE_RE` 之后)加常量与 `_all_h2`:

```python
_NAME_SEP = ("·", "・", "•")   # 与 agents._NAME_SEP 同一口径:专名册只认带分隔符的「类型·名字」标题
_PROTAG_HEAD_RE = re.compile(r"^##\s*主角\s*[·・•]\s*\S", re.M)
_GATE_STAGES = ("立项", "世界观", "人物", "卡章纲")   # voice 不进门禁


def _all_h2(text: str) -> list[tuple[str, str]]:
    """粗切 (H2标题, 段落体) 列表——救导入立项卡的非标准 H2(如「## 来自:xxx」)。"""
    out: list[tuple[str, str]] = []
    for chunk in re.split(r"^##\s+", text, flags=re.M)[1:]:
        head, _, body = chunk.partition("\n")
        out.append((head.strip(), body))
    return out
```

`_project_card_done` 加整卡兜底(替换现实现):

```python
def _project_card_done(root: Path) -> bool:
    """四格任一实质;或救导入——任一非模板 H2 段有实质(整卡兜底,不误吃模板占位/平台默认行)。"""
    p = root / paths.PROJECT_CARD_REL
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    if any(is_substantive(_h2_body(text, f)) for f in _CARD_FIELDS):
        return True
    return any(is_substantive(body) for head, body in _all_h2(text) if head not in _CARD_FIELDS)
```

加 `_protagonist_done`:

```python
def _protagonist_done(root: Path) -> bool:
    """至少一张「主角·名字」实质卡;只填反派/未命名/占位不算(同专名册口径)。"""
    form = paths.brain_form(root, paths.CHARS_REL, paths.CHARS_DIR_REL)
    if form == "dir":
        return any(f.name != paths.GROWTH_NAME and f.stem.startswith("主角")
                   and any(s in f.stem for s in _NAME_SEP) and "未命名" not in f.stem
                   and is_substantive(f.read_text(encoding="utf-8"))
                   for f in paths.brain_dir_files(root, paths.CHARS_DIR_REL))
    if form == "file":
        p = root / paths.CHARS_REL
        return p.is_file() and bool(_PROTAG_HEAD_RE.search(p.read_text(encoding="utf-8")))
    return False
```

`stage_done` 改人物段收紧 + 章纲段放宽(替换现实现):

```python
def stage_done(root: Path, spec: StageSpec) -> bool:
    if spec.land == "seed":
        return load_state(root).get("fingerprint_source", "default") != "default"
    if spec.land == "field":
        return _project_card_done(root)
    if spec.land == "card_lines":
        p = root / spec.target
        if not p.is_file():
            return False
        text = p.read_text(encoding="utf-8")
        return bool(_CARD_LINE_RE.search(text)) or is_substantive(text)   # 放宽:段落式章纲也算
    if spec.key == "人物":
        return _protagonist_done(root)   # 硬判主角,面板与门禁同口径(只填反派不算过)
    return any(_rel_has_content(root, rel) for rel in spec.reads)
```

文件末尾加 `writing_unlocked`:

```python
def writing_unlocked(root: Path) -> tuple[bool, list[str]]:
    """起书完整性:立项+世界观+主角+卡章纲 是否齐;返回 (解锁?, 缺项 STAGES key 列表)。纯文件派生。"""
    missing = [s.key for s in STAGES if s.key in _GATE_STAGES and not stage_done(root, s)]
    return (not missing, missing)
```

- [ ] **Step 4: 跑测试确认通过 + journey 回归**

Run: `.venv/bin/python -m pytest tests/test_gate_predicate.py tests/test_journey.py -v`
Expected: 新测试全过;`test_journey.py` 若有断言"只填任一人物即 人物 done"的用例因主角收紧而红,按新语义更新(改用 `主角·名字.md`,不许削弱主角硬判)。

- [ ] **Step 5: 提交**

```bash
git add loom/journey.py tests/test_gate_predicate.py tests/test_journey.py
git commit -m "feat(gate): 完整性谓词——立项/章纲放宽救导入+主角硬判+writing_unlocked 四项(纯文件派生)"
```

---

### Task 2: 门禁接线(write_precheck,force 前 + 无 Loom 织章作用域)+ CLI KeyError 修

**Files:**
- Modify: `loom/usecases.py`(`write_precheck` 88-95;import 区已有 `journey as journey_mod`、`paths`)
- Modify: `loom/cli.py`(write 命令 168-170 的 code 字典)
- Test: `tests/test_gate_precheck.py`;改 `tests/test_usecases.py`、`tests/test_server_write_lock.py`

**Interfaces:**
- Consumes: `journey_mod.writing_unlocked(root)`、`paths.snapshot_path/chapter_numbers/chapter_path`、`ledger.chapter_drifted`
- Produces: `write_precheck` 新增 `code="brain_incomplete"` 分支(带 `missing`+`stage`);`_has_loom_chapter(root: Path) -> bool`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_gate_precheck.py
"""起书门禁:无 Loom 织章的新书拦第一章、force 不越门禁、有 Loom 织章的书豁免。"""
from pathlib import Path

from loom import usecases, paths, ledger


def _ready(project):
    (project / paths.PROJECT_CARD_REL).write_text("# 立项卡\n\n## 题材\n重生权谋\n", encoding="utf-8")
    (project / "外置大脑/世界观/金手指.md").write_text("# 金手指\n\n吞噬胃袋。\n", encoding="utf-8")
    (project / "外置大脑/人物/主角·林潜.md").write_text("# 主角\n\n废柴逆袭。\n", encoding="utf-8")
    p = project / paths.CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:雪夜被逐"), encoding="utf-8")


def test_bare_book_blocks_with_brain_incomplete(project):
    rej = usecases.write_precheck(project, 1, False)
    assert rej["code"] == "brain_incomplete"
    assert rej["missing"] == ["立项", "世界观", "人物", "卡章纲"]
    assert rej["stage"] == "立项"


def test_force_does_not_bypass_gate(project):
    rej = usecases.write_precheck(project, 1, True)   # force 不越门禁
    assert rej["code"] == "brain_incomplete"


def test_ready_book_passes(project):
    _ready(project)
    assert usecases.write_precheck(project, 1, False) is None


def test_book_with_loom_chapter_is_exempt(project):
    # 有 Loom 织的章(有 .原稿 快照)→ 门禁豁免,回落原三态
    out = paths.chapter_path(project, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 第1章\n\n正文。\n", encoding="utf-8")
    ledger.record_snapshot(project, 1, out.read_text(encoding="utf-8"))
    assert usecases.write_precheck(project, 2, False) is None   # 写第2章:大脑空也豁免(书已在写)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_gate_precheck.py -v`
Expected: FAIL(现 `write_precheck(裸书,1,False)` 返 None,`test_bare_book_blocks` 红)

- [ ] **Step 3: 写实现(usecases.py)**

`write_precheck` 上方加 helper:

```python
def _has_loom_chapter(root: Path) -> bool:
    """本书有没有任何 Loom 织出的章(判据:存在 .原稿 快照)。导入章无快照 → 视作未织。"""
    return any(paths.snapshot_path(root, n).exists() for n in paths.chapter_numbers(root))
```

`write_precheck` 改为(门禁在 force 短路之前):

```python
def write_precheck(root: Path | str, chapter: int, force: bool = False) -> dict | None:
    """写前检查:None=放行;否则 {"error","code",...}(措辞即 server 409 响应体)。
    起书完整性硬门禁在最前:仅当本书还没有 Loom 织的章时启用,force 不越它。"""
    root = Path(root)
    if not _has_loom_chapter(root):
        ok, missing = journey_mod.writing_unlocked(root)
        if not ok:
            names = "、".join(missing)
            return {"error": f"开书资料还差:{names}。在伙伴面板答几题即可解锁"
                             f"(或手填 外置大脑/ 对应文件)。",
                    "code": "brain_incomplete", "missing": missing, "stage": missing[0]}
    if force or not paths.chapter_path(root, chapter).exists():
        return None
    if ledger.chapter_drifted(root, chapter):
        return {"error": f"第 {chapter} 章正文与上次记录不符(手改过?)。先 learn,或勾选覆盖以你的正文为准重写。",
                "code": "chapter_drifted"}
    return {"error": f"第 {chapter} 章已写完。要重写请勾选覆盖。", "code": "chapter_exists"}
```

- [ ] **Step 4: 改 cli.py KeyError(168-170)**

把字典下标改 `.get` 兜底(新 code 直接用 precheck 自带 error 文案):

```python
        if rej:
            _die({"chapter_drifted": f"第 {chapter} 章正文与上次记录不符(你手改过?)。"
                                     f"先 learn {chapter},或加 --force 以你的正文为准重写。",
                  "chapter_exists": f"第 {chapter} 章已写完。要重写加 --force。"}
                 .get(rej["code"], rej["error"]))   # 新 code(brain_incomplete)用 precheck 自带文案,不 KeyError
```

- [ ] **Step 5: 改既有必炸测试**

`tests/test_usecases.py` 的 `test_write_precheck_three_states`:首行裸书断言改为门禁前置(书需先 ready 或先造 Loom 章)。最小改法——在函数体最前面把书铺成 ready(复用 Task 2 的 `_ready` 逻辑内联)或直接造一章带快照再测三态。采用后者(三态本就在测已存在/drifted,天然需要一章):

```python
def test_write_precheck_three_states(project):
    out = paths.chapter_path(project, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 第1章\n\n正文。\n", encoding="utf-8")
    ledger.record_snapshot(project, 1, out.read_text(encoding="utf-8"))   # 造 Loom 章 → 门禁豁免
    assert usecases.write_precheck(project, 1, True) is None              # force 放行
    rej = usecases.write_precheck(project, 1, False)
    assert rej["code"] == "chapter_exists"
    out.write_text("# 第1章\n\n我手改过的正文。\n", encoding="utf-8")
    assert usecases.write_precheck(project, 1, False)["code"] == "chapter_drifted"
```

`tests/test_server_write_lock.py`:裸书 POST /api/write 第1章现会被门禁 409(而非 200)。在 `run_first` 前把 project 铺成 ready 或造带快照的章。因该测试意在验并发锁、`fake_pipeline` 桩不真写正文,最省改法=测第2章 + 预置第1章快照豁免门禁:

```python
    # 预置一章 Loom 快照 → 门禁豁免,专测并发锁(body 改写第2章)
    from loom import ledger, paths as _paths
    c1 = _paths.chapter_path(project, 1); c1.parent.mkdir(parents=True, exist_ok=True)
    c1.write_text("# 第1章\n\nx\n", encoding="utf-8")
    ledger.record_snapshot(project, 1, c1.read_text(encoding="utf-8"))
    body = {"root": str(project), "chapter": 2}
```
(其余断言不变;若测试硬编码 chapter 1 多处,统一改 2。)

- [ ] **Step 6: 跑测试确认通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_gate_precheck.py tests/test_usecases.py tests/test_server_write_lock.py -v && .venv/bin/python -m pytest -q`
Expected: 全过(golden/流水线零改动——门禁不下沉 run_pipeline)

- [ ] **Step 7: 提交**

```bash
git add loom/usecases.py loom/cli.py tests/test_gate_precheck.py tests/test_usecases.py tests/test_server_write_lock.py
git commit -m "feat(gate): write_precheck 接门禁——无Loom织章即拦/force前置/code=brain_incomplete;cli KeyError 兜底"
```

---

### Task 3: project_state 暴露 writing_unlocked + missing(收编 brain_ready 供前端)

**Files:**
- Modify: `loom/usecases.py`(`project_state` 277-294)
- Test: `tests/test_usecases.py`(追加)

**Interfaces:**
- Produces: `project_state` 返回 dict 新增 `"writing_unlocked": bool`、`"missing": list[str]`(brain_ready 键保留,前端逐步弃用)

- [ ] **Step 1: 写失败测试(追加 test_usecases.py)**

```python
def test_project_state_exposes_gate(project):
    st = usecases.project_state(project)
    assert st["writing_unlocked"] is False
    assert st["missing"] == ["立项", "世界观", "人物", "卡章纲"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_usecases.py::test_project_state_exposes_gate -v`
Expected: FAIL,`KeyError: 'writing_unlocked'`

- [ ] **Step 3: 写实现(project_state 的 return dict 内,brain_ready 行旁加)**

```python
        "brain_ready": brain_ready(root),   # 弱判据:铺过底(保留供旧前端,门禁判据用下面两项)
        "writing_unlocked": journey_mod.writing_unlocked(root)[0],
        "missing": journey_mod.writing_unlocked(root)[1],
```

（`journey_mod` 已在 import 区。为省一次重算可先 `_wu = journey_mod.writing_unlocked(root)` 再取 `_wu[0]/_wu[1]`——文件小、可读优先,二选一。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_usecases.py -v`
Expected: 全过

- [ ] **Step 5: 提交**

```bash
git add loom/usecases.py tests/test_usecases.py
git commit -m "feat(gate): project_state 暴露 writing_unlocked+missing(前端软拦收编 brain_ready)"
```

---

### Task 4: 前端收编——409 按 code 分支 + 软拦升级门禁引导卡(app.js)

**Files:**
- Modify: `loom/webui/app.js`(writeChapter 409 分支 1593-1603;软拦 showGuide 1560-1572)

**Interfaces:**
- Consumes: `DATA.writing_unlocked`、`DATA.missing`(Task 3);既有 `showGuide/postJourneyGoto/draftBrain`、`localStorage loom_journey_dismiss`

- [ ] **Step 1: 改 writeChapter 的 409 分支(按 code 分支,brain_incomplete 不渲染"已存在")**

```js
      if (resp.status === 409) {
        if (d.code === "brain_incomplete") {
          openGateGuide(d.missing || []);          // 门禁:引导去补齐,绝不给覆盖按钮
        } else {
          $("run-title").textContent = `第 ${n} 章已存在`;
          showRunForce(n);                          // 仅 chapter_exists/drifted 才给覆盖
        }
      }
```

- [ ] **Step 2: 软拦升级——把 1560-1572 的 brain_ready 块换成门禁块(删「就这样写」)**

```js
  // 起书完整性硬门禁:四项没齐 → 引导去补,不再给「就这样写」逃生门(硬门禁下它必撞 409)
  if (DATA.writing_unlocked === false) {
    openGateGuide(DATA.missing || []);
    return;
  }
```

新增 `openGateGuide`(放 showGuide 附近):

```js
function openGateGuide(missing) {
  const first = missing[0];
  localStorage.removeItem("loom_journey_dismiss:" + DATA.root);   // 一键去补前先解除面板收起
  showGuide({
    title: "先把开书地基打完",
    bodyHtml:
      `<p class="guide-lead">还差:${(missing.length ? missing : ["起书资料"]).join("、")}。没有这些上下文,AI 只能瞎编、和你的书对不上。</p>` +
      `<p class="hint">在伙伴面板答几题就能补齐;或让 AI 按书名先铺一版设定底稿(世界观/人物/章纲)。</p>`,
    primary: { label: "去伙伴面板补齐", fn: () => first && postJourneyGoto(first, false) },
    ghost: { label: "✨ AI 铺底稿", fn: () => draftBrain("") },
  });
}
```

（说明:primary=去补齐(聚焦首缺段);ghost 位放 AI 铺底稿——它一次点击过世界观/人物/章纲三项,最短通路;**不再有「就这样写」**。立项段若缺,postJourneyGoto 聚焦立项、领航员出立项题。)

- [ ] **Step 3: 语法校验 + 手动验证(loom-dev 8792,调试测试书是空书=被拦)**

```bash
node --check loom/webui/app.js
```
在 preview(调试测试书,四项空):点「写下一章」→ 弹「先把开书地基打完 · 还差:立项、世界观、人物、卡章纲」,primary「去伙伴面板补齐」聚焦立项段、**无「就这样写」**;不再出现"第1章已存在"。截图留证。

- [ ] **Step 4: 提交**

```bash
git add loom/webui/app.js
git commit -m "fix(webui): 门禁前端收编——409 按 code 分支不渲染已存在/软拦升级门禁引导卡/删「就这样写」逃生门"
```

---

### Task 5: skip 语义修正(门禁段禁跳过 + exhausted 守卫 + 面板文案)

**Files:**
- Modify: `loom/journey.py`(`goto` 131-150;`next_card` exhausted 210-216)
- Modify: `loom/webui/app.js`(「跳过这段」按钮 777/783/804;head 计数)
- Test: `tests/test_journey.py`(追加)

**Interfaces:**
- Consumes: `_GATE_STAGES`(Task 1)、`stage_done`
- Produces: `goto` 对门禁段拒绝 `skip=True`(静默降级为聚焦);`next_card` exhausted 仅在 `stage_done` 真时跳段

- [ ] **Step 1: 写失败测试(追加 test_journey.py)**

```python
def test_gate_stage_cannot_be_skipped(project):
    s = journey.goto(project, "世界观", skip=True)   # 门禁段禁跳
    assert next(x for x in s["stages"] if x["key"] == "世界观")["skipped"] is False
    assert s["current"] == "世界观"                   # 降级为聚焦本段,不跳走


def test_voice_stage_can_still_skip(project):
    s = journey.goto(project, "voice", skip=True)
    assert next(x for x in s["stages"] if x["key"] == "voice")["skipped"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_journey.py -k "gate_stage_cannot or voice_stage_can" -v`
Expected: FAIL(现 goto 对任意段都写 skip)

- [ ] **Step 3: 改 goto(门禁段禁 skip → 降级为聚焦)**

`goto` 里 `_stage_spec(stage)` 之后加:

```python
    if skip and stage in _GATE_STAGES:
        return goto(root, stage, skip=False)   # 门禁段不许跳过,降级为「回头改/聚焦本段」
```

改 `next_card` exhausted 分支(仅在该段谓词已真时才自动跳段,防空文件误判死锁):

```python
    if parsed and parsed.get("exhausted"):
        spec = _stage_spec(cur)
        if stage_done(root, spec):
            j["skips"][cur] = True   # 真做完了才跳;没做完时无题=模型误判,不跳
            j["card"] = None
            st["journey"] = j
            save_state(root, st)
            return next_card(root, backend) if journey_state(root)["current"] else \
                {"card": None, "state": journey_state(root)}
        # 没做完却报无题 → 降级卡,给自由输入出口,别死锁
        parsed = None
```

（`parsed=None` 后落到既有降级卡分支;确认 `cur`/`j`/`st` 在该分支作用域内可用,必要时把 `spec = _stage_spec(cur)` 提到分支前。)

- [ ] **Step 4: 前端「跳过这段」按门禁段改文案/隐藏**

`paintJourney` 里三处「跳过这段」按钮:门禁段(`_GATE_STAGES` 对应,前端用段 key 判)改标签「先放放」并仍走 `postJourneyGoto(cur,false)`(聚焦,不 skip);仅 voice 段保留真「跳过这段」(`postJourneyGoto(cur,true)`)。head 计数保持 `done||skipped`。最小改法:

```js
  const GATE = ["立项", "世界观", "人物", "卡章纲"];
  const isGate = GATE.includes(JOURNEY.current);
  const skipBtn = isGate
    ? jcBtn("先放放", () => postJourneyGoto(JOURNEY.current, false), true)   // 门禁段:聚焦不跳
    : jcBtn("跳过这段", () => postJourneyGoto(JOURNEY.current, true), true);
```
（三处「跳过这段」统一替换为 `skipBtn` 变量;面板顶「伙伴 · 起书访谈 N/5」保留。）

- [ ] **Step 5: 跑测试 + 语法校验 + 全量**

Run: `.venv/bin/python -m pytest tests/test_journey.py -v && node --check loom/webui/app.js && .venv/bin/python -m pytest -q`
Expected: 全过

- [ ] **Step 6: 提交**

```bash
git add loom/journey.py loom/webui/app.js tests/test_journey.py
git commit -m "fix(gate): skip 修正——门禁四段禁跳过(降级聚焦)/exhausted 仅段真时跳/面板「跳过」改「先放放」"
```

---

### Task 6: 建书题材代落立项「题材」格 + 样例书补立项卡(让默认路径过立项)

**Files:**
- Modify: `loom/scaffold.py`(`init` 的 platform 代落段 108-111 附近)
- Create: `loom/sample/外置大脑/立项卡.md`
- Test: `tests/test_create_seed.py`(追加)

**Interfaces:**
- Consumes: `_resolve_genre`、`PROJECT_CARD_REL`、`atomic_write_text`

- [ ] **Step 1: 写失败测试(追加 test_create_seed.py)**

```python
def test_genre_lands_into_project_card(tmp_path):
    from loom import journey
    root = scaffold_init("题材落卡书", parent=tmp_path, genre="重生")
    text = (root / "外置大脑/立项卡.md").read_text(encoding="utf-8")
    assert "重生" in journey._h2_body(text, "题材")
    assert journey._project_card_done(root) is True   # 建完即过立项谓词
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_create_seed.py::test_genre_lands_into_project_card -v`
Expected: FAIL(现 genre 只拷题材速查、不写立项卡)

- [ ] **Step 3: 改 scaffold.init(platform 代落段之后加 genre 代落「题材」格)**

```python
    # 建书框选的题材代落立项卡「## 题材」格(同平台行先例:作者填的,loom 只代为落盘)
    if genre and genre.strip():
        card = target / PROJECT_CARD_REL
        text = card.read_text(encoding="utf-8")
        text = re.sub(r"(^##\s*题材\s*$).*?(?=^##\s|\Z)",
                      lambda m: f"{m.group(1)}\n{genre.strip()}\n\n", text, count=1, flags=re.M | re.S)
        atomic_write_text(card, text)
```

（用作者原始 `genre` 文本,不经 `_resolve_genre` 归一——立项卡是给人看的散文,原样落更贴作者意图;`_resolve_genre` 仍只管拷题材速查。）

- [ ] **Step 4: 建样例书立项卡**

`loom/sample/外置大脑/立项卡.md`(填好的、非占位——否则样例书虽有 Loom 章豁免门禁,但"打开样例学一本完整的书"应展示完整立项):

```markdown
# 立项卡 / 这本书的定位

平台:起点

## 分区
玄幻 · 东方玄幻

## 题材
重生 + 记忆金手指 + 复仇逆袭

## 对标意图
开局被踩到谷底、靠前世记忆步步翻盘的爽感节奏。

## 为什么选它
这个分区读者吃「憋屈—打脸」闭环,也是我最擅长写的。
```

- [ ] **Step 5: 跑测试确认通过 + 全量(样例书 golden/冒烟不受影响)**

Run: `.venv/bin/python -m pytest tests/test_create_seed.py -v && .venv/bin/python -m pytest -q`
Expected: 全过

- [ ] **Step 6: 提交**

```bash
git add loom/scaffold.py loom/sample/外置大脑/立项卡.md tests/test_create_seed.py
git commit -m "feat(gate): 建书题材代落立项「题材」格(平台行先例)+ 样例书补完整立项卡"
```

---

### Task 7: 文案六处改口 + ADR 0014

**Files:**
- Modify: `loom/templates/外置大脑/立项卡.md`(第 3-5 行)、`docs/使用教程.md`(220/208/108/61 区)、`CONTEXT.md`(立项卡词条 12 行)、`loom/webui/app.js`(导入弹窗 397)
- Create: `docs/adr/0014-startup-completeness-gate.md`

**Interfaces:** 无代码接口。

- [ ] **Step 1: 立项卡模板改口(templates/外置大脑/立项卡.md 第 3-5 行)**

把"loom 从不自动写它 / 缺卡空卡照常出稿 / 五格全可空"三句里与门禁冲突的部分改为:

```markdown
> **人手维护**的一张定位卡:这本书写给谁看、放在哪、对标谁。除建书时代落你选的平台/题材外,loom 不改它。
> 起书要先有定位——立项、世界观、主角、前几章纲都填齐了,才能开写第一章(没上下文 AI 只会瞎编)。
> `平台:` 那一行是可解析行(违禁词自检读它定基线);其余几格随便你怎么写,任一格有内容即算立项完成。
```

- [ ] **Step 2: 教程改口(docs/使用教程.md)**

- 第 220 行「都可空、留空照常出稿」→ 改为区分:世界观/人物/章纲是开书地基(要有内容才能写第一章),文风参考才是可选。
- 第 208 行「护栏只提示、不阻断出稿」→ 加限定:「(写作中的护栏不阻断;唯一例外是**开写前的起书地基**——立项/世界观/主角/章纲没齐,不给写第一章。)」
- 第 108 行「或全部跳过,面板自动收起」→ 「起书四段不能跳过(它们是开写地基);voice 段可跳。四段齐了面板自动收起。」
- 第 61 行标题「三分钟跑通第一章」→ 「答题起书,五分钟跑通第一章」(TOC 第 13 行锚点同步);正文顺序说明改为「先在伙伴面板把四项答齐 → 写第一章」。

（逐行读现文照改,保持教程语气;锚点改了同步 TOC。）

- [ ] **Step 3: CONTEXT.md 立项卡词条改口(第 12 行)**

「各格可选、留空也行」→ 「各格可空(任一格有内容即算立项完成);**立项/世界观/主角/前几章纲是开写第一章的硬门槛**(见 [ADR 0014](docs/adr/0014-startup-completeness-gate.md)),不是可选。平台由建书代落、题材建书时代落其余人手填,loom 不另改。」

- [ ] **Step 4: 导入弹窗改口(app.js 第 397 行)**

```js
    `<p class="hint">你的设定原样进来了。缺立项/世界观/主角/章纲的话,写第一章前伙伴会带你补齐。</p>`,
```

- [ ] **Step 5: 写 ADR 0014(照 0011/0013 格式)**

`docs/adr/0014-startup-completeness-gate.md`:

```markdown
# 起书完整性硬门禁:立项/世界观/主角/章纲没齐,不给写第一章

> 状态:**已采纳**(一期实现:writing_unlocked 谓词 + write_precheck 接线 + 前端引导卡;设计见 [spec](../superpowers/specs/2026-07-12-startup-completeness-gate-design.md))。

起因是作者实报:外置大脑空着直接交给 AI 写,没有上下文,出的就是套路烂稿。ADR 0011 当初定「立项各格可选、缺卡空卡照常出稿」,是把"要不要有定位"完全交给作者;但"答题起书"一期上线后,产品立意变成「先想清楚再写」——起书地基没打完就不该开写。本 ADR 把这条从"引导"升级成"硬门禁"。

## 决定:加一条起书完整性硬门禁,仅在真·开书时启用

`journey.writing_unlocked(root)` 纯文件派生判「立项+世界观+主角+前几章纲」是否齐;`usecases.write_precheck` 在最前(force 之前)查它:
- **作用域 = 无 Loom 织章即拦**:本书没有任何 `.原稿` 快照(=Loom 没织过)时才启用。新书第一章拦、导入书首次让 Loom 续写拦、写到一半的老 Loom 书全豁免、样例书豁免。存量零迁移、零回溯锁。
- **force 不越门禁**:force 只豁免"已存在/漂移",不豁免完整性。
- **一次性解锁**:四项齐即开,不逐章硬查(插空章会错位行号)。
- **主角硬判**:只填反派卡不算过(与写手专名册同口径)。立项/章纲放宽(整体实质兜底)救导入书。

## 与 ADR 0011 / 0006 的关系

- **supersede ADR 0011「缺卡/空卡照常出稿」条款**:该红线作废(立项现进门禁)。0011 的「不回写:loom 从不自动写立项卡」**保留**——建书代落平台/题材、访谈代落是"作者填、工具代落盘",不是 AI 发明。
- **不动 ADR 0006**:完整性门禁是**生成前**的输入门槛,ADR 0006 管的是**生成后**质量复审不阻断——两回事,0006 一字不动。防日后"Loom 从不阻断"被反向引来推翻门禁。

## Considered Options(选摘)

- **独立 gate.py**——否决:完整性双定义必漂;且 `gate` 在库内=质量关卡「绝不阻断」,硬阻断模块同名=词表污染。
- **每章都拦 / 逐章查章纲行**——否决:插空章错位行号→每章误锁;存量老书回溯锁。改「无 Loom 织章即拦」。
- **豁免位存 state**——否决:第二状态真相,游标丢了重新上锁,违 [ADR 0013](0013-journey-orchestration-no-langgraph.md)。

## 红线

- **门禁只住 write_precheck**:绝不下沉 run_pipeline(否则炸流水线测试、违单点)。
- **纯文件派生、无第二真相**:谓词全从盘上文件算;删空世界观会重新上锁,是已知行为(同"改 md 签名失配重跑"哲学),非 bug。
- **诊断/AI 不碰立项卡**:立项永远走访谈/手填/建书代落(守 0011「不回写」)。
```

- [ ] **Step 6: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿(纯文档/文案改动)

```bash
git add loom/templates/外置大脑/立项卡.md docs/使用教程.md CONTEXT.md loom/webui/app.js docs/adr/0014-startup-completeness-gate.md
git commit -m "docs(gate): 文案六处改口(立项卡模板/教程三处/CONTEXT/导入弹窗)+ ADR 0014 起书完整性硬门禁(supersede 0011 不阻断条款)"
```

---

### Task 8: 领航员头像 wiring(IP 形象接位,graceful fallback)

**Files:**
- Modify: `loom/webui/app.js`(`AGENTS_META` 864-870;伙伴面板 head 731 附近加头像位)
- Modify: `loom/webui/style.css`(头像样式)

**Interfaces:**
- Consumes: 既有 `agentAvatar(name, imgCls, fbCls)`(app.js:871,`/agents/<slug>.jpg` + onerror 首字兜底)

**说明:** 领航员头像图 `navigator.jpg` 由 IP 形象独立子项目产出并放 `loom/webui/agents/navigator.jpg`;本任务只做**接位**——图没到位时 `agentAvatar` 的 onerror 自动退化为「领」首字徽标,不阻塞。

- [ ] **Step 1: AGENTS_META 加领航员 slug(app.js:864-870)**

```js
  领航员: { slug: "navigator", tag: "伙伴 · 起书" },
```

- [ ] **Step 2: 伙伴面板 head 挂头像(paintJourney 的 jc-head 构造处,731 附近)**

在 `head`(jc-head)左侧插头像:

```js
  head.prepend(agentAvatar("领航员", "jc-ava", "jc-fallback"));
```

- [ ] **Step 3: CSS(style.css,journey-card 区)**

```css
.jc-head { display: flex; align-items: center; gap: 8px; }
.jc-ava, .jc-fallback {
  width: 24px; height: 24px; border-radius: 50%; flex: none;
  object-fit: cover; display: inline-flex; align-items: center; justify-content: center;
  background: rgba(127,127,127,0.15); font-size: 13px;
}
```

- [ ] **Step 4: 语法校验 + 手动验证(fallback 生效)**

```bash
node --check loom/webui/app.js
```
preview 里伙伴面板头部出现圆形头像位——navigator.jpg 未放时显示「领」字徽标(onerror 兜底),不报错、不裂图。截图留证。

- [ ] **Step 5: 提交**

```bash
git add loom/webui/app.js loom/webui/style.css
git commit -m "feat(webui): 伙伴面板挂领航员头像位(navigator.jpg,IP 形象接位,缺图 graceful 退化首字徽标)"
```

---

## 计划自审记录

- **Spec 覆盖(§一期清单)**:writing_unlocked 谓词(T1)✓;write_precheck 接线 force 前 + 无Loom织章作用域(T2)✓;错误契约 code/missing/stage(T2)+ 前端 code 分支(T4)✓;前端引导卡收编 brain_ready(T3 后端暴露 + T4 前端)✓;skip 修正(T5)✓;scaffold 题材代落 + 样例补卡(T6)✓;文案六处 + ADR 0014(T7)✓;领航员头像(T8)✓。二期(导入诊断)/IP 形象设计明确另拆,不在本计划。
- **占位符扫描**:无 TBD/TODO;每个代码步给完整代码或确切改法。教程逐行文案改动给了口径与限定(T7 需读现文照改,已注明"逐行读现文照改")。
- **类型一致性**:`writing_unlocked(root) -> (bool, list[str])` 在 T1 定义,T2/T3 消费签名一致;`code="brain_incomplete"`+`missing`+`stage` 在 T2 产出、T4 前端消费一致;`_GATE_STAGES` T1 定义、T5 复用;`agentAvatar(name,imgCls,fbCls)` 与既有签名一致。
- **门禁不下沉 run_pipeline** 在 Global Constraints 与 T2/ADR 三处重申;golden 零改动在 T2 Step 6 验证。
