# 领航员出题可靠性 + 静默覆盖修复(一期)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让领航员的选项真的出得来(解析容错 + demo 分支 + 降级可查因),并修掉「AI 铺底稿静默覆盖作者已填行」的既有数据丢失 bug。

**Architecture:** 零数据模型改动、零前端改动、零 prompt 模板改动的一期:只动 parse(放宽)/journey(零选项降级+留痕)/draft(谓词统一)/backends(demo 分支)/doctor(报降级率)。二期(槽位层)、三期(定址落盘+红线改写)另立计划,蓝本见 `docs/superpowers/specs/2026-07-15-navigator-two-layer-card-design.md`。

**Tech Stack:** Python 3.11 + pytest(现 431 绿)。无新依赖。

## 背景(执行者需要知道的三件事)

1. **降级卡的三个来源**:后端异常(`LoomBackendError`)、解析失败(`parse_journey_card` 返 `None`)、模型误报无题。今天三者糊成一个 `degraded: true`,原始回复不落盘,**查不出原因**——本计划给每次降级记 `why` + 留痕文件。
2. **解析器过严是降级第一大来源**:[parse.py:203](../../loom/parse.py) 的 `_CARD_Q_RE` 要求行首就是 `问`,模型输出 `**问**:`/`问题:`/`Q:`/`1. 问:` 全部降级;`【无题】` 是整段裸子串匹配且先于 `问:` 检查,模型只要复述格式规则就自我降级。
3. **静默覆盖 bug(已实测复现)**:[draft.py:86](../../loom/draft.py) `_is_blank_or_template` 对整个文件做裸子串匹配 `PLACEHOLDER_MARKS`,而 [卡章纲.md:7](../../loom/templates/外置大脑/卡章纲.md) 的引导行自带「占位示例」四字且作者不会删——作者填了第1/2章章纲后点「AI 铺设定底稿」,**两行被 AI 初稿静默覆盖,skipped 为空**。同一谓词还被 [importer.py:75](../../loom/importer.py) 消费:导入时会误删「含占位字样但已填真内容」的文件。

## Global Constraints

- **本期一个字都不动**:`loom/webui/**`(app.js/style.css)、`loom/templates/agents/领航员.md`、`loom/templates/外置大脑/**`、`loom/server.py`、`loom/usecases.py`、`journey.py` 的 `STAGES`/`StageSpec`/`_CARD_FIELDS`/`_STAGE_HINT`。
- **钉死测试红了 = 实现错了,回滚实现,禁改测试**:`tests/test_journey.py` 全部既有断言(尤其落盘 12 条 :171-283、`test_garbage_degrades_without_burning_budget` 的 `options == []` 与 `asked == 0`、`test_exhausted_without_done_degrades_instead_of_skip`、sig 缓存两条)、`tests/test_parse_journey.py` 既有 7 条、`tests/test_placeholder.py`、`tests/test_journey_usecases.py` 全 5 条。
- 其余既有测试(如 `test_draft_seed.py`/`test_brain_dirs.py`/`test_importer.py`)若意外变红:**停下来向用户报告**,不得静默改断言。
- 新增测试**零真实模型调用**(用 conftest 的 `FakeBackend`/`const`、本计划的 `BoomBackend`、`DemoBackend`)。
- 每个 Task 独立提交;提交信息用仓库惯例 `type(scope): 中文摘要`,末尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- UI 冒烟(Task 7)前**必须先钉 `loom_root` 到 scratchpad 测试书**——preview 与桌面端共享 localStorage,曾误写真书(docs/调试.md §4)。

---

### Task 1: 修静默覆盖——`_is_blank_or_template` 统一到 `is_substantive`

**Files:**
- Modify: `loom/draft.py:20`(import 行)、`loom/draft.py:79-86`(谓词)
- Test: `tests/test_draft_seed.py`(追加 2 个测试)

**Interfaces:**
- Consumes: `loom.parse.is_substantive(text: str) -> bool`(已存在,parse.py:184)
- Produces: `_is_blank_or_template(path: Path) -> bool` 语义变为「缺失/空/无实质内容」;`draft.py:121`(整文件防覆盖)、`draft.py:146,152`(目录节防覆盖/清占位)、`importer.py:75`(导入清占位)三处消费者自动获得新语义

**行为变化(写进提交信息,让用户可查):**
- 修复:含占位字样但已填真内容的文件,不再被 `draft_brain` 覆盖、不再被 `importer._clear_placeholders` 误删。
- 收紧:无任何实质内容的文件(只有标题/引用行)即使不含占位字样,现在也算「可覆盖的模板」——这本就是该函数 docstring 声明的意图。

- [ ] **Step 1: 写两个失败测试**

在 `tests/test_draft_seed.py` 末尾追加(文件已 import `draft_brain`、`FakeBackend`、`const`;需补 `from loom.draft import _is_blank_or_template` 与 `from loom.paths import CARD_REL`):

```python
def test_blank_or_template_respects_filled_rows(tmp_path):
    # 引导行自带「占位示例」但作者已填真内容 → 不可覆盖;纯骨架 → 可覆盖
    p = tmp_path / "卡章纲.md"
    p.write_text("> (占位示例,换成你自己的。)\n\n- 第1章:主角雪夜被逐出宗门\n- 第2章:\n", encoding="utf-8")
    assert _is_blank_or_template(p) is False
    p.write_text("> (占位示例,换成你自己的。)\n\n- 第1章:\n- 第2章:\n", encoding="utf-8")
    assert _is_blank_or_template(p) is True


def test_filled_rows_survive_draft_brain(project):
    # 复现静默覆盖:作者答题填了章行 → 点「AI 铺设定底稿」→ 拍板的行必须还在,整段必须 skipped
    card = project / CARD_REL
    card.write_text(card.read_text(encoding="utf-8").replace(
        "- 第1章:", "- 第1章:主角雪夜被逐出宗门,捡到会说话的鼎"), encoding="utf-8")
    out = draft_brain(project, "一句话设定", FakeBackend(const(_OK)))
    text = card.read_text(encoding="utf-8")
    assert "主角雪夜被逐出宗门" in text
    assert "卡章纲" in out["skipped"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_draft_seed.py -v -k "blank_or_template or survive"`
Expected: 两条 FAIL——第一条 `_is_blank_or_template(p) is False` 断言失败(旧谓词见「占位示例」即 True);第二条 `"主角雪夜被逐出宗门" in text` 断言失败(被覆盖)。

- [ ] **Step 3: 最小实现**

`loom/draft.py:20` 的 import 行改为(`PLACEHOLDER_MARKS` 在 draft.py 内不再有消费者,换成 `is_substantive`):

```python
from .parse import is_substantive, split_brain_draft as _split  # 读侧解析共置 parse.py(S7),薄别名保引用面
```

`loom/draft.py:79-86` 整个函数替换为:

```python
def _is_blank_or_template(path: Path) -> bool:
    """文件缺失 / 空 / 剥掉占位提示后没有实质内容 → 可安全覆盖;否则保留作者内容。

    与 parse.is_substantive 共用同一判定(占位判定单一真相),两侧永不漂移——
    旧版裸子串匹配 PLACEHOLDER_MARKS 会把「引导行含标记 + 作者已填真内容」误判为可覆盖(静默数据丢失)。"""
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    return not text.strip() or not is_substantive(text)
```

- [ ] **Step 4: 跑测试确认通过 + 波及面回归**

Run: `.venv/bin/python -m pytest tests/test_draft_seed.py tests/test_brain_dirs.py tests/test_importer.py tests/test_placeholder.py -q`
Expected: 全绿。若 `test_brain_dirs.py` 或 `test_importer.py` 红:停,报告用户(见 Global Constraints)。

- [ ] **Step 5: Commit**

```bash
git add loom/draft.py tests/test_draft_seed.py
git commit -m "$(cat <<'EOF'
fix(draft): 占位判定统一到 is_substantive——修「AI铺底稿静默覆盖作者已填行」

_is_blank_or_template 原是整文件裸子串匹配 PLACEHOLDER_MARKS,而卡章纲.md 的
引导行自带「占位示例」且作者不会删:答题填过的章行会被 AI 底稿静默整份覆盖
(skipped 为空,已实测复现)。统一到 is_substantive 后:
- 已填真内容的文件不再被 draft_brain 覆盖、不再被 importer 清占位误删
- 只有标题/引用行的零实质文件照旧算模板(函数本来的意图)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 解析容错——`问:`/选项行放宽,`【无题】` 只认独占一行且无题面

**Files:**
- Modify: `loom/parse.py:197-221`(输出约定注释 + 两个正则 + `parse_journey_card`)
- Test: `tests/test_parse_journey.py`(追加 4 个测试)

**Interfaces:**
- Consumes: 无(纯函数)
- Produces: `parse_journey_card(raw: str) -> dict | None` 签名与返回形状不变(`{"question", "options", "field"?}` / `{"exhausted": True}` / `None`);新增容忍 `**问**:`/`问题:`/`Q:`/`1. 问:` 与 `*`/`•`/`1.` 选项行;`【无题】` 仅当「整行只有它」且「全文无问句」才算

- [ ] **Step 1: 写四个失败测试**

在 `tests/test_parse_journey.py` 末尾追加:

```python
def test_decorated_question_parses():
    # 模型爱加 markdown 装饰,这是今天降级的第一大来源
    card = parse_journey_card("**问**:金手指选哪个?\n- 吞噬胃袋\n- 时间回溯")
    assert card["question"] == "金手指选哪个?"


def test_question_word_and_numbered_bullets_parse():
    card = parse_journey_card("1. 问题:开局钩子走哪种?\n* 威胁逼近\n• 身世反转")
    assert card["question"] == "开局钩子走哪种?"
    assert card["options"] == ["威胁逼近", "身世反转"]


def test_rule_recitation_does_not_self_degrade():
    # 模型复述格式规则时句中出现「【无题】」——有题面就成卡,不算无题
    raw = "若无题可出,只输出【无题】。\n问:主角的软肋是什么?\n- 亲妹妹在敌方手里\n- 灵根残缺,大道无望"
    card = parse_journey_card(raw)
    assert card["question"] == "主角的软肋是什么?"


def test_bare_sentinel_line_still_exhausted():
    # 独占一行的哨兵(前面可有闲话)仍判无题——老书 prompt 还会这么输出
    assert parse_journey_card("这一段该问的都定好了。\n【无题】") == {"exhausted": True}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_parse_journey.py -v`
Expected: 新增 4 条中前 3 条 FAIL(`**问**:` 不匹配返 None;`1. 问题:` 不匹配返 None;复述句触发裸子串 → 返 `{"exhausted": True}` 而非卡);第 4 条 PASS(现行为凑巧一致)。既有 7 条全 PASS。

- [ ] **Step 3: 实现**

`loom/parse.py:197-205` 的共置注释与两个正则替换为:

```python
# ── 领航员问题卡(journey.next_card 消费;输出约定住 templates/agents/领航员.md) ──
# 输出约定(prompt ↔ 解析器共置面):
#   格:题材            ← 可选,仅立项阶段
#   问:一行问题         ← 容忍 markdown 装饰/编号/「问题」「Q」变体(模型常飘,飘了不该降级)
#   - 选项(2-4 个)      ← 容忍 * / • / 数字编号作弹头
#   无题哨兵:「【无题】」独占一行且全文无问句才算(句中复述格式规则不算,防模型自我降级)。
_CARD_Q_RE = re.compile(r"^\s*(?:\d+[.、]\s*)?[*_#\s]*(?:问题?|[Qq])[*_\s]*[:：]\s*(\S.*?)[*_\s]*$")
_CARD_F_RE = re.compile(r"^格[:：]\s*(\S+)\s*$", re.M)
_CARD_OPT_RE = re.compile(r"^\s*(?:[-*•]|\d+[.、])\s+(\S.*)$")
```

`parse_journey_card` 整个函数替换为:

```python
def parse_journey_card(raw: str) -> dict | None:
    """领航员输出 → 问题卡;无题 {"exhausted": True};不成卡 None(调用方降级为自由输入)。"""
    lines = raw.splitlines()
    q_idx = next((i for i, l in enumerate(lines) if _CARD_Q_RE.match(l.strip())), None)
    if q_idx is None:
        if any(l.strip() == "【无题】" for l in lines):   # 独占一行才算哨兵;有题面时题面赢
            return {"exhausted": True}
        return None
    question = _CARD_Q_RE.match(lines[q_idx].strip()).group(1).strip()
    options = [m.group(1).strip() for l in lines[q_idx + 1:] if (m := _CARD_OPT_RE.match(l))]
    card: dict = {"question": question, "options": [o for o in options if o][:4]}
    f = _CARD_F_RE.search(raw)
    if f:
        card["field"] = f.group(1).strip()
    return card
```

注意:`[:4]` 上限一字不动(`test_options_capped_at_four` 钉死,它是防模型话痨的信任边界)。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_parse_journey.py tests/test_journey.py tests/test_journey_usecases.py -q`
Expected: 全绿(11 条 parse + journey 全部既有)。

- [ ] **Step 5: Commit**

```bash
git add loom/parse.py tests/test_parse_journey.py
git commit -m "$(cat <<'EOF'
fix(parse): 领航员卡解析容错——问:装饰/编号/问题/Q变体、*•数字弹头,【无题】只认独行

**问**:/问题:/Q:/1. 问: 今天全部解析失败→降级,是降级率第一大来源;
【无题】原是整段裸子串且先于问句检查,模型复述一句格式规则就自我降级。
改为:问句放宽匹配;哨兵独占一行且全文无问句才算(有题面时题面赢)。
[:4] 选项上限不动(防话痨的信任边界)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 零/独苗选项 → 降级,降级卡带 `why`

**Files:**
- Modify: `loom/journey.py:270-296`(`next_card` 的解析后半段)
- Test: `tests/test_journey.py`(追加 1 个测试)

**Interfaces:**
- Consumes: Task 2 的 `parse_journey_card`
- Produces: 降级卡 JSON 多一个 `"why"` 字段,取值 `backend_error | unparsed | few_options | false_exhausted`(前端不消费它也不受影响;Task 4 的留痕消费它);`len(options) < 2` 的模型回复不再成卡——不烧预算、不进缓存、前端「重试出题」按钮(只认 `degraded`)自动出现

**背景(为什么这是三重 bug 一刀修):** 今天模型给了 `问:` 但没给弹头行 → 成「正常卡」→ 烧预算(`asked+=1`)、进 sig 缓存(文件不变就永久钉死这张烂卡)、且无重试按钮(app.js:896 只认 `degraded`)。判成降级后三者同时归位:`journey.py:292` 只有成卡才烧预算、`:262` 降级不进缓存、前端自动给重试钮。

- [ ] **Step 1: 写失败测试**

在 `tests/test_journey.py` 的「---- 出题(Task 4) ----」区末尾追加:

```python
def test_single_option_degrades_without_burning_budget(project):
    # 契约是 2-4 个候选:独苗/零候选不成卡——不烧预算、不进缓存、带 why 供查因
    fake = FakeBackend(const("问:只有一个选项?\n- 独苗"))
    out = journey.next_card(project, fake)
    assert out["card"]["degraded"] is True
    assert out["card"]["why"] == "few_options"
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "立项")["asked"] == 0
    journey.next_card(project, fake)          # 降级不吃缓存 → 真重试
    assert len(fake.calls) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_journey.py::test_single_option_degrades_without_burning_budget -v`
Expected: FAIL——`out["card"]["degraded"]` KeyError 或非 True(今天独苗照样成卡)。

- [ ] **Step 3: 实现**

`loom/journey.py` `next_card` 内,从 `parsed = None`(:270)到降级卡构造(:295)整段替换为:

```python
    parsed = None
    raw = ""
    why = ""       # 降级原因:backend_error|unparsed|few_options|false_exhausted(留痕+查因;成卡时为空)
    err_code = ""
    try:
        raw = backend.complete(_navigator_system(root), user, max_chars=_NAV_MAX_CHARS)
        parsed = parse_journey_card(raw)
        if parsed is None:
            why = "unparsed"
    except LoomBackendError as e:
        why, err_code = "backend_error", (e.code or "")   # 断网/超时 → 降级卡,旅程不卡死

    if parsed and parsed.get("exhausted"):
        if stage_done(root, spec):
            j["skips"][cur] = True   # 真做完了才跳;游标可丢,丢了最多重问一次
            j["card"] = None
            st["journey"] = j
            save_state(root, st)
            return next_card(root, backend) if journey_state(root)["current"] else \
                {"card": None, "state": journey_state(root)}
        parsed, why = None, "false_exhausted"   # 没做完却报无题 → 模型误判,降级兜底,别死锁

    if parsed and len(parsed["options"]) < 2:
        parsed, why = None, "few_options"   # 契约 2-4 个候选:独苗不成卡(否则烧预算+缓存钉死+无重试钮)

    if parsed:
        card = {"stage": cur, "sig": sig, "question": parsed["question"],
                "options": parsed["options"]}
        if "field" in parsed:
            card["field"] = parsed["field"]
        j["asked"][cur] = int(j["asked"].get(cur, 0)) + 1   # 只有成卡才烧预算
    else:
        card = {"stage": cur, "sig": sig, "options": [], "degraded": True, "why": why,
                "question": f"「{spec.key}」要定:{_STAGE_HINT.get(cur, spec.key)}。领航员这次没出上题,直接写你想定的。"}
```

(`err_code` 本 Task 尚无消费者,Task 4 的留痕用它;降级卡题面文案本期不动,二期换成槽位现拼。)

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_journey.py tests/test_journey_usecases.py -q`
Expected: 全绿。重点看住 `test_garbage_degrades_without_burning_budget`(`options == []`/`asked == 0`)、`test_exhausted_without_done_degrades_instead_of_skip`、`test_exhausted_on_done_stage_skips_and_advances`、sig 缓存两条——一条红都不许。

- [ ] **Step 5: Commit**

```bash
git add loom/journey.py tests/test_journey.py
git commit -m "$(cat <<'EOF'
fix(journey): 零/独苗选项不成卡+降级卡带why——一刀修「烂卡烧预算/进缓存钉死/无重试钮」三重

模型给了问:却没给≥2个候选 → 今天照样成卡:烧掉一格预算、进sig缓存(文件不变
永久钉死)、且前端重试钮只认degraded不出现。改判降级后三者同时归位。
降级卡新增 why 字段(backend_error|unparsed|few_options|false_exhausted),
是「降级了查不出原因」的第一块补丁,留痕(下个提交)消费它。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 降级留痕 `.审稿留痕/领航员留痕.md` + `paths.NAV_TRACE_REL`

**Files:**
- Modify: `loom/paths.py:21` 附近(加常量)、`loom/journey.py`(加 `_nav_trace` + 降级分支调用)
- Test: `tests/test_journey.py`(追加 3 个测试 + 1 个 BoomBackend 假后端)

**Interfaces:**
- Consumes: Task 3 的 `why`/`err_code`/`raw`;`paths.REVIEW_DIR`(已存在,:21);`fsutil.atomic_write_text`(自建父目录,fsutil.py:35)
- Produces: `paths.NAV_TRACE_REL: str`(值 `".审稿留痕/领航员留痕.md"`);`journey._nav_trace(root, *, stage, sig, why, backend, raw, code="") -> None`(Task 6 的 doctor 读这个文件)

**三条硬边界(写进 docstring,违反即返工):** 绝不进 `.loom_state.json`(游标必须薄且可丢弃,ADR 0013);绝不进外置大脑(会被 agent 读到污染设定);绝不被读回来派生任何状态(题从文件现状推导,不从问答历史推导)。

- [ ] **Step 1: 写三个失败测试**

`tests/test_journey.py` 顶部 import 区补 `from loom.backends import LoomBackendError` 与 `from loom.paths import NAV_TRACE_REL`(现有 import 保持不动),测试区追加:

```python
class BoomBackend:
    """一调用就炸的假后端:模拟断网/没key。"""
    def complete(self, system, user, *, max_chars=None, on_chunk=None):
        raise LoomBackendError("联不上", code="deepseek_call_failed")


def test_trace_written_on_backend_error(project):
    out = journey.next_card(project, BoomBackend())
    assert out["card"]["why"] == "backend_error"
    text = (project / NAV_TRACE_REL).read_text(encoding="utf-8")
    assert "backend_error" in text and "deepseek_call_failed" in text


def test_no_trace_on_success(project):
    journey.next_card(project, FakeBackend(const(_CARD_RAW)))
    assert not (project / NAV_TRACE_REL).exists()   # 成功不打点(体积+隐私:raw含书的设定)


def test_trace_keeps_last_20(project):
    import re as _re
    for _ in range(23):
        journey.next_card(project, BoomBackend())
    text = (project / NAV_TRACE_REL).read_text(encoding="utf-8")
    assert len(_re.findall(r"^## ", text, _re.M)) == 20
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_journey.py -v -k "trace"`
Expected: 3 条 FAIL——`NAV_TRACE_REL` ImportError(常量还不存在)。

- [ ] **Step 3: 实现**

`loom/paths.py` 在 `REVIEW_DIR = ".审稿留痕"`(:21)行后加:

```python
NAV_TRACE_REL = f"{REVIEW_DIR}/领航员留痕.md"   # 领航员出题失败的现场记录(人可读可删,不派生状态)
```

(`CHAPTER_ARTIFACTS`(:128)是**按章**产物清单,留痕是全书一份,不加行。)

`loom/journey.py` 在 `next_card` 之前加:

```python
def _nav_trace(root: Path, *, stage: str, sig: str, why: str, backend, raw: str, code: str = "") -> None:
    """出题降级才留痕(.审稿留痕/领航员留痕.md):现场证据,新条目在前,保最近 20 条。

    三条硬边界:绝不进 .loom_state.json(游标要薄且可丢弃,ADR 0013);绝不进外置大脑
    (会被 agent 读到污染设定);绝不被读回来派生状态(题从文件现状推导,不从问答历史推导)。
    留痕失败绝不影响出题(fire-and-forget,同 events 纪律)。"""
    from datetime import datetime
    try:
        p = root / paths.NAV_TRACE_REL
        old = p.read_text(encoding="utf-8") if p.is_file() else ""
        entries = [b for b in re.split(r"(?=^## )", old, flags=re.M) if b.startswith("## ")][:19]
        quoted = "\n".join("  > " + l for l in (raw.strip() or "(无原始回复)")[:500].splitlines())
        entry = (f"## {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · {stage}\n"
                 f"- sig: {sig}\n- 结果: {why}\n- 后端: {type(backend).__name__}\n"
                 + (f"- code: {code}\n" if code else "")
                 + f"- 原始回复(截断 500 字):\n{quoted}\n\n")
        head = "# 领航员留痕\n\n> 出题失败的现场记录:查「为什么降级」用。loom 只追加、不读回;整个文件可删。\n\n"
        atomic_write_text(p, head + entry + "".join(entries))
    except Exception:
        pass
```

`next_card` 降级卡构造(Task 3 的 `else:` 分支)末尾、`j["card"] = card` 之前加一行:

```python
        _nav_trace(root, stage=cur, sig=sig, why=why, backend=backend, raw=raw, code=err_code)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_journey.py -q`
Expected: 全绿(含 3 条新 trace 测试;`test_no_trace_on_success` 钉住「成功不打点」)。

- [ ] **Step 5: Commit**

```bash
git add loom/paths.py loom/journey.py tests/test_journey.py
git commit -m "$(cat <<'EOF'
feat(journey): 降级留痕 .审稿留痕/领航员留痕.md——降级卡从「查不出原因」变成有现场

只在降级时追加(why/后端/code/原始回复截断500字),新条目在前保最近20条;
成功不打点(体积+隐私)。三条硬边界:不进游标(ADR 0013)、不进外置大脑、
绝不读回派生状态。留痕失败不影响出题(fire-and-forget)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: DemoBackend 领航员分支——demo 模式起书访谈端到端可点

**Files:**
- Modify: `loom/backends.py`(`DemoBackend._pick` 加一分支 + `_DEMO` 加一键)
- Test: `tests/test_journey.py`(追加 1 个测试)

**Interfaces:**
- Consumes: `journey._navigator_system` 返回的 body 含「领航员」三字(模板首句「你是「领航员」……」;全 agents 模板中唯一,已核实)
- Produces: `LOOM_DEMO=1` 下 `next_card` 出正常卡(3 个候选),不再必然降级

**背景:** 今天 demo 模式下领航员 system 落到 `_pick` 的兜底 `"（demo 占位）"` → 无 `问:` 行 → 必降级。这正是本次改造的起点(用户第一眼看到的就是那张降级卡)。

- [ ] **Step 1: 写失败测试**

`tests/test_journey.py` 追加(import 区补 `from loom.backends import DemoBackend` 与 `from loom.config import load_config`;`LoomBackendError` Task 4 已加):

```python
def test_demo_navigator_end_to_end_card(project):
    # LOOM_DEMO 下起书访谈必须端到端可点:出正常卡带 2-4 个候选,不降级
    out = journey.next_card(project, DemoBackend(load_config(project)))
    assert "degraded" not in out["card"]
    assert 2 <= len(out["card"]["options"]) <= 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_journey.py::test_demo_navigator_end_to_end_card -v`
Expected: FAIL——`"degraded" not in out["card"]` 断言失败(兜底占位不成卡)。

- [ ] **Step 3: 实现**

`loom/backends.py` `DemoBackend._pick` 内,在「起一个/章节标题」分支之后、五角色 for 循环之前插入:

```python
        if "领航员" in system:   # 访谈出题:格式必须合规能解析成卡(问: + 2-4 个候选)
            return _DEMO["nav"]
```

`_DEMO` 字典加一键(放 `"learn"` 之后):

```python
    "nav": (
        "问:(demo)这本书的核心冲突先走哪一路?\n"
        "- (demo 候选)旧秩序崩塌,主角靠金手指逆流翻盘\n"
        "- (demo 候选)双雄相争,主角在夹缝里闷声发育\n"
        "- (demo 候选)悬案倒查,每章揭开一层旧真相\n"
    ),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_journey.py tests/test_model_split.py -q`
Expected: 全绿(注意 DemoBackend.complete 无 on_chunk 时 sleep 0.7s,单条测试慢一点是正常的)。

- [ ] **Step 5: Commit**

```bash
git add loom/backends.py tests/test_journey.py
git commit -m "$(cat <<'EOF'
feat(backends): DemoBackend 补领航员分支——LOOM_DEMO 起书访谈端到端可点,不再必降级

demo 下领航员原落到「(demo 占位)」兜底,无问:行必降级——用户免key试玩
第一眼就是降级卡。补一条合规输出(问:+3个候选),五道工序之外第六个角色点亮。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: doctor 报「领航员近况」 + 调试文档一行

**Files:**
- Modify: `loom/doctor.py`(尾部加一个 Check)、`docs/调试.md`(§6 排查加一行)
- Test: Create `tests/test_doctor_nav.py`

**Interfaces:**
- Consumes: Task 4 的留痕文件格式(`^## ` 每条一个标题)、`paths.NAV_TRACE_REL`
- Produces: `run_checks` 结果里条件性多一条 `Check(name="领航员出题", ...)`;无留痕文件时不出这条(健康书零噪音)

- [ ] **Step 1: 写失败测试**

Create `tests/test_doctor_nav.py`:

```python
"""doctor 的领航员近况检查:读留痕报降级次数;没有留痕(没降级过)不出这条,零噪音。"""
from loom.doctor import run_checks
from loom.paths import NAV_TRACE_REL


def test_no_trace_no_nav_check(project):
    assert all(c.name != "领航员出题" for c in run_checks(project))


def test_trace_entries_surface_in_doctor(project):
    p = project / NAV_TRACE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 领航员留痕\n\n## 2026-07-15 12:00:00 · 立项\n- 结果: unparsed\n"
                 "\n## 2026-07-15 12:01:00 · 立项\n- 结果: backend_error\n", encoding="utf-8")
    c = next(c for c in run_checks(project) if c.name == "领航员出题")
    assert c.ok is False
    assert "2 次" in c.missing
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_doctor_nav.py -v`
Expected: 第一条 PASS(check 还不存在,自然全都不叫这名),第二条 FAIL(StopIteration——找不到该 check)。

- [ ] **Step 3: 实现**

`loom/doctor.py` import 区补 `import re` 与 `from .paths import NAV_TRACE_REL`(挂进现有 `from .paths import brain_rel` 行)。`run_checks` 里可选大脑件循环之后、`return checks` 之前加:

```python
    # e. 领航员近况(读留痕,纯只读;没有留痕文件 = 没降级过,不出这条,零噪音)
    trace = root / NAV_TRACE_REL
    if trace.is_file():
        n = len(re.findall(r"^## ", trace.read_text(encoding="utf-8"), re.M))
        checks.append(_c("领航员出题", n == 0,
                         f"最近留痕里有 {n} 次降级(只保最近20条)",
                         f"看 {NAV_TRACE_REL} 的「结果」列:backend_error→查key/网络;unparsed/few_options→升级loom或换模型"))
    return checks
```

(原 `return checks` 行被上面这段吸收,别留两个 return。)

`docs/调试.md` 的排查段(「看服务端日志」附近)加一行:

```markdown
- **降级卡查因**:看这本书的 `.审稿留痕/领航员留痕.md`(每次降级记 why/后端/原始回复截断);`loom doctor` 也会报最近降级次数。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_doctor_nav.py -q`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add loom/doctor.py tests/test_doctor_nav.py docs/调试.md
git commit -m "$(cat <<'EOF'
feat(doctor): 报「领航员出题」近况——读留痕数降级次数,健康书零噪音

有留痕文件才出这条(ok=近20条零降级),missing 带次数、fix 按 why 给处方。
纯只读,守 doctor 的二态纪律。调试.md 补查因入口。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 全量回归 + demo 冒烟(验证一期的用户可见效果)

**Files:** 无代码改动;只验证。

- [ ] **Step 1: 全量测试 + 离线 eval 门禁**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m evals.run_eval --gate`
Expected: 全绿。基线 431 + 本计划新增 13 条(Task1×2 + Task2×4 + Task3×1 + Task4×3 + Task5×1 + Task6×2)= 444 passed;eval 门禁 PASS。

- [ ] **Step 2: demo 服务冒烟(loom-dev 8792 已带 --reload,存盘即生效)**

浏览器(preview 面板)操作,**先钉 loom_root**(没有测试书就先在 scratchpad 目录 `loom init 测试书` 造一本;绝不用真书):

```js
// preview console 先执行(数据安全纪律,docs/调试.md §4);路径填上一步造的测试书绝对路径:
localStorage.setItem('loom_root', '/…/scratchpad/测试书'); location.reload();
```

然后点降级卡上的「重试出题」(或首次进入等自动出题)。
Expected: 居中大卡出现 **3 个「(demo 候选)」开头的可点选项按钮**,textarea placeholder 变成「或者自己写……」,无「领航员这次没出上题」文案。点任一候选 → 答案落入 `外置大脑/立项卡.md`(demo 卡无 `格:` 行 → 按现行 `_land_field` 兜底落「题材」格,这是既有行为,二期才改)。

- [ ] **Step 3: 故障注入验证留痕(可选但建议)**

临时断网或在测试书 `loom.toml` 配一个坏 provider 起真后端出题一次 → 打开测试书 `.审稿留痕/领航员留痕.md`,确认有 `结果: backend_error` 条目;`loom doctor` 输出含「领航员出题」一条。验完恢复配置。

- [ ] **Step 4: 汇报**

向用户展示:测试计数、demo 卡截图、留痕文件样例。不合并不发版——等用户验收。

---

## 二三期路线(本计划不含,各自另立计划)

| 期 | 内容 | 前置 |
|---|---|---|
| 二期 | 槽位层(只读):`slots.py` 扫描骨架行、卡带 `slots` 字段、降级卡换槽位 chip、`/card {slot}`、前端 chip+托盘 | 一期发布 + 收一轮真机降级率 |
| 三期 | 定址落盘 `_land_slot`(line/h2/row/filename/file)+ 红线改写(删「绝不发明设定」)+ 删 `格:`/`【无题】` + ADR 0015 + CONTEXT 对账 | 二期 + 盲评实验(带/不带槽位锚定各 20 题) |

设计蓝本(含每个岔路的裁决与退路):`docs/superpowers/specs/2026-07-15-navigator-two-layer-card-design.md`
