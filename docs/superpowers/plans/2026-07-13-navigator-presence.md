# 领航员在场形态改造 · 实施计划(起书居中 + 悬浮球)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 领航员从侧栏小卡变为「未解锁时占主区居中、解锁后右下 48px 悬浮球」,dismiss 废弃、门禁弹层退役、织章隐身。

**Architecture:** 纯前端(后端零改动):`navMode()` 纯推导六态;`paintJourney` 容器参数化,同一份渲染画进 `#nav-center`(居中)或 `#nav-popover`(球浮层);`openGateGuide` 改转发聚焦居中卡。spec:[navigator-presence-design](../specs/2026-07-13-navigator-presence-design.md)。

**Tech Stack:** vanilla JS + 纸墨 CSS token。零新依赖。IP 头像由 A 轨并行产出(navigator.jpg 缺失时首字徽标兜底,不阻塞本计划)。

## Global Constraints(每任务隐含遵守)

- **后端零改动**;三态判定只用现有 `DATA.writing_unlocked / has_body / chapters / missing / fingerprint_source` 与 `JOURNEY.stages/current/card`。
- **同一份渲染**:paintJourney 容器参数化,不复制渲染函数;展示密度差异用宿主修饰类 + CSS。
- **dismiss 废弃**:`loom_journey_dismiss:` 键不再读写(存量键值自然失效);居中态不可关只可让位(会话级 `_navYield`,不落 localStorage)。
- **换书守卫延续**:任何新异步取数/开合状态照抄 `const root = DATA && DATA.root; … if (!DATA || DATA.root !== root) return;`;`enterProject` 清 `_navYield/_weaving/popover 开合`。
- **动效克制**:内容切换 120-160ms 淡入;交接动效仅 S0→S2 一次(localStorage once 键);无 FLIP、无吉祥物动画。
- **CSS 走纸墨 token**(`--space/--fs/--radius/--dur/--seal/--line`),悬浮球 z-index 30-35 段位(低于 overlay 40);`body.focus-mode`/`body.typing` 下球隐藏。
- 每任务 `node --check loom/webui/app.js` 必过;全量 `.venv/bin/python -m pytest -q` 必绿(后端不动,数字不变);UI 冒烟由控制者 preview 做(钉 loom_root 测试书)。
- 提交中文 `feat(webui)/fix(webui)`。

---

### Task 1: 宿主与 CSS 骨架(纯增量,不切换渲染)

**Files:**
- Modify: `loom/webui/index.html`(editor-pane 内加 `#nav-center`;body 末加 `#nav-ball`+`#nav-popover`;`#journey-card` 保留暂不删)
- Modify: `loom/webui/style.css`(新 §7h:nav-center/nav-ball/nav-popover/交接与内容过渡/focus-typing 隐藏;顺手 `.jc-opt/.jc-btn` 硬编码灰→token)

**Interfaces:**
- Produces:DOM 锚点 `#nav-center`(初始 hidden)、`#nav-ball`(初始 hidden,内含 `agentAvatar` 位与 `.nav-dot` 未读点)、`#nav-popover`(初始 hidden);CSS 类 `.nav-center-card/.nav-strip/.nav-yield/.nav-dot/.nav-handoff`

- [ ] **Step 1: index.html——editor-pane 内(editor-scroll 之前)插入居中宿主**

在 `<section class="editor-pane">` 的 `editor-head` 与 `editor-scroll` 之间插:

```html
      <div id="nav-center" class="nav-center hidden">
        <div class="nav-center-inner">
          <div class="nav-center-head">
            <span id="nav-center-ava"></span>
            <div class="nav-center-title">
              <div class="nav-center-name">领航员 · 陪你把地基打完</div>
              <div class="nav-center-sub" id="nav-center-sub"></div>
            </div>
          </div>
          <div id="nav-center-strip" class="nav-strip"></div>
          <div id="nav-center-card" class="journey-card nav-host"></div>
          <div class="nav-center-foot">
            <button id="nav-browse" class="ghost">先自己逛逛</button>
          </div>
        </div>
      </div>
```

- [ ] **Step 2: index.html——body 末(guide-overlay 之后)加球与浮层**

```html
  <button id="nav-ball" class="nav-ball hidden" title="领航员">
    <span id="nav-ball-ava"></span>
    <span id="nav-dot" class="nav-dot hidden"></span>
  </button>
  <div id="nav-popover" class="nav-popover hidden">
    <div id="nav-pop-list" class="nav-pop-list"></div>
    <div id="nav-pop-card" class="journey-card nav-host"></div>
  </div>
```

- [ ] **Step 3: style.css——§7f 之后新 §7h(全部用既有 token)**

```css
/* ---------- 7h. 领航员在场形态:起书居中 + 悬浮球 ---------- */
.nav-center { flex: 1; display: flex; align-items: flex-start; justify-content: center;
  overflow-y: auto; padding: var(--space-7) var(--space-4); }
.nav-center-inner { width: 100%; max-width: 540px; animation: navFadeUp var(--dur-3) var(--ease-out); }
@keyframes navFadeUp { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.nav-center-head { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.nav-center-head .jc-ava, .nav-center-head .jc-fallback { width: 64px; height: 64px; font-size: 24px; }
.nav-center-name { font-family: var(--font-brand); font-size: var(--fs-lg); }
.nav-center-sub { color: var(--text-soft); font-size: var(--fs-sm); margin-top: 2px; }
.nav-center-sub.hot { color: var(--seal); transition: color var(--dur-4); }
.nav-strip { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-bottom: var(--space-4); }
.nav-strip .ns-seg { cursor: pointer; font-size: var(--fs-sm); color: var(--text-soft);
  padding: 2px var(--space-2); border-radius: var(--radius-pill); border: 1px solid var(--line); }
.nav-strip .ns-seg.done { color: var(--text); border-color: transparent; }
.nav-strip .ns-seg.next { color: var(--text); border-color: var(--line-strong); font-weight: 600; }
.nav-center .journey-card.nav-host { border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: var(--space-4); background: var(--surface); }
.nav-center-foot { margin-top: var(--space-3); display: flex; justify-content: flex-end; }
.nav-ball { position: fixed; right: var(--space-4); bottom: var(--space-4); z-index: 32;
  width: 48px; height: 48px; border-radius: 50%; border: 1px solid var(--line);
  background: var(--surface); box-shadow: var(--shadow-2); cursor: pointer; padding: 0; }
.nav-ball .jc-ava, .nav-ball .jc-fallback { width: 100%; height: 100%; border-radius: 50%; font-size: 18px; }
.nav-ball .nav-dot { position: absolute; top: 2px; right: 2px; width: 6px; height: 6px;
  border-radius: 50%; background: var(--seal); }
.nav-ball.nav-handoff { animation: pulse-gold 1.2s var(--ease-out) 1; }
.nav-popover { position: fixed; right: var(--space-4); bottom: 64px; z-index: 33; width: 320px;
  max-height: 60vh; overflow-y: auto; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-3); padding: var(--space-3); }
.nav-pop-list { display: flex; flex-direction: column; gap: var(--space-1); margin-bottom: var(--space-2); }
.nav-pop-list .np-item { font-size: var(--fs-sm); color: var(--text-soft); cursor: pointer; }
.nav-pop-list .np-item::before { content: "●"; color: var(--seal); font-size: 8px; margin-right: 6px; }
body.focus-mode .nav-ball, body.focus-mode .nav-popover,
body.typing .nav-ball, body.typing .nav-popover { display: none; }
```

并顺手替换 §7f 内 `.jc-opt/.jc-opt:hover/.jc-input/.jc-btn` 的 `rgba(127,127,127,…)` 为 `var(--line)`(hover/边框强调用 `var(--line-strong)`)。若 `pulse-gold` keyframes 只挂在既有选择器名下,确认 `.nav-ball.nav-handoff` 能复用(keyframes 是全局的,可直接引用)。

- [ ] **Step 4: 验证 + 提交**

Run: `node --check loom/webui/app.js && .venv/bin/python -m pytest -q`
Expected: JS 未动照过;全量绿。preview:界面与之前完全一致(新宿主全 hidden,纯增量)。

```bash
git add loom/webui/index.html loom/webui/style.css
git commit -m "feat(webui): 领航员形态宿主与CSS骨架——nav-center/nav-ball/nav-popover(hidden纯增量)+jc-*硬编码灰换token"
```

---

### Task 2: navMode 分发 + paintJourney 容器参数化 + dismiss 废弃(核心切换)

**Files:**
- Modify: `loom/webui/app.js`
- Modify: `loom/webui/index.html`(删 `#journey-card` 侧栏宿主一行,约 :76)

**Interfaces:**
- Consumes:Task 1 的 DOM 锚点;既有 `paintJourney/renderJourney/loadJourney/agentAvatar/postJourneyGoto/jcBtn/JOURNEY/DATA`
- Produces:
  - `navMode() -> "hidden"|"center"|"float"`(spec §2 推导式;`_weaving`、`_navYield` 模块级会话变量)
  - `journeyHost() -> HTMLElement`(center→`#nav-center-card`;float→`#nav-pop-card`)
  - `renderJourney()` 按 navMode 控制 `#nav-center`/`#nav-ball`/editor-scroll 显隐 + 画头像/副标题/段进度条/球未读点
  - `toggleNavPopover(open?)`;dismiss 键读写全删

- [ ] **Step 1: 模块级状态与推导(app.js 顶部全局态区)**

```js
let _navYield = false;   // 居中态让位(会话级,换书清零;不落 localStorage)
let _weaving = false;    // 织章中(领航员隐身)
let _navPopOpen = false; // 球浮层开合(重画后按此恢复)

function navMode() {
  if (!DATA) return "hidden";
  if (_weaving) return "hidden";
  if (DATA.writing_unlocked === false) return _navYield ? "float" : "center";
  return "float";
}
function journeyHost() {
  return navMode() === "center" ? $("nav-center-card") : $("nav-pop-card");
}
```

`enterProject(d)` 里(现清 JOURNEY 处)追加:`_navYield = false; _weaving = false; _navPopOpen = false;`

- [ ] **Step 2: paintJourney 容器参数化**

`paintJourney` 里 `const card = $("journey-card")` 改为 `const card = journeyHost()`;函数内所有对该变量的引用不变。删除函数内「全 done 自动收起写 dismiss + hidden」分支(769-771 一带):全 done 且已解锁时 navMode 本就是 float,球形态自然承接;未解锁全跳过的死角已被门禁段禁 skip 消灭。头部 `dis`(×按钮)构造整段删除(dismiss 废弃);头像 prepend 保留(浮层里 24px 版)。

- [ ] **Step 3: renderJourney 重写为形态编排**

```js
function renderJourney() {
  const mode = navMode();
  const center = $("nav-center"), ball = $("nav-ball"), pop = $("nav-popover");
  const editorScroll = document.querySelector(".editor-scroll");
  if (!center) return;
  center.classList.toggle("hidden", mode !== "center");
  if (editorScroll) editorScroll.classList.toggle("hidden", mode === "center");
  ball.classList.toggle("hidden", mode !== "float");
  if (mode !== "float") { pop.classList.add("hidden"); _navPopOpen = false; }
  else pop.classList.toggle("hidden", !_navPopOpen);
  if (mode === "hidden") return;
  // 头像位(球与居中头各一次,幂等重建)
  const ava = $("nav-center-ava"), bava = $("nav-ball-ava");
  if (ava) { ava.innerHTML = ""; ava.appendChild(agentAvatar("领航员", "jc-ava", "jc-fallback")); }
  if (bava) { bava.innerHTML = ""; bava.appendChild(agentAvatar("领航员", "jc-ava", "jc-fallback")); }
  if (mode === "center") paintNavCenterChrome();
  if (mode === "float") paintNavDot();
  loadJourney();   // 取 journey/state → paintJourney() 画进 journeyHost()
}
```

`loadJourney` 内的双帧闪烁顺手治:有缓存 `JOURNEY` 且同书时先 `paintJourney()` 再后台刷新(守卫照旧)。

- [ ] **Step 4: 居中态镶边(chrome)与球未读点**

```js
function paintNavCenterChrome() {
  const missing = DATA.missing || [];
  $("nav-center-sub").textContent = missing.length ? `距开写还差 ${missing.length} 项:${missing.join("、")}` : "地基快齐了";
  const strip = $("nav-center-strip"); strip.innerHTML = "";
  ((JOURNEY && JOURNEY.stages) || []).forEach((s) => {
    const seg = document.createElement("span");
    seg.className = "ns-seg" + (s.done ? " done" : "") + (JOURNEY && s.key === JOURNEY.current ? " next" : "");
    seg.textContent = (s.done ? "✓ " : s.skipped ? "– " : "○ ") + s.key;
    seg.onclick = () => postJourneyGoto(s.key, false);
    strip.appendChild(seg);
  });
}

function navUnread() {
  const chs = DATA.chapters || [];
  const last = chs[chs.length - 1];
  if (last && last.edited && !last.learned) return "上一章的手改可以 learn 了";
  const voice = ((JOURNEY && JOURNEY.stages) || []).find((s) => s.land === "seed");
  if (voice && !voice.done && !voice.skipped && DATA.fingerprint_source === "default") return "喂几段样本,让指纹像你";
  if (DATA.writing_unlocked && (DATA.missing || []).length) return `地基还差:${DATA.missing.join("、")}`;
  return "";
}
function paintNavDot() { $("nav-dot").classList.toggle("hidden", !navUnread()); }
```

- [ ] **Step 5: 球开合 + 「先自己逛逛」+ openFile 让位(bind() 区)**

```js
  $("nav-ball").onclick = () => { _navPopOpen = !_navPopOpen; renderJourney(); if (_navPopOpen) paintNavPopList(); };
  $("nav-browse").onclick = () => { _navYield = true; renderJourney(); };
```

```js
function paintNavPopList() {
  const list = $("nav-pop-list"); list.innerHTML = "";
  const msg = navUnread();
  if (msg) { const it = document.createElement("div"); it.className = "np-item"; it.textContent = msg; list.appendChild(it); }
  if (DATA.writing_unlocked === false) {
    const back = document.createElement("div"); back.className = "np-item"; back.textContent = "继续答题(回到居中)";
    back.onclick = () => { _navYield = false; _navPopOpen = false; renderJourney(); };
    list.appendChild(back);
  }
}
```

`openFile(...)` 函数体开头加一行让位:`if (navMode() === "center") { _navYield = true; renderJourney(); }`

- [ ] **Step 6: dismiss 键退役——删 4 处**

app.js 中 `loom_journey_dismiss` 的全部读写删除:renderJourney 入口守卫(原 699)、×按钮写入(原 736,随 Step 2 删)、全 done 自动收起写入(原 770,随 Step 2 删)、openGateGuide 里 removeItem(原 1013,Task 3 一并改)。`grep -c loom_journey_dismiss loom/webui/app.js` 应为 0(Task 3 完成后)。

- [ ] **Step 7: 删 index.html :76 侧栏 `#journey-card` 一行;验证 + 提交**

Run: `node --check loom/webui/app.js && grep -c 'journey-card"' loom/webui/index.html && .venv/bin/python -m pytest -q`
Expected: 语法过;index.html 中 `id="journey-card"` 零命中(类名 journey-card 仍在新宿主 class 上);全量绿。

```bash
git add loom/webui/app.js loom/webui/index.html
git commit -m "feat(webui): navMode三态分发——paintJourney容器参数化/居中chrome+段条/球未读点+popover/openFile让位/dismiss键退役/删侧栏卡"
```

---

### Task 3: 门禁转发 + 织章隐身 + 交接动效(语义收口)

**Files:**
- Modify: `loom/webui/app.js`

**Interfaces:**
- Consumes:Task 2 的 `navMode/_navYield/_weaving/renderJourney`;既有 `openGateGuide/writeChapter/closeRun/postJourneyGoto`
- Produces:`enterNavCenter(missing)`;`openGateGuide` 转发壳;`_weaving` 翻转两处;S0→S2 一次性交接(`loom_nav_handoff:<root>` once 键)

- [ ] **Step 1: enterNavCenter + openGateGuide 转发**

```js
function enterNavCenter(missing) {
  _navYield = false; _navPopOpen = false;
  renderJourney();
  const sub = $("nav-center-sub");
  if (sub) { sub.classList.add("hot"); setTimeout(() => sub.classList.remove("hot"), 1000); }
  const first = (missing || [])[0];
  if (first) postJourneyGoto(first, false);
}
function openGateGuide(missing) { enterNavCenter(missing); }   // 弹层退役,签名不动(软拦与409两调用点无感)
```

原 openGateGuide 函数体(showGuide 弹层 + removeItem dismiss)整体替换为上面转发;确认写前软拦(约 1640)与 409 分支(约 1670)两个调用点无需改动。

- [ ] **Step 2: 织章隐身两行**

`writeChapter` 内发起 fetch 前(现 run-overlay 打开处)加:`_weaving = true; renderJourney();`
`closeRun()`(约 1819)与 writeChapter 的流 `finally`/非 ndjson 错误 return 前加:`_weaving = false; renderJourney();`(确认所有提前 return 路径都恢复——非 ndjson 分支、连接失败 catch、正常 finally 三处)。

- [ ] **Step 3: S0→S2 一次性交接**

`refresh()` 或 `enterProject` 后的渲染点上检测翻转:在 `renderJourney()` 开头加——

```js
  const hk = DATA ? "loom_nav_handoff:" + DATA.root : "";
  if (hk && DATA.writing_unlocked && (DATA.chapters || []).length === 0 && !localStorage.getItem(hk)) {
    localStorage.setItem(hk, "1");
    const ball = $("nav-ball");
    if (ball) { ball.classList.add("nav-handoff"); setTimeout(() => ball.classList.remove("nav-handoff"), 1400); }
    _navPopOpen = true;   // 交接后自动开一次浮层
    setTimeout(() => { toast("地基齐了——去织第一章。我搬去右下角,随叫随到"); }, 200);
  }
```

- [ ] **Step 4: 写后气泡挂头像**

`maybeCoachLearnLoop`(约 2432)构造 coach-pop 处,在气泡首部 `prepend(agentAvatar("领航员","jc-ava","jc-fallback"))`(24px,复用 .jc-ava)。

- [ ] **Step 5: 验证 + 提交**

Run: `node --check loom/webui/app.js && grep -c loom_journey_dismiss loom/webui/app.js && .venv/bin/python -m pytest -q`
Expected: 语法过;dismiss 键 0 命中;全量绿。

```bash
git add loom/webui/app.js
git commit -m "feat(webui): 门禁弹层退役转发enterNavCenter/织章_weaving隐身/S0→S2一次性交接+浮层自动开/写后气泡挂领航员头像"
```

---

### Task 4: 控制者 preview 六态冒烟(非子代理任务——控制者亲自做)

**说明:** 本任务由控制者在 preview(8792 demo,钉测试书)执行,逐态截图留证:
1. S0 新书:主区居中大卡(头像+还差N项+段条+问题卡),editor 隐藏;侧栏无旅程卡;
2. 「先自己逛逛」→ 球出现、居中让位、editor 回归;球点开 popover 有「继续答题」;
3. 点「写下一章」被拦 → **不弹 guide 弹层**,直接回居中 + 副标题高亮 + goto 首缺段;
4. 手工把测试书四项补齐(写文件)→ refresh → 交接动效(球 pulse + toast + popover 自动开一次;再刷新不重复);
5. S3:球静默;造「末章 edited 未 learn」态 → 朱点亮;focus-mode(⌘.)下球隐藏;
6. 织章(demo 后端)期间球隐身,写完回来。
发现问题记清单,一并派 fix 子代理。

---

### Task 5: 文档收口

**Files:**
- Modify: `CONTEXT.md`(「创作旅程(伙伴面板)」词条改口:侧栏卡→起书居中+悬浮球;dismiss 语义删除)
- Modify: `docs/使用教程.md`(「答题起书」小节按新形态改写:主区居中答题/右下领航员球/先自己逛逛)
- Modify: `docs/superpowers/specs/2026-07-10-journey-partner-design.md`(头部加一行修订指针:面板形态已被 2026-07-13 navigator-presence spec 修订)
- Create: `docs/design/proposals/navigator-avatar.md`(A 轨产出后补:提示词+seed+挑选记录——若 A 轨未完可先占位一行"待 A 轨定稿补")

- [ ] Step 1-3: 逐处按语义定位改写(先读现文);Step 4: `.venv/bin/python -m pytest -q` 全绿;Step 5: 提交 `docs(webui): 领航员形态文档收口——CONTEXT词条/教程答题起书/旧spec修订指针`。

---

## 计划自审记录

- **Spec 覆盖**:六态状态机(T2 navMode/T3 织章与交接)✓;居中态 in-flow 让位(T1 宿主+T2 openFile 让位+「先自己逛逛」)✓;悬浮球+未读点+popover(T1/T2)✓;dismiss 废弃四处(T2/T3)✓;门禁弹层退役转发(T3)✓;写后气泡挂头像(T3)✓;IP 头像=A 轨并行(agentAvatar 兜底,不阻塞)✓;文档(T5)✓;克制动效(T1 keyframes+T3 一次性)✓。
- **占位符**:无 TBD;代码块完整。app.js 行号为语义锚点(现场以 grep 定位)。
- **类型一致性**:`navMode()/journeyHost()/enterNavCenter(missing)/navUnread()` 在 T2 定义、T3 消费一致;`_navYield/_weaving/_navPopOpen` 三变量 enterProject 清零(T2 Step 1)。
- **风险**:paintJourney 参数化后三个 POST 回调仍无参调用 `paintJourney()` → host 函数动态求值,天然正确;popover 在 render 重画后按 `_navPopOpen` 恢复(T2 Step 3)。
