# 伙伴对话「执行活动视图」设计(P1 + P1.5)

> 状态:已过两轮对抗式评审(架构 run wf_00e0ee7e-9e1;spec run wf_67a0c5b2-033,1 blocker + 5 important + 2 minor 全部对真码坐实并已并入本文)+ 设计定稿。
>
> **分期**:**P1** = 动作层做厚 + 条件滚动(纯前端,零后端,零竞态风险,先发)。**P1.5** = 停(碰数据完整性,单独做,含归档锁门禁修复)。**v2** = 思考层。
>
> **实现状态(2026-07-18)**:P1 + P1.5 + **v2 思考层均已实现**,各自真机验 + 对抗式审通过并提交(分支 `navigator-reliability-p1`,未合)。v2 为 DeepSeek-only(reasoning_content 独立字段)、transient 不落盘;BYOK `<think>` 内联兜底(§11)留待接入那些供应商时补。

## 1. 背景与痛点

书房伙伴(领航员)现在的对话是「单轮阻塞」体验:作者发一条消息后,输入框整段禁用(`_partnerBusy`,T5 反并发锁引入),只能干等,**看不到伙伴正在干什么、也点不了下一步**。作者原话:「每次选择了一个内容之后就等着 agent 给回复,点下一个问题也点不了。」

拆成两个痛点:
- **P-盲**:等待期看不到 agent 在干嘛(在查什么?查到什么?)。→ **P1 治**(以「累积的可读记录」形式,见 §2 的诚实重估)。
- **P-锁**:整轮期间被锁死,想停也停不了。→ **P1.5 给逃生口**(「停」,非真排队);**真排队**是更后面的事。

## 2. 目标 / 非目标

**P1 目标**
- 治 P-盲:把现在的「伙伴查了X」噪声行 + 裸结果块,收成**跨轮累积、带标签、可展开的「看了什么」记录**(「看了地基 ▸」点开看明细)。多轮对话里作者能看到记录一条条累积。
- 顺手修既有小病:滚动被无条件拽到底,往上翻看早前结果会被下一个事件打断。

**P1 价值的诚实重估(评审 finding #6,已坐实)**
- Loom 的三个工具**全是亚知觉的本地瞬时操作**(看地基=内存扫槽 partner_tools.py:102;读文件=本地读盘;提设定=内存拼卡),`run_turn` 把 `tool` 与 `result` **背靠背同步 emit**(partner.py:169→172,中间只一次瞬时 `run_tool`)。因此「正在看地基…」旋转活动态**只存在几微秒、常在同一 reader 批次里就被 result 替换,基本看不到**。
- 真正有知觉的等待是 `backend.complete()` 生成——那一刻末尾事件是 user/result,渲染成通用「伙伴在想…」,**不是**工具专属活动行。
- 所以 P1 交付的**不是** Claude Code 式「live 工具流」(Loom 工具瞬时,没这回事),而是「**累积的、可读的、可回看的动作记录**」。旋转指示器是**廉价的锦上添花**(几乎不显现,但为未来可能的慢工具留着,成本极低),**不当作主卖点、不在验收里要求必须看见**。

**非目标(明确不做)**
- ❌ **思考层(reasoning 流)**:降 v2,见 §10。
- ❌ **live 每秒跳计时器**:唯一逼出增量 DOM 重构的诉求;CSS 旋转已足够。砍。
- ❌ **增量 DOM 渲染重构**:上一条砍了就不必做;P1 事件率与今天一致(逐行/逐工具,非逐 token),保留现有全量重画。
- ❌ **非阻塞排队**(边等边发下一条):P1/P1.5 仍单轮串行;P1.5 的「停」是逃生口不是排队。真排队是独立决策,更后面。
- ❌ **P1 不含「停」**:停碰数据完整性(§9 blocker),拆 P1.5。

## 3. 范围裁决依据

架构评审把「五后端签名 + Protocol + 循环 + server + 前端」纵切和痛点治疗绑成一个包,是原设计最大的问题。盯真码后:

1. **动作层做厚是纯前端、零后端**——`tool`/`result` 事件已在 `partner.py:169/172` emit、`app.js:1203/1213` 已在渲染,只是做薄了。做厚=换渲染逻辑,不产新事件、不动后端。
2. **tool↔result 配对可在每次重画时无状态扫一遍事件列表算出**,不需跨事件存活的 DOM,故不需增量重构。
3. **「停」是唯一动后端、且唯一碰数据完整性的一块**:它让 `_partnerBusy`(前端)与 worker 存活解耦,重开归档-写入竞态(§9)。故拆 P1.5 单独稳做。

于是:**P1 = ①动作层做厚 + ②条件滚动**(纯前端);**P1.5 = ③停**(前端 abort + 后端归档锁门禁 + 生命周期 + 真机冒烟)。全程不碰 `backends.py`/Backend Protocol/12+ 测试替身。

---

# P1(先发,纯前端)

## 4. ① 动作层做厚

### 4.1 现状

`paintPartnerChat()`(app.js:1099)把 `PARTNER.events` **逐条独立** map:`tool`→`pcTool`(app.js:1203,死行「伙伴查了X」)、`result`→`pcResult`(app.js:1213,独立折叠块)、`proposal`→`pcProposal`(候选卡)。tool 与 result 互不认识,看不出「这个结果是那个查询的」。

真实 emit(来自 `run_turn`/`partner_tools`):读类工具(看地基/读文件)→ `{t:tool}` 紧跟 `{t:result,text|error}`;`提设定` **成功**→ `{t:tool}` 紧跟 `{t:proposal,id,slot,content,before}`,**失败(参数错)**→ `{t:tool}` 紧跟 `{t:result,error}`(partner_tools.py:185-192,mutates 工具的 try/except 在参数问题时先返回 result-error,走不到 proposal)。

### 4.2 目标渲染:单遍配对扫描,**按下一事件类型分派**(不按工具名)

用无状态单遍扫描替换现有 `(PARTNER.events||[]).map(renderPartnerEvent).filter(Boolean)`。扫到 `tool`(索引 i)时看 `event[i+1]` 的**类型**决定(评审 finding #2:必须按事件类型判,不能按工具名判,否则提设定错误路径会把 result-error 当 proposal 喂给 `pcProposal`,渲染出 `partnerConfirm(undefined)` 的空假候选卡——正撞项目一直在防的「假候选卡」):

| `event[i+1]` 类型 | 渲染 | 消费 |
|---|---|---|
| `result`(无 error) | **合并折叠行**,summary=`partnerToolVerb(name,params).done`(如「看了地基 ▸」),body=`result.text` | i+=2 |
| `result`(有 error) | **合并折叠行**,summary=`.err`(如「查地基没成功」「拟设定没成功」)+ 现有 `.err` 样式,body=`result.error` | i+=2 |
| `proposal` | **压掉 tool 行**,让 `proposal` 走自己的 `pcProposal`(候选卡自解释) | i+=1(proposal 下一轮迭代自渲染) |
| 无下一事件 且 `_partnerBusy` | **活动行**:`.active`(如「正在看地基…」)+ CSS 旋转 | i+=1 |
| 无下一事件 且 **非** busy | **静态 done 行**:`.done`,不展开(轮末残留/崩溃) | i+=1 |
| 其它类型(如其后是 `error`/`assistant`/`user`——真连接中断可致 `[..,tool,error]`,评审 finding #7) | **兜底静态 done 行**(不让配不上的 tool 行凭空消失,否则作者只看到 error、丢了正在跑的工具) | i+=1 |
| (非 tool 事件) | 走现有 `renderPartnerEvent`(user/assistant/proposal/error) | i+=1 |

**要点**:除 `proposal` 压掉 tool 行外,**任何配不到 result/proposal 的 tool 都必有一个渲染分支**(active 或 done),绝不消失。

### 4.3 动词映射 `partnerToolVerb(name, params)`

单一来源,返回 `{active, done, err}`:

| 工具 | active | done | err |
|---|---|---|---|
| `看地基` | 正在看地基… | 看了地基 | 查地基没成功 |
| `读文件` | 正在读〈basename〉… | 读了〈basename〉 | 读〈basename〉没成功 |
| `提设定` | 正在拟一条设定… | 拟了一条设定 | 拟设定没成功 |
| 未知/未来工具 | 正在用〈name〉… | 用了〈name〉 | 用〈name〉没成功 |

`〈basename〉` = `params.路径` 末段文件名(去目录)。注:`提设定` 成功走 proposal(tool 行被压),其 `done` 仅在极端边角(提设定+result 无 error,现实不产)兜底存在;`提设定` 的 `err` 则在参数错(result-error)时真用到——**所以每个工具的每条路径都有定义文案,无 `undefined`**(评审 finding #2)。

### 4.4 双指示器抑制(评审 finding #3)

现有 `paintPartnerChat` 在渲染完事件后,只要 `_partnerBusy` 且 `_partnerDelta` 空,就**无条件**再追加一条通用「伙伴在想…」块(app.js:1124-1132)。而「tool 末尾 + busy」时,§4.2 已渲染「正在看地基…」活动行,通用块会**再叠一条**,两个「活着」指示器并存。

**修法**:通用「伙伴在想…」块只在 `_partnerBusy` 且**末尾事件不是 dangling tool**(即 `events[last]?.t !== "tool"`)时才追加——末尾是 tool 时,活动行本身即 busy 指示器。`_partnerDelta` 非空的流式气泡分支不受影响(有 delta 说明末尾在流 assistant,非 dangling tool)。

### 4.5 实现落点(前端)

- `paintPartnerChat()`(app.js:1099):§4.2 单遍配对扫描替换独立 map;§4.4 通用 busy 块加条件。
- 新增 `pcToolResult(toolEv, resultEv)`:合并折叠行(吸收现有 `pcResult` 的 `<details>` 骨架,summary 用 §4.3 done/err 文案,err 沿用 `.err` 样式)。
- 新增 `pcToolActive(toolEv)` / `pcToolDone(toolEv)`:活动行(CSS 旋转)/ 静态 done 行(§4.2 后三档兜底)。
- 新增 `partnerToolVerb(name, params)`:§4.3 单一实现。
- `pcTool`(app.js:1203 旧死行):新扫描下不再被调用,删除(§4.2 兜底已覆盖旧 pcTool 的所有情形,不留双份文案)。
- CSS:`.pc-tool-active`(旋转,尊重 `prefers-reduced-motion` → 减弱时降静态圆点)、`.pc-tool-done`。

### 4.6 关键性质

- **零新事件类型、零后端改动。** 配对全在渲染层,数据仍是既有 `tool`/`result`/`proposal`。
- **无状态、幂等。** 每次重画从完整事件列表重算,刷新/换书/归档后一致。

## 5. ② 条件滚动

现状:`paintPartnerChat()` 末尾无条件 `scroll.scrollTop = scroll.scrollHeight`(app.js:1170),往上翻看早前结果会被下一个事件拽回底部。

改法(sticky-bottom):**重画前**读旧 scroll 容器,量是否贴底(`scrollHeight - scrollTop - clientHeight < 40px`)与当前 `scrollTop`;**重画后**——贴底则滚到底,否则还原到重画前 `scrollTop`。全量重画也能做(抓旧容器量、设新容器)。首帧(旧容器不存在)按贴底处理。

## 6. P1 数据流与不变量

- **P1 不引入任何新事件类型、零后端改动。**
- **「busy === worker 存活」不变量完整保留**:P1 无「停」,`_partnerBusy` 仍持续到流结束(worker 完成),与今天完全一致 → **P1 无任何数据完整性风险**,归档门禁仍靠 `_partnerBusy`(app.js:1165/1359)即安全。
- 落盘语义、轮锁语义均不变。

## 7. P1 错误处理

- 工具 err 结果(`result.error`):§4.2 走 `.err` 文案 + 现有 `.err` 样式,body 显示错误文本。
- 真连接中断:维持现有「连接中断:…」error 事件;若落在 tool 与 result 间致 `[..,tool,error]`,§4.2 兜底行保住正在跑的工具行(finding #7)。

## 8. P1 文件改动面

| 文件 | 改动 |
|---|---|
| `loom/webui/app.js` | §4 单遍配对扫描 + `pcToolResult`/`pcToolActive`/`pcToolDone`/`partnerToolVerb` + 删 `pcTool` + §4.4 通用 busy 块加条件;§5 sticky-bottom |
| `loom/webui/*.css` | `.pc-tool-active`(旋转,尊重 `prefers-reduced-motion`)、`.pc-tool-done` |

**P1 不碰**:`backends.py`、Backend Protocol、`server.py`、`partner.py`、`partner_tools.py`、`partner_context.py`、`partner_store.py`、`usecases.py`、任何测试替身。

## 9. P1 测试策略

**无 JS 单测设施 → 浏览器冒烟**
- 冒烟前**必须**把 `loom_root` 钉到 scratch 测试书(预览与桌面共享 localStorage,autoReopen 会误开真书——既有教训)。**绝不在真书上冒烟。**
- 验:发一条 → 多轮里看到「看了地基 ▸」「读了X ▸」记录**逐条累积、可展开**;`提设定` 只出候选卡、不出工具噪声行;`提设定` 参数错时出「拟设定没成功 ▸」而**非**空假候选卡;busy 期只有一个「活着」指示器(无双叠);往上翻看时新事件不拽回底部。
- 旋转活动态**不列为必看项**(§2:工具瞬时,常不显现)。

---

# P1.5(停,单独稳做)

> 停让 `_partnerBusy`(前端)与 worker 存活**解耦**,因此(a)重开归档-写入竞态,必须服务端补门禁;(b)需自己的生命周期与真机冒烟。故拆出单做。

## 10.1 前端

- 模块级 `_partnerAbort`(AbortController|null)。`partnerSay()` 建 `ctrl`,fetch 传 `signal: ctrl.signal`。
- **区分「用户停」与「真出错」**:reader 抛错时若 `ctrl.signal.aborted`(或 `e.name==="AbortError"`)→ 干净停止,**不**追加 error 事件;否则维持现有错误处理。
- `finally` 沿用 `_partnerGen` 世代守卫清 `_partnerBusy`/`_partnerDelta` → 立刻拿回输入框。
- **停止键**:`_partnerBusy` 时把「发送」换/并出「停止」键,`onclick=()=>_partnerAbort&&_partnerAbort.abort()`。
- **停止反馈** `_partnerStopped`(模块级布尔):abort 置 true,渲染时对话流尾出一条 muted「· 已停止 ·」(纯客户端,不落盘、不产事件)。**清零点必须枚举齐全**(评审 finding #4:否则漏到别的书/新会话):`partnerSay` 开头、换书 `enterProject`(app.js:480)、另起 `partnerNewThread`(app.js:1365)三处都清——镜像 `_partnerGen`/`_partnerBusy` 的生命周期。

## 10.2 后端:归档锁门禁(修 blocker)

**Blocker(评审坐实)**:停在 abort 时提前清 `_partnerBusy`,但 worker 还在写 jsonl 尾巴到下一轮边界;而 `partner_new`(归档)走**写锁**(usecases.py:462)**不是 partner 轮锁**——归档不被轮锁挡。时序:abort→busy 清→点「另起」→`archive_current` 改名 `当前.jsonl`→还在飞的 worker `_persist` 重建一个**没有 user 事件的孤儿** `当前.jsonl`→「旧轮尾巴串进新会话」(app.js:1165/1359 注释发誓禁止)。

**修法**:`partner_new` 归档前先 `try_partner_lock(root)`(usecases.py:100 现成,非阻塞);worker 还持轮锁(say 未收尾)→ 抛 `ProjectBusyError(code="partner_busy")` → 409「伙伴还在收尾,稍等再另起」;拿到则持轮锁跨整个归档、`finally` 释放:

```python
def partner_new(root, *, stamp):
    guard = try_partner_lock(root)          # 非阻塞;worker 持锁 → None
    if guard is None:
        raise ProjectBusyError(PARTNER_BUSY_MESSAGE, code="partner_busy")
    try:
        with write_lock(root):
            ... 现有归档逻辑 ...
    finally:
        guard.release()
```

把「busy 不再等于 worker 活着」的裂缝在**服务端**补上——abort 后前端已失去知道 worker 何时收尾的通道,唯一稳的判据是服务端轮锁。无死锁循环:say worker 只持轮锁;partner_new 持轮锁→写锁;无「写锁→轮锁」路径。前端 `partnerNewThread` 的 409 分支复用现有 `codeHint`/toast(app.js:1040 路径)。

## 10.3 后端:轮内取消

- `run_turn` 加可选形参 `should_cancel: Callable[[], bool] | None = None`(默认 None → 行为逐字不变,demo/CLI/旧测试替身不受影响)。
- `while True`(partner.py:152)**顶部**检查:`if should_cancel and should_cancel(): return`。取消在**轮边界**生效——正跑的 `backend.complete()`(一次生成)跑完、当前轮工具(若有)可能执行,然后下一次 `complete()` 前 return。不把取消穿进流式循环(不碰 Protocol)。
- server `partner_say`:`cancel = threading.Event()`,传 `should_cancel=cancel.is_set`,`stream()` 的 `finally` 里 `cancel.set()`(客户端断连/流关闭 → worker 下一轮边界停 → worker `finally` 放轮锁)。

## 10.4 取消促发性(评审 finding #8,诚实口径)

`cancel.set()` 在 ≤ **一次生成**内触发,不是瞬间:
- **流式后端**(OpenAICompat/DeepSeek):`assistant_delta` 频繁流出、频繁解阻 `q.get()`,断连后**下一个 delta**(亚秒级)即触发。
- **非流式 CLI 后端**(claude/codex,无 key 主通道):生成期死空(subprocess 整段返回),sync `stream()` 阻塞在 `q.get()`,`GeneratorExit` 要等 `q.get()` 解阻 → **~一次完整生成后**才触发。

**代价记账**:轮锁在 ≤ 一次生成内释放。这窗口内立刻重发/另起 → 撞干净 409 `partner_busy`(重发走 `acquire_partner_lock` 现有;另起走 §10.2 新门禁)。非死锁:worker `finally` 无条件放锁(server.py:727-729),`run_turn` 受 `_MAX_TOOL_ROUNDS=6` 上界。**停是逃生口(轮边界),不是排队。**

## 10.5 GeneratorExit 时机(实现风险点)

sync 生成器的 `finally` 依赖生成器被关闭时 `GeneratorExit` 投递。若实测不可靠(Starlette 对 sync 流式生成器的断连取消不如 async 及时),**回退方案**:显式 `POST /api/partner/stop`,server 维护 `{root: threading.Event}` 注册表,stop 端点查表置旗——确定性、易测,但引入模块级共享态。**P1.5 先走 §10.3 断连方案;冒烟发现锁不释放再切回退。** 单列为已知实现风险。

## 10.6 P1.5 测试策略(评审 finding #5,修正不实断言)

- `tests/test_partner_loop.py`:`should_cancel` 恒 True → 首轮顶即 return(`complete` 调用次数 ≤1);恒 False/None → 行为与今逐字一致(现有多轮闭环仍绿);第 N 轮翻 True → 第 N+1 轮不再 `complete`。
- `tests/test_partner_usecases.py`(或 endpoints):**worker 持轮锁时 `partner_new` 抛 `partner_busy` 409**(§10.2 门禁);轮锁空闲时正常归档。这条**能**离线真测(直接持 `try_partner_lock` 再调 `partner_new`)。
- **不**声称离线 pytest 能验「GeneratorExit→锁释放」:TestClient 不可靠触发 GeneratorExit,且假后端下 run_turn 自行跑完放锁,绿了证明不了 cancel。断连路径**只走真机冒烟**;pytest 只验 wiring(monkeypatch `run_turn` 断言收到的 `should_cancel is cancel.is_set`)。
- 全量回归 542+ 保持绿。

## 10.7 P1.5 文件改动面

| 文件 | 改动 |
|---|---|
| `loom/webui/app.js` | `_partnerAbort` + fetch signal + abort 分辨 + 停止键 + `_partnerStopped`(三处清零)+ 另起 409 提示 |
| `loom/webui/*.css` | 「· 已停止 ·」样式 |
| `loom/partner.py` | `run_turn` 加 `should_cancel=None` + while 顶检查 |
| `loom/server.py` | `partner_say` 加 `cancel` Event、传 `should_cancel`、`stream()` finally `cancel.set()` |
| `loom/usecases.py` | `partner_new` 加 `try_partner_lock` 门禁(§10.2) |

**P1.5 不碰**:`backends.py`、Backend Protocol、`partner_tools.py`、`partner_context.py`、`partner_store.py`、测试替身签名。

---

## 11. 明确降 v2:思考层

记录以便 v2 直接接手,P1/P1.5 不做:
- **形态**:后端 `on_reasoning` 回调(读 `getattr(delta, "reasoning_content", None)`,**不能**直接取属性否则 `AttributeError`;且须放在 `if not delta: continue` 之**前**,否则纯 reasoning 帧被吞)读 DeepSeek 思维链 → `run_turn` emit `{"t":"reasoning_delta"}` → 前端 inline 灰字折叠。
- **不进 Protocol**:复用 `partner.py:33` 的 `_accepts_agent_mode` 内省套路,只对声明了 `on_reasoning` 的后端传;CLI/demo 优雅退化。
- **BYOK `<think>` 兜底**:硅基流动/豆包/通义常托管 R1/QwQ,把思考内联进 `delta.content`(非独立字段)→ `on_reasoning` 永不触发,CoT 会灌进对话气泡并落盘 assistant(**倒退**)。v2 需在 content 通道剥 `<think>…</think>` 路由到 reasoning。**动手前先对每个 advertised 供应商抓一次真实 stream delta 形状。**
- **落盘裁决**:`reasoning_delta`(逐 token)**不进 jsonl**(与 `assistant_delta` 同性质,落盘撑大归档且污染 assemble 回喂)。若要持久折叠块,须轮末落一条收敛后的 authoritative `reasoning` 事件(只落一次:秒数+全文),否则折叠块轮末即蒸发。倾向:接受纯瞬态、不落盘,文档记「刷新后思考摘要不回显」是有意取舍。
- **CLI 地板**:体验最差的 CLI 后端既无 reasoning 也忽略 `on_chunk`,思考层惠及不到;其地板就是现有「伙伴在想…」+ 工具轮记录(P1 已覆盖)。

## 12. 分期总览

| 期 | 内容 | 改动面 | 风险 |
|---|---|---|---|
| **P1** | ①动作层做厚 + ②条件滚动 | 纯前端(app.js + css) | 零(busy===worker 不变量保留) |
| **P1.5** | ③停(前端 abort + 归档锁门禁 + 轮内取消) | app.js + server.py + partner.py + usecases.py | 中(碰数据完整性,门禁修复 + 真机冒烟) |
| **v2** | 思考层(§11) | 纵切多后端 | 高(Protocol + BYOK `<think>`) |
| **v3?** | 非阻塞排队 / 中途打断生成 | Protocol | 独立决策 |
