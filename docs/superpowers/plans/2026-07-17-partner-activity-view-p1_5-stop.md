# 伙伴「执行活动视图」P1.5 实施计划(停)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 给伙伴对话一个「停」——前端 abort 立刻拿回控制权,后端在轮边界释放锁;并修「停」重开的归档-写入竞态 blocker。

**Architecture:** 三块。(1) blocker 修复:`partner_new` 归档前 `try_partner_lock` 门禁,worker 还持轮锁则 409(把「busy≠worker存活」的裂缝在服务端补上)。(2) 轮内取消:`run_turn` 加 `should_cancel` 回调(while 顶检查,**不**传给 `backend.complete()`,故不碰后端签名),server 用 `threading.Event` 经 `stream()` finally 置旗。(3) 前端:AbortController + 停止键 + `_partnerStopped` 标记。

**Tech Stack:** Python(loom/usecases.py·partner.py·server.py)+ 原生 JS(app.js)+ pytest。

## Global Constraints

- **不碰** `backends.py`、Backend Protocol、`partner_tools.py`、`partner_context.py`、`partner_store.py`、任何测试替身签名。`should_cancel` 是 `run_turn` 的本地参数,**绝不传给** `backend.complete()`(ScriptedBackend/FakeBackend 无此参数,传了会 TypeError)。
- **取消在轮边界生效**:`while True` 顶部检查;正跑的 `backend.complete()` 会跑完(spec §10.3/§10.4)。促发性 ≤ 一次生成(流式亚秒,CLI 可能整轮)。
- **blocker**:`partner_new` 走写锁不走轮锁(usecases.py:462),故必须加轮锁门禁,否则 abort 后 worker 仍在写而归档改名 `当前.jsonl` → 孤儿事件串进新会话(spec §10.2)。
- **abort 分辨**:reader 抛 `AbortError`(用户停)→ 不追加 error 事件;真中断维持现有「连接中断」。
- **`_partnerStopped` 三处清零**:partnerSay 开头、enterProject(app.js:480 换书)、partnerNewThread(app.js:1449 另起)——镜像 `_partnerGen`/`_partnerBusy` 生命周期(spec §10.1 / 评审 finding #4)。
- 冒烟前 `loom_root` 钉 scratch 书,绝不碰真书。提交 `git add` 具体文件;Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>;不 push/不 merge。
- **GeneratorExit 断连时机**是已知实现风险(spec §10.5):离线 pytest 不可靠验,只走真机冒烟;不实断言不写进测试。

---

### Task 1: 归档锁门禁(blocker 修复)

**Files:**
- Modify: `loom/usecases.py:459-464`(`partner_new`)
- Test: `tests/test_partner_usecases.py`

**Interfaces:**
- Consumes: 既有 `try_partner_lock(root) -> Lock|None`(usecases.py:100)、`ProjectBusyError(msg, code=)`(:53)、`PARTNER_BUSY_MESSAGE`(:94)、`write_lock`、`partner_store.archive_current`
- Produces: `partner_new` 在轮锁被占时抛 `ProjectBusyError(code="partner_busy")`(经 server.py:52 全局 handler → 409)

- [ ] **Step 1: 写失败测试**(tests/test_partner_usecases.py 末尾追加)

```python
def test_partner_new_blocked_while_partner_lock_held(project):
    import pytest
    # 模拟 say worker 正持轮锁(停之后 worker 尚在收尾的窗口)
    guard = usecases.try_partner_lock(project)
    assert guard is not None
    try:
        with pytest.raises(usecases.ProjectBusyError) as ei:
            usecases.partner_new(project, stamp="t")
        assert ei.value.code == "partner_busy"   # 归档被轮锁挡住,不改名当前.jsonl
    finally:
        guard.release()


def test_partner_new_succeeds_when_partner_lock_free(project):
    # 轮锁空闲(worker 已收尾)→ 正常归档
    out = usecases.partner_new(project, stamp="t2")
    assert out["ok"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_partner_usecases.py::test_partner_new_blocked_while_partner_lock_held -q`
Expected: FAIL(现 `partner_new` 不拿轮锁,不抛 ProjectBusyError → `pytest.raises` 落空)。

- [ ] **Step 3: 实现门禁**(usecases.py:459-464 替换)

把:
```python
def partner_new(root: Path | str, *, stamp: str) -> dict:
    """归档当前伙伴对话,另起一段(不动书内容,只挪 jsonl 文件)。"""
    root = Path(root)
    with write_lock(root):
        partner_store.archive_current(root, stamp)
        return {"ok": True}
```
改为:
```python
def partner_new(root: Path | str, *, stamp: str) -> dict:
    """归档当前伙伴对话,另起一段(不动书内容,只挪 jsonl 文件)。

    先拿伙伴轮锁再归档(blocker 修复,spec §10.2):say worker 从头到尾持轮锁,
    「停」在前端提前清 _partnerBusy 后 worker 可能仍在写尾巴事件——此时归档若改名
    当前.jsonl,worker 的 append 会重建一个没有 user 事件的孤儿文件,旧轮尾巴串进
    新会话。轮锁被占 → 409 partner_busy,挡住归档直到 worker 收尾放锁。
    """
    root = Path(root)
    guard = try_partner_lock(root)
    if guard is None:
        raise ProjectBusyError(PARTNER_BUSY_MESSAGE, code="partner_busy")
    try:
        with write_lock(root):
            partner_store.archive_current(root, stamp)
            return {"ok": True}
    finally:
        guard.release()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_partner_usecases.py -q`
Expected: PASS(新增两条 + 既有全绿)。

- [ ] **Step 5: Commit**

```bash
git add loom/usecases.py tests/test_partner_usecases.py
git commit -m "fix(partner): 归档加轮锁门禁——修停重开的归档-写入竞态(blocker)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 轮内取消 should_cancel + server 取消旗

**Files:**
- Modify: `loom/partner.py:117`(`run_turn` 签名)、`:152`(while 顶检查)
- Modify: `loom/server.py:700-740`(`partner_say`:cancel Event + 传 should_cancel + stream finally)
- Test: `tests/test_partner_loop.py`

**Interfaces:**
- Consumes: 既有 `run_turn(root, user_text, backend, *, emit, ts)`、server 的 worker/stream/queue 骨架
- Produces: `run_turn(..., should_cancel: Callable[[], bool] | None = None)`;取消在 while 顶生效

- [ ] **Step 1: 写失败测试**(tests/test_partner_loop.py 末尾追加)

```python
def test_should_cancel_returns_before_any_complete(project):
    evs, emit = _collect()
    be = ScriptedBackend(["不该被调用"])
    run_turn(project, "你好", be, emit=emit, ts="t", should_cancel=lambda: True)
    assert be.calls == []                       # 顶部即取消,complete 从未调用
    assert any(e["t"] == "user" for e in evs)   # user 事件在循环前已落(不丢)


def test_should_cancel_stops_at_round_boundary(project):
    evs, emit = _collect()
    be = ScriptedBackend(["用:看地基"] * 10)     # 不取消会跑满 6 轮工具
    n = {"i": 0}
    def sc():
        n["i"] += 1
        return n["i"] > 2                        # 前两轮顶放行,第三轮顶取消
    run_turn(project, "x", be, emit=emit, ts="t", should_cancel=sc)
    assert len(be.calls) == 2                     # 只跑两轮 complete,第三轮顶提前 return


def test_should_cancel_none_is_unchanged(project):
    evs, emit = _collect()
    be = ScriptedBackend(["用:看地基"] * 10)
    run_turn(project, "x", be, emit=emit, ts="t", should_cancel=None)
    assert sum(1 for e in evs if e["t"] == "tool") <= 6   # 与 test_tool_rounds_capped 一致,行为不变
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_partner_loop.py::test_should_cancel_returns_before_any_complete -q`
Expected: FAIL(`run_turn` 尚无 `should_cancel` 形参 → TypeError: unexpected keyword argument)。

- [ ] **Step 3: run_turn 加形参 + while 顶检查**(partner.py)

签名(:117)由:
```python
def run_turn(root, user_text, backend, *, emit, ts) -> None:
```
改为:
```python
def run_turn(root, user_text, backend, *, emit, ts, should_cancel=None) -> None:
```
并在 `while True:`(:152)之后、`tail = ...` 之前插入取消检查:
```python
    while True:
        if should_cancel is not None and should_cancel():
            return   # 轮边界取消(spec §10.3):user 事件已落,正跑的 complete 不在此处
        tail = partner_store.read_events(root)
```
(注:`should_cancel` **只**在此本地判定,**绝不**混进 `complete_kwargs`/传给 `backend.complete()`——否则撞测试替身签名。)

- [ ] **Step 4: 跑 run_turn 测试确认通过**

Run: `python3 -m pytest tests/test_partner_loop.py -q`
Expected: PASS(新增三条 + 既有全绿)。

- [ ] **Step 5: server 接线取消旗**(server.py `partner_say`,700-740)

`worker()` 之前建 Event,worker 传 should_cancel,stream 的 finally 置旗。替换整个 `partner_say` 体的 worker/stream 部分为:
```python
    q: queue.Queue = queue.Queue()
    cancel = threading.Event()

    def worker():
        ts = time.strftime("%Y%m%d-%H%M%S")
        try:
            cfg = load_config(root)
            partner.run_turn(root, b.text, get_backend(cfg), emit=q.put, ts=ts,
                             should_cancel=cancel.is_set)
        except LoomBackendError as e:
            err_ev = {"t": "error", "text": str(e), "ts": ts}
            if e.code:
                err_ev["code"] = e.code
            q.put(err_ev)
        except (ValueError, FileNotFoundError) as e:
            q.put({"t": "error", "text": str(e), "ts": ts})
        except Exception as e:  # 兜底,别让流挂死
            q.put({"t": "error", "text": f"意外错误:{e}", "ts": ts})
        finally:
            lock.release()   # 锁跟着 worker 走(响应流着,轮还没完),在哨兵 None 之前放
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        try:
            while True:
                ev = q.get()
                if ev is None:
                    break
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        finally:
            # 客户端断连(前端 abort)→ 生成器被关闭 → 置取消旗,worker 下一轮边界停并放锁。
            # 正常收尾(哨兵 None break)时 worker 已 return,置旗是无副作用的 no-op(spec §10.3)。
            cancel.set()

    return StreamingResponse(stream(), media_type="application/x-ndjson")
```

- [ ] **Step 6: 跑相关端点测试确认通过**

Run: `python3 -m pytest tests/test_partner_endpoints.py tests/test_partner_loop.py -q`
Expected: PASS(既有端点测试正常消费流,新增取消旗对正常流是 no-op)。

- [ ] **Step 7: Commit**

```bash
git add loom/partner.py loom/server.py tests/test_partner_loop.py
git commit -m "feat(partner): 轮内取消should_cancel(while顶,不碰后端签名)+server断连置旗

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 前端 abort + 停止键 + 已停止标记

**Files:**
- Modify: `loom/webui/app.js`:模块级 `_partnerAbort`/`_partnerStopped` 声明;`partnerSay`(1015-1081);`paintPartnerChat`(停止键 + 已停止标记);`enterProject`(480);`partnerNewThread`(1440-1458)
- Modify: `loom/webui/style.css`(`.pc-stopped` 样式)

**Interfaces:**
- Consumes: 既有 `_partnerBusy`/`_partnerGen`/`_partnerDelta`、`partnerSay`、`paintJourney`
- Produces: 用户可点「停止」中止本轮;`· 已停止 ·` 标记;另起 409 友好提示

- [ ] **Step 1: 声明模块级状态**(app.js,靠近 `_partnerBusy` 声明处 ~22-25)

在 `_partnerDelta` 等声明附近加:
```js
let _partnerAbort = null;     // 本轮 AbortController(停止键用);轮结束置 null
let _partnerStopped = false;  // 上一轮被用户「停」→ 渲染尾部出「· 已停止 ·」;换书/另起/再发清零
```

- [ ] **Step 2: partnerSay 挂 AbortController + abort 分辨**(app.js:1015 起)

`partnerSay` 开头(设 `_partnerBusy = true` 附近)加:
```js
  _partnerStopped = false;                    // 新一轮:清上轮的已停止标记
  const ctrl = new AbortController();
  _partnerAbort = ctrl;
```
fetch 调用(1025-1028)加 `signal`:
```js
    resp = await fetch("/api/partner/say", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root, text }),
      signal: ctrl.signal,
    });
```
**fetch 的 catch**(1029-1037)开头加 abort 分辨(用户停不算失败):
```js
  } catch (e) {
    if (e && e.name === "AbortError") {          // 用户点了停止,不是连接失败
      if (gen === _partnerGen) { _partnerBusy = false; _partnerStopped = true; }
      if (gen === _partnerGen && DATA && DATA.root === root) paintJourney();
      return;
    }
    if (gen === _partnerGen) _partnerBusy = false;
    ...既有连接失败处理不变...
```
**reader 循环的 catch**(1069-1073)同样先分辨 abort:
```js
  } catch (e) {
    if (!(e && e.name === "AbortError") && gen === _partnerGen && DATA && DATA.root === root) {
      if (!PARTNER) PARTNER = { events: [] };
      PARTNER.events.push({ t: "error", text: "连接中断:" + e.message });
    }
    if (e && e.name === "AbortError" && gen === _partnerGen) _partnerStopped = true;
  } finally {
```
**finally**(1074-1080)加 `_partnerAbort` 清理(仅当仍是本轮):
```js
  } finally {
    if (gen === _partnerGen) {
      _partnerBusy = false;
      _partnerDelta = "";
      _partnerAbort = null;
      if (DATA && DATA.root === root) paintJourney();
    }
  }
```

- [ ] **Step 3: paintPartnerChat 停止键 + 已停止标记**(app.js)

**停止键**:`sendBtn` 定义处(~1153-1157),把静态 send 改成随 busy 切换:
```js
  const sendBtn = document.createElement("button");
  sendBtn.className = "jc-btn pc-send";
  if (_partnerBusy) {
    sendBtn.textContent = "停止";
    sendBtn.disabled = false;
    sendBtn.onclick = () => { if (_partnerAbort) _partnerAbort.abort(); };
  } else {
    sendBtn.textContent = "发送";
    sendBtn.disabled = loading;
    sendBtn.onclick = doSend;
  }
```
**已停止标记**:在渲染完事件、busy 块之后(即 `if (_partnerBusy) {...}` 块之后、input 行之前 ~1133),加:
```js
  if (_partnerStopped && !_partnerBusy) {
    const stopped = document.createElement("div");
    stopped.className = "pc-stopped";
    stopped.textContent = "· 已停止 ·";
    scroll.appendChild(stopped);
  }
```

- [ ] **Step 4: 三处清零 `_partnerStopped`**(app.js)

`enterProject`(480,换书清伙伴态那行)在 `PARTNER = null; ...` 同处加 `_partnerStopped = false;`:
```js
  PARTNER = null; _partnerRoot = null; _partnerBusy = false; _partnerDelta = ""; _partnerStopped = false; _partnerGen++;
```
`partnerNewThread`(1449-1450,另起重置处)加:
```js
    _partnerGen++;
    _partnerStopped = false;
    PARTNER = { events: [] };
```

- [ ] **Step 5: partnerNewThread 409 友好提示**(app.js:1454-1457)

`catch (e)` 里对 partner_busy 409 给专属文案(worker 收尾窗口):
```js
  } catch (e) {
    if (!DATA || DATA.root !== root) return;
    const msg = /partner_busy|还在应答|收尾/.test(e.message || "") ? "伙伴还在收尾,稍等一下再另起" : e.message;
    toast(msg, true);
  }
```

- [ ] **Step 6: CSS**(style.css,`.pc-tool-done` 行后)

```css
.pc-stopped { text-align: center; font-size: var(--fs-xs); color: var(--text-mute);
  font-style: italic; padding: 2px 0; }
```

- [ ] **Step 7: 语法自检 + Commit**

```bash
node --check loom/webui/app.js && echo OK
git add loom/webui/app.js loom/webui/style.css
git commit -m "feat(partner): 前端停止键+AbortController+已停止标记(三处清零)+另起409提示

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 全量回归 + 浏览器冒烟(停)

**Files:** 无(验证)

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest -q 2>&1 | tail -8`
Expected: 全绿(562 + 新增 5 条 = 567)。

- [ ] **Step 2: 起 demo server(需重启以载入后端改动)+ 钉 loom_root scratch**

后端(usecases/partner/server)变了,须重启 dev server。用 loom-demo 或 loom-dev。**loom_root 钉 scratch 测试书**(见 P1 计划)。

- [ ] **Step 3: 冒烟——停止键拿回控制**

发一条触发多轮的话,伙伴回复中点「停止」。验:输入框立刻可用(_partnerBusy=false)、出「· 已停止 ·」、无「连接中断」error 气泡。read_console 确认无 JS 报错。

- [ ] **Step 4: 冒烟——另起 409 门禁(blocker)**

在 worker 仍持轮锁的窗口点「另起一段对话」→ 应 toast「伙伴还在收尾,稍等」,`当前.jsonl` 不被过早改名(可查 scratch 书 `.伙伴对话/` 目录无孤儿新文件)。收尾后另起正常。

- [ ] **Step 5: GeneratorExit 促发性(诚实验)**

停止后观察 server 端锁是否在 ≤ 一次生成内释放(demo 后端快,近即时;真 CLI/流式后端此项留待真机)。**若发现锁不释放**(再发一直 409)→ 记录并切 spec §10.5 回退方案(显式 /api/partner/stop 端点)。记录实测结论。

- [ ] **Step 6: 截图留证**

computer screenshot 存证「· 已停止 ·」态。此任务不改代码,无 commit(冒烟发现 bug 回对应 Task 修)。

---

## Self-Review

**Spec coverage**(对 spec §10):
- §10.1 前端 abort/停止键/_partnerStopped 三处清零/409 提示 → Task 3 ✓
- §10.2 归档锁门禁(blocker)→ Task 1 ✓
- §10.3 run_turn should_cancel + server 旗 → Task 2 ✓
- §10.4 促发性 → Task 4 Step 5 诚实验 ✓
- §10.5 GeneratorExit 回退 → Task 4 Step 5 记录 ✓
- §10.6 测试(should_cancel 单测 + partner_new 409 可离线;GeneratorExit 只真机)→ Task 1/2 测试 + Task 4 ✓
- §10.7 改动面(app.js/css/partner.py/server.py/usecases.py,不碰 backends/Protocol/替身)→ 各 Task Files 一致 ✓

**Placeholder scan:** 无 TBD;每步完整代码/命令 ✓

**Type consistency:** `should_cancel: Callable|None=None` 在 run_turn 定义与 server 传参(`cancel.is_set`)一致,且不进 complete_kwargs;`try_partner_lock`/`ProjectBusyError(code=)` 用法与 usecases.py 现有一致;`_partnerAbort`/`_partnerStopped` 声明与三处清零/两处 catch 用法一致 ✓
