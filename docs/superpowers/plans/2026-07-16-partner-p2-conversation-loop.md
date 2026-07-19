# 书房伙伴 P2:对话循环(loop + 工具协议 + 存储 + 上下文)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。步骤用 checkbox 跟踪。

**Goal:** 建成离线可测(ScriptedBackend,零真实模型)的对话循环:`partner.py` 每轮 `assemble(对话尾部, 书文件) → complete() → 解析说话段+工具块 → 执行工具 → 回喂 → 再 complete`,配三个工具(读文件/看地基/提设定)、`.伙伴对话/` jsonl 存储、文本工具协议解析(含流式行缓冲纪律)。P2 不碰服务端/前端/迁移(那是 P3)。

**Architecture:** 循环架在五后端共用的单轮 `complete(system, user, max_chars, on_chunk)` 之上,后端协议零改动。每轮重建、两轮之间零挂起(ADR 0013 平移)。上下文分层组装(稳定前缀吃缓存 + 动态后缀现算),看地基/环境快照都调 P1 的 `slots.stage_slots`。对话是可丢弃日志,删 `.伙伴对话/` 书无恙。

**Tech Stack:** Python 3.11 + pytest(现 470 绿)。无新依赖。

**设计权威:**〔[书房伙伴设计](../specs/2026-07-16-navigator-agent-design.md)〕§3(循环)、§4(上下文)、§5(工具)、§6(拍板 proposal)、§7(存储)、§8(降级)。P1(slots.py/`_land_slot`)是地基。

## Global Constraints

- **零服务端/前端/迁移改动**。P2 只新建 `loom/partner.py`、`loom/partner_store.py`(或合并)、改 `loom/parse.py`(加工具协议解析)、`loom/paths.py`(加 `.伙伴对话` 常量)、`tests/conftest.py`(加 ScriptedBackend)、新建 `tests/test_partner_*.py`。**不碰 server.py/usecases.py/webui/journey.py 的出题退役(P3)**。
- **零真实模型调用**:循环测试全走 ScriptedBackend(回复序列 pop)。
- **流式行缓冲纪律是硬要求**(spec §5.2 critical):协议行(`用:`/`键:值`)绝不许以 assistant_text 漏到作者屏幕上;chunk 可在行中截断(`用` 与 `:` 分两 chunk)必须免疫。
- **路径守卫两层**(spec §5.3):`safe_join`(fsutil,锁书根内挡 `../`/绝对路径)+ 通用规则「路径任一段以『.』开头即拒」(涵盖 `.env`/`.loom_state.json`/`.伙伴对话/`/`外置大脑/.拆书/` 等)+ 白名单谓词(外置大脑/skills/正文,只读,前缀从 paths 常量派生)。**不复用 brainedit.check_rel**(那是写白名单)。
- **上下文≠状态**:完成度/门禁永远从文件推导;删 `.伙伴对话/` 书无恙。唯一被程序读回的对话事件是待确认 proposal 行。
- **人可改文件读容错**:jsonl 读回带 `errors="replace"`(GBK 自愈,journey.py:258 先例);坏行 `try/except json 跳过`(ledger「坏就当无」哲学)。
- 提交信息 `type(scope): 中文摘要` + 末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件,绝不 `git add -A`。
- 命名公约:代码/API 层 `partner`;盘上 `.伙伴对话/`;角色人设仍 `领航员.md`(不改名)。

---

### Task 1: `.伙伴对话/` jsonl 存储

**Files:**
- Modify: `loom/paths.py`(加 `PARTNER_DIR`/`PARTNER_CUR_REL` 常量)
- Create: `loom/partner_store.py`
- Test: `tests/test_partner_store.py`

**Interfaces:**
- Produces:
  ```python
  # paths.py
  PARTNER_DIR = ".伙伴对话"
  PARTNER_CUR_REL = f"{PARTNER_DIR}/当前.jsonl"
  # partner_store.py
  def append_event(root: Path, event: dict) -> None       # 单行 append,ts 由调用方给(无 Date.now 依赖)
  def read_events(root: Path, *, tail: int | None = None) -> list[dict]   # 坏行跳过;tail=只取尾部 N 条
  def archive_current(root: Path, stamp: str) -> None      # 当前.jsonl → 归档-<stamp>.jsonl(整文件原子重写场景)
  def find_proposal(root: Path, pid: str) -> dict | None   # 全文件找 proposal 事件(不受 tail 限)
  ```

**背景(scout 核实):**
- 追加写现网先例:`path.open("a", encoding="utf-8").write(...)`(agents.py:106),不走 atomic_write_text。jsonl 单行 append 照此。
- 逐行读坏行跳过:仓库无现成函数,借 ledger「坏就当无」哲学,per-line `try: json.loads except: continue`。
- `paths.py` 顶注红线:纯 stdlib,不 import 任何 loom 模块。加常量 OK,别引依赖。
- 事件 `t` 枚举(spec §7):`user|assistant|tool|result|proposal|confirm|meta|summary`。

- [ ] **Step 1: 写失败测试**

`tests/test_partner_store.py`:
```python
"""伙伴对话存储:jsonl 单行 append + 坏行跳过 + proposal 查找。上下文不是状态。"""
from loom import partner_store as ps
from loom.paths import PARTNER_CUR_REL


def test_append_and_read_roundtrip(project):
    ps.append_event(project, {"t": "user", "ts": "2026-07-16T00:00:00", "text": "你好"})
    ps.append_event(project, {"t": "assistant", "ts": "2026-07-16T00:00:01", "text": "我在"})
    evs = ps.read_events(project)
    assert [e["t"] for e in evs] == ["user", "assistant"]
    assert evs[0]["text"] == "你好"


def test_bad_line_skipped(project):
    ps.append_event(project, {"t": "user", "ts": "x", "text": "ok"})
    p = project / PARTNER_CUR_REL
    p.write_text(p.read_text(encoding="utf-8") + "{坏行不是json\n", encoding="utf-8")
    ps.append_event(project, {"t": "assistant", "ts": "y", "text": "still ok"})
    evs = ps.read_events(project)
    assert [e["t"] for e in evs] == ["user", "assistant"]   # 坏行跳过,前后都在


def test_tail_limits(project):
    for i in range(5):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"m{i}"})
    assert [e["text"] for e in ps.read_events(project, tail=2)] == ["m3", "m4"]


def test_find_proposal_scans_full_file(project):
    for i in range(20):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"m{i}"})
    ps.append_event(project, {"t": "proposal", "ts": "p", "id": "p1", "slot": "外置大脑/立项卡.md#题材", "content": "重生流"})
    for i in range(20):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"n{i}"})
    found = ps.find_proposal(project, "p1")
    assert found and found["content"] == "重生流"     # 全文件找,不受 tail 影响


def test_delete_dir_is_safe(project):
    # 删 .伙伴对话/ 只是失忆,read_events 返空不炸
    ps.append_event(project, {"t": "user", "ts": "x", "text": "ok"})
    import shutil
    shutil.rmtree(project / ".伙伴对话")
    assert ps.read_events(project) == []
```

- [ ] **Step 2-4: 跑红 → 实现 → 跑绿**

实现 `loom/partner_store.py`:
```python
"""伙伴对话存储:一条对话一个 当前.jsonl,单行 append、坏行跳过。

上下文不是状态:删整个 .伙伴对话/ 目录,书完好无损(门禁/完成度从书文件推导)。
读回带 errors="replace" 兜 GBK(人可改文件);坏行 try/except 跳过(同 ledger「坏就当无」)。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths


def _cur(root: Path) -> Path:
    return root / paths.PARTNER_CUR_REL


def append_event(root: Path, event: dict) -> None:
    p = _cur(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(root: Path, *, tail: int | None = None) -> list[dict]:
    p = _cur(root)
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue   # 坏行跳过,坏就当无
        if isinstance(ev, dict):
            out.append(ev)
    return out[-tail:] if tail else out


def find_proposal(root: Path, pid: str) -> dict | None:
    for ev in reversed(read_events(root)):   # 从近到远找
        if ev.get("t") == "proposal" and ev.get("id") == pid:
            return ev
    return None


def archive_current(root: Path, stamp: str) -> None:
    p = _cur(root)
    if p.is_file():
        p.rename(p.with_name(f"归档-{stamp}.jsonl"))
```
`paths.py` 加(在 `REVIEW_DIR` 附近):
```python
PARTNER_DIR = ".伙伴对话"                    # 伙伴对话日志(整书一条;人可读可删,删=失忆书无恙)
PARTNER_CUR_REL = f"{PARTNER_DIR}/当前.jsonl"
```

Run: `.venv/bin/python -m pytest tests/test_partner_store.py -q`

- [ ] **Step 5: Commit** `feat(partner): .伙伴对话/ jsonl 存储——单行append/坏行跳过/proposal全文件查找`

---

### Task 2: 文本工具协议解析(`用:`/`键:值`)

**Files:**
- Modify: `loom/parse.py`(加 `parse_tool_block`)
- Test: `tests/test_partner_protocol.py`

**Interfaces:**
- Produces:
  ```python
  def parse_tool_block(text: str) -> tuple[str, dict | None]:
      """(说话段, 工具调用 | None)。工具调用 = {"name": str, "params": {键:值}}。
      只认第一个「用:」块;之后的尾巴文字丢弃。协议行不进说话段。"""
  ```

**背景:** 复用一期放宽后的手艺(全/半角冒号、装饰剥离)。`用:<工具名>` 起,后续 `键:值` 行到空行/文末止。

- [ ] **Step 1: 失败测试**
```python
from loom.parse import parse_tool_block


def test_speech_only():
    say, tool = parse_tool_block("我觉得这本书的金手指可以走系统流。")
    assert say == "我觉得这本书的金手指可以走系统流。"
    assert tool is None


def test_tool_block():
    say, tool = parse_tool_block("我看看金手指定得怎么样。\n\n用:读文件\n路径:外置大脑/世界观/金手指.md")
    assert say == "我看看金手指定得怎么样。"
    assert tool == {"name": "读文件", "params": {"路径": "外置大脑/世界观/金手指.md"}}


def test_only_first_block_tail_dropped():
    say, tool = parse_tool_block("话\n\n用:看地基\n\n用:读文件\n路径:x")
    assert tool["name"] == "看地基"     # 第一个块
    assert "用:读文件" not in say        # 尾巴不进说话段


def test_decorated_tool_line_tolerated():
    _, tool = parse_tool_block("**用**:读文件\n**路径**:外置大脑/立项卡.md")
    assert tool == {"name": "读文件", "params": {"路径": "外置大脑/立项卡.md"}}


def test_fullwidth_colon():
    _, tool = parse_tool_block("用：看地基")
    assert tool == {"name": "看地基", "params": {}}
```

- [ ] **Step 2-4: 实现**(parse.py 加,与领航员卡解析共置):
```python
_TOOL_USE_RE = re.compile(r"^\s*[*_#\s]*用[*_\s]*[:：]\s*(\S.*?)[*_\s]*$")
_TOOL_KV_RE = re.compile(r"^\s*[*_#\s]*([^:：*_]+?)[*_\s]*[:：]\s*(.*?)\s*$")


def parse_tool_block(text: str) -> tuple[str, dict | None]:
    lines = text.splitlines()
    ui = next((i for i, l in enumerate(lines) if _TOOL_USE_RE.match(l)), None)
    if ui is None:
        return text.strip(), None
    name = _TOOL_USE_RE.match(lines[ui]).group(1).strip(" *_").strip()
    params: dict = {}
    for l in lines[ui + 1:]:
        if not l.strip():
            break            # 空行终止本块
        m = _TOOL_KV_RE.match(l)
        if not m:
            break
        params[m.group(1).strip(" *_").strip()] = m.group(2).strip(" *_").strip()
    say = "\n".join(lines[:ui]).strip()
    return say, {"name": name, "params": params}
```

Run: `.venv/bin/python -m pytest tests/test_partner_protocol.py tests/test_parse_journey.py -q`(既有 parse 测试不许红)

- [ ] **Step 5: Commit** `feat(parse): 文本工具协议解析——用:/键:值,只认第一块尾巴丢弃`

---

### Task 3: 工具注册表 + 三工具(读文件/看地基/提设定)

**Files:**
- Create: `loom/partner_tools.py`
- Test: `tests/test_partner_tools.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ToolSpec:
      name: str; params: tuple[str, ...]; desc: str; handler: Callable; mutates: bool
  REGISTRY: dict[str, ToolSpec]         # name -> spec
  def render_contract() -> str          # 渲染进 prompt 的工具契约段(稳定前缀②)
  def run_tool(root, name, params, *, ts) -> dict   # 执行 → 结果事件 dict(不落盘,提设定产 proposal)
  def _safe_read_path(root, rel) -> Path            # 路径守卫:safe_join + 点开头拒 + 白名单
  ```

**背景(spec §5.3):** 读文件白名单=外置大脑/skills/正文(只读);点开头段一律拒;提设定 mutates=True 产 proposal 事件(不落盘,P3 的 confirm 才落)。看地基调 `slots.stage_slots` 遍历 STAGES。

- [ ] **Step 1: 失败测试**(覆盖:读文件白名单放行外置大脑、拒 `.env`/`../`/`.伙伴对话`;看地基返回槽位摘要;提设定产 proposal 带 id;超 3k 字截断)
```python
from loom import partner_tools as pt
import pytest


def test_read_allows_brain(project):
    ev = pt.run_tool(project, "读文件", {"路径": "外置大脑/世界观/金手指.md"}, ts="t")
    assert ev["t"] == "result" and "金手指" in ev["text"]


def test_read_rejects_dotfiles_and_traversal(project):
    for bad in (".env", "../secret", "外置大脑/.拆书/x.md", ".伙伴对话/当前.jsonl"):
        ev = pt.run_tool(project, "读文件", {"路径": bad}, ts="t")
        assert ev.get("error"), f"{bad} 应被拒"


def test_kandiji_returns_slots(project):
    ev = pt.run_tool(project, "看地基", {}, ts="t")
    assert ev["t"] == "result"
    assert "立项" in ev["text"] and "未填" in ev["text"]


def test_tishe_produces_proposal(project):
    ev = pt.run_tool(project, "提设定", {"落点": "外置大脑/立项卡.md#题材", "内容": "重生流"}, ts="t")
    assert ev["t"] == "proposal" and ev["id"] and ev["slot"].endswith("题材")


def test_render_contract_lists_tools():
    c = pt.render_contract()
    assert "读文件" in c and "看地基" in c and "提设定" in c
```

- [ ] **Step 2-4: 实现** `loom/partner_tools.py`(路径守卫用 `fsutil.safe_join` + 点开头检查 + 白名单前缀从 paths 派生;看地基调 `slots.stage_slots`;提设定 id 由 ts 派生)。**注意:read handler 超 3k 字截断并提示带起止行重取。**

Run: `.venv/bin/python -m pytest tests/test_partner_tools.py -q`

- [ ] **Step 5: Commit** `feat(partner): 工具注册表+三工具——读文件(白名单+点开头拒)/看地基(调slots)/提设定(产proposal)`

---

### Task 4: 上下文组装 `assemble()`

**Files:**
- Create: `loom/partner_context.py`
- Test: `tests/test_partner_context.py`

**Interfaces:**
- Produces:
  ```python
  def assemble(root: Path, tail: list[dict]) -> tuple[str, str]:
      """(system, user)。system=稳定前缀(人设+工具契约+skills索引);
      user=动态后缀(环境快照+对话尾部+工具结果)。纯派生零存储。"""
  def env_snapshot(root: Path) -> str    # ≤400字:书名/一句话设定/门禁完成度/未填槽位摘要/章节数
  ```

**背景(spec §4):** 前缀「文件不变则字节稳定」弱保证(人设/skills 改了立即生效)。环境快照与看地基共用 `slots.stage_slots`(快照=只读投影:每段一行「段名 未填N/总数:前K个未填 容器#键」)。

- [ ] **Step 1: 失败测试**(前缀稳定性:书文件不变时两次 assemble 前缀 sha 相等;改 领航员.md → 前缀变;改正文 → 只后缀变;env_snapshot 含门禁完成度且 ≤400 字)
```python
import hashlib
from loom.partner_context import assemble, env_snapshot


def _sha(s): return hashlib.sha256(s.encode()).hexdigest()[:12]


def test_prefix_stable_when_files_unchanged(project):
    s1, _ = assemble(project, [])
    s2, _ = assemble(project, [{"t": "user", "text": "hi", "ts": "x"}])
    assert _sha(s1) == _sha(s2)      # 对话尾变,前缀不变


def test_prefix_changes_when_persona_edited(project):
    s1, _ = assemble(project, [])
    p = project / "agents/领航员.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n补一句人设\n", encoding="utf-8")
    s2, _ = assemble(project, [])
    assert _sha(s1) != _sha(s2)      # 人设改了前缀变(立即生效)


def test_env_snapshot_has_gate_and_bounded(project):
    snap = env_snapshot(project)
    assert "立项" in snap and "未填" in snap
    assert len(snap) <= 500          # ≤400字硬约束留余量


def test_body_change_only_touches_suffix(project):
    s1, u1 = assemble(project, [])
    (project / "外置大脑/世界观/金手指.md").write_text("# 金手指\n\n吞噬万物\n", encoding="utf-8")
    s2, u2 = assemble(project, [])
    assert _sha(s1) == _sha(s2)      # 前缀不含正文/外置大脑明细
```

- [ ] **Step 2-4: 实现**(前缀=`_navigator_system(root)`(journey 复用,人设加载)+ `partner_tools.render_contract()` + skills 索引;后缀=env_snapshot + 对话尾部渲染 + 工具结果。env_snapshot 调 `slots.stage_slots` + `journey.writing_unlocked`)。

Run: `.venv/bin/python -m pytest tests/test_partner_context.py -q`

- [ ] **Step 5: Commit** `feat(partner): assemble 上下文组装——稳定前缀(人设+工具契约+skills索引)+动态后缀(环境快照+对话尾)`

---

### Task 5: ScriptedBackend + 对话循环 `partner.py`(含流式行缓冲纪律)

**Files:**
- Modify: `tests/conftest.py`(加 ScriptedBackend)
- Create: `loom/partner.py`
- Test: `tests/test_partner_loop.py`

**Interfaces:**
- Produces:
  ```python
  def run_turn(root, user_text, backend, *, emit, ts) -> None:
      """一轮:追加 user 事件 → assemble → complete(流式行缓冲) → 解析说话+工具 →
      有工具则执行+回喂再 complete(≤6 次) → 无工具则终结。emit(event) 转发给调用方(P3 的 ndjson)。
      两轮之间零挂起。ts 由调用方给(无 Date.now)。"""
  _MAX_TOOL_ROUNDS = 6
  ```

**背景(spec §3/§5.2,critical):** 流式行缓冲——`on_chunk` 增量按行缓冲,整行落定且以 `用:` 开头才停转发,之前的整行照发 assistant_text;chunk 行中截断免疫。ScriptedBackend 要能以「`用` 与 `:` 分两 chunk」的序列驱动。

- [ ] **Step 1: 失败测试**(单轮说话即终结;一轮工具调用→执行→回喂→再说话;≤6 次上限;解析失败回喂;流式行缓冲:协议行不漏进 assistant_text;chunk 行中截断)
```python
from loom.partner import run_turn
from conftest import ScriptedBackend


def _collect():
    evs = []
    return evs, (lambda e: evs.append(e))


def test_speech_turn_terminates(project):
    evs, emit = _collect()
    run_turn(project, "你好", ScriptedBackend(["你好呀,我们从金手指聊起?"]), emit=emit, ts="t")
    texts = [e for e in evs if e["t"] == "assistant"]
    assert texts and "金手指" in texts[-1]["text"]


def test_tool_round_then_speak(project):
    evs, emit = _collect()
    be = ScriptedBackend(["看看现状。\n用:看地基", "立项还空着,先定题材吧?"])
    run_turn(project, "帮我看看", be, emit=emit, ts="t")
    kinds = [e["t"] for e in evs]
    assert "tool" in kinds and "result" in kinds
    assert evs[-1]["t"] == "assistant" and "题材" in evs[-1]["text"]


def test_tool_rounds_capped(project):
    evs, emit = _collect()
    be = ScriptedBackend(["用:看地基"] * 10)   # 一直调工具
    run_turn(project, "x", be, emit=emit, ts="t")
    assert sum(1 for e in evs if e["t"] == "tool") <= 6


def test_protocol_line_not_leaked_to_assistant(project):
    evs, emit = _collect()
    # 说话段 + 工具块,流式按 6 字小块吐(含把「用」「:」拆开的边界)
    be = ScriptedBackend(["我查一下金手指。\n用:看地基"], stream=True)
    run_turn(project, "x", be, emit=emit, ts="t")
    for e in evs:
        if e["t"] == "assistant":
            assert "用:" not in e["text"] and "看地基" not in e["text"]


def test_delete_dialogue_keeps_book(project):
    from loom.journey import journey_state
    before = journey_state(project)["current"]
    run_turn(project, "定个题材:重生流", ScriptedBackend(["好"]), emit=lambda e: None, ts="t")
    import shutil
    shutil.rmtree(project / ".伙伴对话")
    assert journey_state(project)["current"] == before   # 删对话,门禁不变
```

- [ ] **Step 2-4: 实现** `conftest.py` 的 `ScriptedBackend`(list pop,`stream=True` 时把回复按 6 字小块 + 故意在 `用`/`:` 之间切一刀喂 on_chunk),`loom/partner.py` 的循环(assemble → complete(on_chunk=行缓冲器) → parse_tool_block → run_tool → append jsonl + emit → 回喂再 complete,≤6 轮)。

Run: `.venv/bin/python -m pytest tests/test_partner_loop.py -q`

- [ ] **Step 5: Commit** `feat(partner): 对话循环 run_turn——assemble/complete/流式行缓冲/工具执行回喂/≤6轮/零挂起`

---

### Task 6: P2 全量回归 + 离线多轮闭环烟测(控制者)

- [ ] Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m evals.run_eval --gate` — 全绿 + 无回归。
- [ ] 离线多轮烟测(临时书,ScriptedBackend):模拟起书对话 3-4 轮(看地基→提设定→拍板前的 proposal 事件),确认 jsonl 落对、proposal 可 find、删 `.伙伴对话/` 门禁不变。**先钉临时书。**
- [ ] 汇报:P2 新增测试计数、多轮闭环输出。不合并——等 P3。

## P3 预告

server /api/partner/say(流式+锁裁量)/confirm/new/history + 双形态对话 UI + 退役卡片机 + demo 罐头多轮 + CLI 护栏伙伴变体 + ADR 0015/0014 修订 + CONTEXT/领航员.md 改写。P1+P2+P3 齐后统一终审。
