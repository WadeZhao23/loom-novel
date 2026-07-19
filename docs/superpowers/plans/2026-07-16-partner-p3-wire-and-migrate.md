# 书房伙伴 P3:接线与迁移(服务端 + 前端 + 红线改写)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。

**Goal:** 把 P1(槽位/落盘)+ P2(对话循环)接成能真机用的书房伙伴:服务端 `/api/partner/*` 端点(流式 say + 拍板 confirm)、demo 罐头多轮、CLI 护栏伙伴变体、前端对话 UI、红线文档改写(ADR 0015/0014 + 领航员.md + CONTEXT)。

**Architecture:** say 端点复刻 `/api/write` 的 ndjson 流式 + worker 线程,但用**独立 partner 轮锁**(不碰书写锁,织章期间可聊);confirm/new 走 `write_lock`。confirm 从 jsonl 读 proposal(find_proposal)→ 调 P1 的 `_land_slot` 落盘。前端对话 UI 复用现有 ndjson 流式消费。

**Tech Stack:** Python 3.11 + pytest(现 507 绿)+ 前端 vanilla JS(无测试框架,靠浏览器 preview 验证)。

**设计权威:**〔[书房伙伴设计](../specs/2026-07-16-navigator-agent-design.md)〕§2/§6/§8/§10/§13。P1+P2 是地基。

## Global Constraints

- **锁裁量**(spec §10 critical):say **完全不碰书写锁**——轮内读书文件无锁纯读、追加 jsonl 只拿独立 per-root 伙伴轮锁(非阻塞→409 `partner_busy`);confirm/new 走真 `write_lock`。织章期间对话可聊、只有拍板落盘要等。
- **拍板才落盘**:say 里的 `提设定` 只产 proposal 事件不落盘;唯一落盘出口是 confirm → `_land_slot`(P1)。
- **红线改写**(spec §13):领航员.md 删「绝不发明设定」保留「绝不替作者做决定」+ 补候选卡纪律;ADR 0014 立项红线改「走作者拍板通道」;ADR 0015 新建;CONTEXT 四处。**命名公约**:盘上/角色 `领航员`(不改名)、UI 称「伙伴」、代码/API `partner`。
- **卡片机退役是本计划最后一步且需用户在场验证 UI**——前端对话 UI 先与卡片机并存、控制者浏览器验证通过后,**卡片机代码删除留给用户醒后确认**(不 bulldoze,irreversible UI 变更不盲提交)。
- **替代测试先行**:任何 journey 出题/落盘的退役,新测试网(P1 的 test_land_slot + P2 的 test_partner_*)必须已绿才许删旧。
- 既有测试红了=禁改断言(尤其 12 条 land 测试、journey/parse 测试)。
- 提交 `type(scope): 中文摘要` + Co-Authored-By;`git add` 只加本任务文件,绝不 `-A`。

---

### Task 1: usecases partner 层 + confirm 落盘

**Files:**
- Modify: `loom/usecases.py`(加 partner_say/partner_confirm/partner_new/partner_history)
- Test: `tests/test_partner_usecases.py`

**Interfaces:**
```python
def partner_history(root) -> dict          # 纯读,无锁:{events: [...]}(尾部)
def partner_confirm(root, pid, *, ts) -> dict   # write_lock;find_proposal → _land_slot → append confirm 事件 → {landed, state}
def partner_new(root, *, stamp) -> dict     # write_lock;archive_current → {ok}
# say 在 server 层直接驱动 run_turn(流式),不经 usecases 包一层(同 /api/write 在 server 内建 worker)
```

**背景:** confirm 幂等(jsonl 已有该 id 的 confirm → 返已落盘结果不二次写);proposal 过期(find_proposal 返 None → 「提案已过期,重新问」);落点现状与 proposal 快照不符(作者手改了)→ 拒绝落盘告知(改文件即分叉)。

- [ ] Step 1-4: TDD——测 confirm 落对(调 _land_slot 落进 slot)、幂等(重复 confirm 不二次写)、过期(未知 id 报错)、new 归档、history 纯读。实现 usecases 四函数(confirm 用 `write_lock` + `partner_store.find_proposal` + `journey._land_slot` + append confirm 事件)。
- [ ] Step 5: Commit `feat(partner): usecases confirm落盘(find_proposal→_land_slot幂等)/new归档/history纯读`

---

### Task 2: 服务端 `/api/partner/*` 端点(流式 say + 锁裁量)

**Files:**
- Modify: `loom/server.py`(加 4 端点 + PartnerSayBody/PartnerConfirmBody + partner 轮锁 + partner_busy 409)
- Modify: `loom/usecases.py`(加 `try_partner_lock`/`acquire_partner_lock` 独立轮锁,仿 write 锁但独立字典)
- Test: `tests/test_partner_endpoints.py`

**Interfaces:**
- `POST /api/partner/say {root, text}` → ndjson 流(assistant/assistant_delta/tool/result/proposal/error/done)。复刻 /api/write:先 acquire_partner_lock(拿不到→409 partner_busy)→ worker 线程 run_turn(emit=q.put)→ finally lock.release()+q.put(None)→ StreamingResponse。**backend 用 get_backend(主模型),不走 cheap**(对话是主体验)。
- `POST /api/partner/confirm {root, id}` → usecases.partner_confirm(非流式,write_lock)。
- `POST /api/partner/new {root}` → usecases.partner_new。
- `GET /api/partner/history?root=` → usecases.partner_history(纯读,query 参数,同 journey_state)。

**背景(scout):** partner 轮锁独立于 write_lock(`_partner_locks` 字典),防两次并发 say 交错写同一 jsonl;织章持书写锁几分钟,say 不碰书写锁所以织章期间可聊。ts 由 server 生成(用 request 时刻——但 Date.now 在脚本禁,server 运行时用 `time.strftime` 无妨,这是运行时不是 workflow)。

- [ ] Step 1-4: TDD(端点测试用 FastAPI TestClient,同 test_server_write_lock)——测 say 流式返事件、partner 锁互斥(并发 say → 409 partner_busy)、say 不被 write_lock 挡(织章持书锁时 say 仍通)、confirm/new/history 端点。实现四端点 + 独立轮锁。
- [ ] Step 5: Commit `feat(server): /api/partner/say流式(独立轮锁不碰书写锁)/confirm/new/history`

---

### Task 3: DemoBackend 罐头多轮 + CLI 护栏伙伴变体

**Files:**
- Modify: `loom/backends.py`(DemoBackend 领航员分支脚本化多轮;ClaudeCodeBackend/CodexBackend `complete` 加 `agent_mode` 关闭反 agent 护栏)
- Modify: `loom/partner.py`(run_turn 调 complete 时对伙伴通道传 agent_mode=True)
- Test: `tests/test_partner_backends.py`

**背景(spec §3/§8):** demo 罐头按对话轮数(数 user prompt 里的 assistant 事件)出:开场→提问→提设定候选→收尾,自报 `(demo)`。CLI 护栏 `_GUARD` 现禁「调用工具/反问」——伙伴变体要允许输出一个 `用:` 块 + 允许反问,保留 `--allowed-tools ""`/read-only 沙箱(真实工具由 loom 执行,CLI 只产文本)。

- [ ] Step 1-4: TDD——测 demo 下 run_turn 多轮各出合规内容(问题/工具/proposal);测 ClaudeCodeBackend(mock subprocess)agent_mode=True 时 prompt 不含「禁止反问/调用工具」、agent_mode=False(默认,五工序)仍含旧护栏。实现。
- [ ] Step 5: Commit `feat(backends): demo罐头多轮+CLI护栏伙伴变体(agent_mode允许工具块与反问)`

---

### Task 4: 红线文档改写(领航员.md + ADR 0015 + ADR 0014 + CONTEXT)

**Files:**
- Modify: `loom/templates/agents/领航员.md`(删「绝不发明设定」保留「绝不替作者做决定」+ 补候选卡纪律 + 一次一题/给具体候选/别连环追问)
- Create: `docs/adr/0015-navigator-agent.md`(书房伙伴对话 agent 吞访谈;继承 0013 不引框架/无第二真相;四协议形状换代)
- Modify: `docs/adr/0014-startup-completeness-gate.md`(立项红线第三条→「走作者拍板通道(手填/建书代落/伙伴候选卡);AI起草候选未拍板一字不进」+注原辩护措辞被0015取代)
- Modify: `CONTEXT.md`(领航员词条重写为书房伙伴 agent + 命名公约;创作旅程词条改述为对话流;审稿留痕词条领航员留痕更新;新增.伙伴对话词条 + Avoid补「别把对话当状态读回,例外待确认proposal」)
- Test: 无新测试;跑全量确认 `test_journey.py:62/67`(「问题卡」in text)等依赖领航员.md 文案的断言——**领航员.md 改写要保留这些断言依赖的短语,或同步改测试**(先查哪些测试读领航员.md)。

- [ ] Step 1: 先 grep 哪些测试断言领航员.md/CONTEXT 的具体文案(`grep -rn "问题卡\|绝不发明\|领航员" tests/`),确认改写不破它们(破了就是替代测试问题,停下报告)。
- [ ] Step 2-4: 改四处文档,跑全量确认绿。
- [ ] Step 5: Commit `docs(navigator): 红线改写——领航员.md删「绝不发明设定」+ADR0015新建+0014修订+CONTEXT四处`

---

### Task 5: 前端对话 UI(与卡片机并存,控制者浏览器验证)

**Files:**
- Modify: `loom/webui/app.js`(paintJourney 增对话流渲染:say 流式消费、候选卡渲染、confirm 按钮;与现有卡渲染并存,feature-gate 或新函数)
- Modify: `loom/webui/style.css`(对话气泡/候选卡样式)
- Modify: `loom/webui/index.html`(如需容器)

**背景:** 复用现有 ndjson 流式消费(/api/write 的进度显示)。候选卡:内容 + 落点人话 + 〔就这么定〕〔改一改〕,虚线边+「候选」角标(spec §6.1);落点已填时渲染旧值 + 〔替换〕。**这是无自动化测试区,控制者必须浏览器 preview 亲验**:先钉临时书,起 loom-dev(非 demo 也可,但 demo 罐头能免 key 全链路),对话→看地基→提设定候选→点确认→落盘,截图留证。

- [ ] Step 1: 实现对话 UI(不删卡片机,新增对话渲染路径)。
- [ ] Step 2: 控制者浏览器验证(preview,先钉临时书):对话往返、候选卡渲染、点确认落盘、事件流显示。截图。
- [ ] Step 3: Commit `feat(webui): 书房伙伴对话UI(对话流+候选卡+拍板确认;与卡片机暂并存)`

---

### Task 6: 全量回归 + 端到端烟测 + 卡片机退役决策(控制者)

- [ ] `.venv/bin/python -m pytest -q && .venv/bin/python -m evals.run_eval --gate` 全绿无回归。
- [ ] 端到端烟测(临时书):demo 罐头起 loom-dev,真机走一遍起书对话→拍板落盘→门禁解锁→写章,浏览器截图。
- [ ] **卡片机退役决策**:替代测试(P1 land_slot + P2 partner)已绿 + 对话 UI 浏览器验证通过 → 若一切稳,可退役 next_card/card 端点/paintJourney 卡体;**但 land_answer/digest 落盘器保留为 legacy**(避免 _land_sections 耦合断裂),goto/voice skip 按 spec §9 处理。**若 UI 或退役有任何不稳,保留卡片机、flag 给用户**——irreversible 删除不盲提交。
- [ ] 汇报:P3 各任务、浏览器截图、退役决策与理由。P1+P2+P3 齐 → 全分支终审。

## 终审

P1+P2+P3 齐后走全分支终审(package P1起点..HEAD)+ superpowers:finishing-a-development-branch。**不 push 不 merge**——等用户验收。
