# 伙伴「执行活动视图」P1 实施计划(纯前端)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把伙伴对话里的工具执行从「静态两行(伙伴查了X + 裸结果块)」做厚成「跨轮累积、带标签、可展开的动作记录(看了地基 ▸)」,并修条件滚动。

**Architecture:** 纯前端。用一个无状态单遍配对扫描替换 `paintPartnerChat` 里的逐条 `map`,按**下一事件类型**(result/proposal)把 `tool` 与其结果配对成一行;新增 `partnerToolVerb` + 三个渲染 helper;抑制双「活着」指示器;滚动改 sticky-bottom。零后端、零新事件类型。

**Tech Stack:** 原生 JS(`loom/webui/app.js`,无框架、无 JS 单测设施)+ CSS(`loom/webui/style.css`)。

## Global Constraints

- **只碰** `loom/webui/app.js` + `loom/webui/style.css`。不碰任何 Python、不碰 Backend Protocol、不产新事件类型(spec §8)。
- **配对必须按下一事件的类型(result vs proposal)分派,绝不按工具名**(spec §4.2,评审 finding #2:提设定参数错走 `result(error)` 非 `proposal`,按工具名会渲染 `partnerConfirm(undefined)` 假候选卡)。
- **任何配不到 result/proposal 的 tool 都必有渲染分支(active 或 done),绝不消失**(spec §4.2 兜底,finding #7)。
- **无 JS 单测** → 验收走浏览器冒烟。**冒烟前必须把 `loom_root` 钉到 scratch 测试书**(预览与桌面共享 localStorage,autoReopen 会误开真书)。**绝不在真书上冒烟。**
- 旋转活动态**不是**验收必看项(spec §2:Loom 工具瞬时,常不显现);验收主看「累积的可读折叠记录」。
- 提交:`git add` 只加具体文件;Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>;不 push/不 merge。

## 文件结构

- `loom/webui/app.js`:新增 `partnerToolVerb`/`pcToolActive`/`pcToolDone`/`pcToolResult`/`renderPartnerEvents`;改 `paintPartnerChat`(扫描替换 map、双指示器抑制、sticky 滚动);删 `pcTool` + `renderPartnerEvent` 的 `case "tool"`。
- `loom/webui/style.css`:新增 `.pc-tool-active`/`.pc-spinner`/`@keyframes pc-spin`/`.pc-tool-done`。

---

### Task 1: 动词映射 + 三个渲染 helper + CSS

**Files:**
- Modify: `loom/webui/app.js`(在 `pcResult` 附近 ~1224 后新增函数;暂不接线,旧 map 仍生效 → 本任务零行为变化,是安全中间态)
- Modify: `loom/webui/style.css`(在 `.pc-result-text` ~667 后新增)

**Interfaces:**
- Produces:
  - `partnerToolVerb(name, params) -> {active: string, done: string, err: string}`
  - `pcToolActive(toolEv) -> HTMLElement`(活动行 + 旋转)
  - `pcToolDone(toolEv) -> HTMLElement`(静态 done 行,无展开)
  - `pcToolResult(toolEv, resultEv) -> HTMLElement`(合并折叠行,吸收 `pcResult` 的 `<details>` 骨架)

- [ ] **Step 1: 新增 `partnerToolVerb` + 三 helper**(app.js,`pcResult` 函数后)

```js
// 工具名 → 三态文案(spec §4.3)。〈basename〉取 params.路径 末段文件名。
// 每个工具每条路径都有定义,无 undefined:提设定成功走 proposal(tool 行被压)、
// 参数错走 result(error) 用 .err;done 仅极端边角兜底。
function partnerToolVerb(name, params) {
  const base = (params && params.路径) ? String(params.路径).split("/").pop() : "";
  switch (name) {
    case "看地基": return { active: "正在看地基…", done: "看了地基", err: "查地基没成功" };
    case "读文件": return { active: `正在读${base}…`, done: `读了${base}`, err: `读${base}没成功` };
    case "提设定": return { active: "正在拟一条设定…", done: "拟了一条设定", err: "拟设定没成功" };
    default: {
      const n = name || "工具";
      return { active: `正在用${n}…`, done: `用了${n}`, err: `用${n}没成功` };
    }
  }
}

// 活动行:旋转指示器 + 「正在看地基…」(spec §4.2 dangling+busy)
function pcToolActive(ev) {
  const row = document.createElement("div");
  row.className = "pc-tool-active";
  const spin = document.createElement("span");
  spin.className = "pc-spinner";
  row.appendChild(spin);
  const label = document.createElement("span");
  label.textContent = partnerToolVerb(ev.name, ev.params).active;
  row.appendChild(label);
  return row;
}

// 静态 done 行:轮末残留 / [tool,error] 兜底 / 非 busy(spec §4.2 后两档)
function pcToolDone(ev) {
  const row = document.createElement("div");
  row.className = "pc-tool-done";
  row.textContent = partnerToolVerb(ev.name, ev.params).done;
  return row;
}

// 合并折叠行:tool + 其 result 配一行(spec §4.2)。summary 用配对 tool 的 done/err 文案,
// 沿用 pcResult 的 .pc-result 折叠骨架 + .err 样式。
function pcToolResult(toolEv, resultEv) {
  const verb = partnerToolVerb(toolEv.name, toolEv.params);
  const det = document.createElement("details");
  det.className = "pc-result" + (resultEv.error ? " err" : "");
  const sum = document.createElement("summary");
  sum.textContent = resultEv.error ? verb.err : verb.done;
  det.appendChild(sum);
  const body = document.createElement("div");
  body.className = "pc-result-text";
  body.textContent = resultEv.error || resultEv.text || "";
  det.appendChild(body);
  return det;
}
```

- [ ] **Step 2: 新增 CSS**(style.css,`.pc-result-text` 行后 ~667)

```css
.pc-tool-active { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs);
  color: var(--text-mute); padding: 1px 4px; }
.pc-spinner { flex: none; width: 10px; height: 10px; border-radius: 50%;
  border: 1.5px solid var(--line); border-top-color: var(--text-soft);
  animation: pc-spin 0.7s linear infinite; }
@keyframes pc-spin { to { transform: rotate(360deg); } }
.pc-tool-done { font-size: var(--fs-xs); color: var(--text-soft); padding: 1px 4px; }
```
(全局 `prefers-reduced-motion`(style.css:919-922)已把 `animation-duration` 降 `.01ms`,旋转器自动降静态圆环,无需额外媒体查询。)

- [ ] **Step 3: 语法自检**

Run: `cd /Users/chambers/Desktop/Project/playground/Loom && node --check loom/webui/app.js`
Expected: 无输出(语法通过)。若无 node,用 `python3 -c "import esprima"` 不可行则跳过,靠浏览器控制台在 Task 3 验。

- [ ] **Step 4: Commit**

```bash
git add loom/webui/app.js loom/webui/style.css
git commit -m "feat(partner): 加动作层渲染helper——partnerToolVerb+活动/完成/折叠行+旋转CSS(未接线)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 单遍配对扫描接线 + 删 pcTool + 双指示器抑制

**Files:**
- Modify: `loom/webui/app.js`:`paintPartnerChat`(~1099-1132)、`renderPartnerEvent`(~1173-1186,删 `case "tool"`)、删 `pcTool`(~1203-1211)

**Interfaces:**
- Consumes: Task 1 的 `pcToolActive`/`pcToolDone`/`pcToolResult`;既有 `renderPartnerEvent`(非 tool 事件)、`_partnerBusy`、`PARTNER.events`
- Produces: `renderPartnerEvents(events) -> HTMLElement[]`

- [ ] **Step 1: 确认 `renderPartnerEvent`/`pcTool` 无其它调用方**

Run: `cd /Users/chambers/Desktop/Project/playground/Loom && grep -n "renderPartnerEvent\|pcTool\b" loom/webui/app.js`
Expected: `renderPartnerEvent` 仅在 `paintPartnerChat`(将被替换的 map)出现;`pcTool`(词界,非 pcToolX)仅定义处 + `renderPartnerEvent` 的 case 出现。若有别的调用方,停下来重新评估。

- [ ] **Step 2: 新增 `renderPartnerEvents` 单遍扫描**(app.js,`renderPartnerEvent` 函数前)

```js
// 单遍配对扫描(spec §4.2):tool 按【下一事件类型】配对——绝不按工具名,
// 否则提设定 result(error) 会被当 proposal 渲染成假候选卡(评审 finding #2)。
// 任何配不到 result/proposal 的 tool 都落 active 或 done,绝不消失(finding #7)。
function renderPartnerEvents(events) {
  const out = [];
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    if (ev && ev.t === "tool") {
      const next = events[i + 1];
      if (next && next.t === "result") {
        out.push(pcToolResult(ev, next));
        i++;                                  // 连同 result 一起消费
        continue;
      }
      if (next && next.t === "proposal") {
        continue;                             // 压掉 tool 行;proposal 下一轮迭代自渲染
      }
      if (i === events.length - 1 && _partnerBusy) {
        out.push(pcToolActive(ev));           // 末尾 + busy → 活动行
      } else {
        out.push(pcToolDone(ev));             // 轮末残留 / [tool,error] / 非 busy → 静态 done
      }
      continue;
    }
    const el = renderPartnerEvent(ev);
    if (el) out.push(el);
  }
  return out;
}
```

- [ ] **Step 3: `paintPartnerChat` 用扫描替换 map**(app.js:1114)

把:
```js
    const rendered = (PARTNER.events || []).map(renderPartnerEvent).filter(Boolean);
```
改为:
```js
    const rendered = renderPartnerEvents(PARTNER.events || []);
```

- [ ] **Step 4: 双指示器抑制**(app.js:1124-1132,spec §4.4 / finding #3)

把:
```js
  if (_partnerBusy) {
    if (_partnerDelta) scroll.appendChild(pcBubble("assistant", _partnerDelta, true));
    else {
      const think = document.createElement("div");
      think.className = "pc-thinking";
      think.textContent = "伙伴在想…";
      scroll.appendChild(think);
    }
  }
```
改为:
```js
  if (_partnerBusy) {
    // 末尾事件是 tool ⟺ dangling(已被扫描渲染成活动行,它本身即 busy 指示器)——
    // 此时不再叠通用「伙伴在想…」,免双指示器(spec §4.4)。
    const evs = (PARTNER && PARTNER.events) || [];
    const danglingTool = evs.length > 0 && evs[evs.length - 1].t === "tool";
    if (_partnerDelta) scroll.appendChild(pcBubble("assistant", _partnerDelta, true));
    else if (!danglingTool) {
      const think = document.createElement("div");
      think.className = "pc-thinking";
      think.textContent = "伙伴在想…";
      scroll.appendChild(think);
    }
  }
```

- [ ] **Step 5: 删 `renderPartnerEvent` 的 `case "tool"` + 删 `pcTool` 函数**

`renderPartnerEvent`(~1180)删掉这一行:
```js
    case "tool": return pcTool(ev);
```
并整段删除 `pcTool` 函数定义(~1203-1211):
```js
function pcTool(ev) {
  const row = document.createElement("div");
  row.className = "pc-tool";
  const params = ev.params || {};
  const paramTxt = Object.keys(params).length
    ? "(" + Object.entries(params).map(([k, v]) => `${k}:${v}`).join(" · ") + ")" : "";
  row.textContent = `伙伴查了${ev.name || "工具"}${paramTxt}`;
  return row;
}
```
(扫描已在 renderPartnerEvent 之前拦截所有 tool 事件,故 case 与 pcTool 皆死代码。)

- [ ] **Step 6: 语法自检**

Run: `cd /Users/chambers/Desktop/Project/playground/Loom && node --check loom/webui/app.js`
Expected: 无输出。

- [ ] **Step 7: Commit**

```bash
git add loom/webui/app.js
git commit -m "feat(partner): 单遍配对扫描接线——tool按事件类型配result/proposal+删pcTool+抑双指示器

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 条件滚动(sticky-bottom)

**Files:**
- Modify: `loom/webui/app.js`:`paintPartnerChat`(开头抓旧滚动量;结尾 ~1170 改条件滚动)

**Interfaces:**
- Consumes: 既有 `journeyHost()`、`.pc-scroll` 容器

- [ ] **Step 1: `paintPartnerChat` 开头抓旧滚动位置**(app.js,`card.innerHTML = ""` 之前,~1101)

在 `card.innerHTML = "";` 前插入:
```js
  // sticky-bottom(spec §5):重画前量旧容器是否贴底 + 当前位置,重画后据此决定滚动。
  const oldScroll = card.querySelector(".pc-scroll");
  let stickBottom = true, prevTop = 0;
  if (oldScroll) {
    prevTop = oldScroll.scrollTop;
    stickBottom = (oldScroll.scrollHeight - oldScroll.scrollTop - oldScroll.clientHeight) < 40;
  }
```

- [ ] **Step 2: 结尾条件滚动**(app.js:1170)

把:
```js
  scroll.scrollTop = scroll.scrollHeight;
```
改为:
```js
  // 贴底则跟读到底,否则维持作者停留位置(不被新事件拽走,spec §5)
  scroll.scrollTop = stickBottom ? scroll.scrollHeight : prevTop;
```

- [ ] **Step 3: 语法自检**

Run: `cd /Users/chambers/Desktop/Project/playground/Loom && node --check loom/webui/app.js`
Expected: 无输出。

- [ ] **Step 4: Commit**

```bash
git add loom/webui/app.js
git commit -m "feat(partner): 条件滚动sticky-bottom——贴底才跟读,翻看早前结果不被拽回底

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 全量回归 + 浏览器冒烟验收

**Files:** 无(验证任务)

- [ ] **Step 1: Python 全量回归**(前端改动不应碰 Python,跑一遍确认没误伤)

Run: `cd /Users/chambers/Desktop/Project/playground/Loom && python -m pytest -q 2>&1 | tail -20`
Expected: 全绿(与改动前同数量,542+)。

- [ ] **Step 2: 起 scratch 测试书 + 钉 loom_root**

**关键安全步骤**:准备一本 scratch 测试书(非真书),把预览的 `loom_root` 钉到它,防 autoReopen 误开真书。用既有 demo/离线书或在 scratchpad 建一本最小书。起 dev server(preview_start,名字见 `.claude/launch.json`),导航到伙伴对话面板。

- [ ] **Step 3: 冒烟——动作记录累积 + 折叠**

跟伙伴发一条会触发工具的话(如「帮我看看现在该定什么」引出「看地基」)。验:
- 多轮里出现「看了地基 ▸」「读了X ▸」等**折叠行**,点开能看明细;
- 记录**逐条累积**(不是一次性刷没);
- busy 期只有**一个**「活着」指示器(旋转活动行 或「伙伴在想…」,不并存)。
用 read_page / read_console_messages 确认无 JS 报错。

- [ ] **Step 4: 冒烟——提设定不出假卡**

触发一次「提设定」。验:成功 → 出**候选卡**(虚线+「候选」角标),**无**「伙伴查了提设定」噪声行;若构造参数错场景(可选),出「拟设定没成功 ▸」而**非** `partnerConfirm(undefined)` 空卡。

- [ ] **Step 5: 冒烟——条件滚动**

对话内容超过一屏后,往上翻;此时发新消息 / 等新事件。验:**不被拽回底部**;贴底时新事件正常跟读到底。

- [ ] **Step 6: 截图留证 + 收尾**

computer screenshot 存证。记录冒烟结果。此任务不改代码,无 commit(若冒烟发现 bug,回对应 Task 修复再验)。

---

## Self-Review

**Spec coverage**(对 spec §4-§9):
- §4.2 配对表(result/proposal/active/done/兜底)→ Task 2 Step 2 `renderPartnerEvents` 全覆盖 ✓
- §4.3 动词映射 → Task 1 `partnerToolVerb` ✓
- §4.4 双指示器抑制 → Task 2 Step 4 ✓
- §4.5 落点(helper + 删 pcTool)→ Task 1 + Task 2 Step 5 ✓
- §5 条件滚动 → Task 3 ✓
- §4.6/§6 零新事件/零后端/幂等 → 全程只碰 app.js+css ✓
- §9 测试(pytest 回归 + loom_root 钉 scratch 冒烟)→ Task 4 ✓

**Placeholder scan:** 无 TBD/TODO;每步有完整代码或确切命令 ✓

**Type consistency:** `partnerToolVerb` 返回 `{active,done,err}` 在 `pcToolActive/pcToolDone/pcToolResult` 三处用法一致;`renderPartnerEvents(events)->HTMLElement[]` 与 `paintPartnerChat` 消费点一致;删 `pcTool` 后 `renderPartnerEvent` 不再引用它 ✓
