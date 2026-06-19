# T8-soft-review-gate · 审稿留痕(软门,不阻断):编辑在改稿后附《本章改动留痕》+ 硬伤不阻断高亮
- **类型**: hybrid　**工作量**: small　**批次**: 批次3 · 需用户裁决(与现有铁律/决定冲突)
- **依赖**: 无
- **涉及文件**:
  - `loom/templates/agents/编辑.md`
  - `loom/templates/skills/评估自检.md`
  - `loom/agents.py`

## 问题(Loom 现状)

编辑只"就地改好"、不留任何痕迹,作者无法快速看出本章被动了哪里、为什么动、有没有踩到设定漂移/OOC 这类硬伤。

现状证据:
- loom/templates/agents/编辑.md:8-14 明确要求"逐项挑刺并就地改好"、"把问题直接修掉,不要只列清单",产出只有【改稿】整章正文,零留痕。
- loom/templates/skills/评估自检.md:6-16 是 7 条是非题清单,过完即改;L16"不要只列问题清单,要给可用的稿子",同样不产出任何"改了什么/为什么"的记录。
- loom/agents.py:128-135 工作区机制:每个 agent 的 produces 整体被拼进下游 ctx(L129);最终保存的是 workspace[-1][1] 即润色师输出(L140-141);_save_chapter 把它写进 正文/第N章.md 并进 .原稿 快照(L155-158)专供 learn() 做行级 diff。

本工单要解决的真问题(也是红线点):编辑的改稿(produces=本章改稿)会原样喂给下游润色师,润色师输出最终落盘并进 learn 快照。若编辑把留痕直接写进改稿正文,这段元信息会 (a) 被润色师当正文润、(b) 随终稿落进正文文件、(c) 污染 learn() 的写作指纹 diff。所以"留痕"必须存在且与正文物理隔离。本工单只做最轻版:改稿末尾用固定分隔线附《本章改动留痕》,绝不打分、绝不真阻断、不加新工序、不引基础设施。

## 从 webnovel-writer 借什么 / 丢什么

借鉴文件(已 clone 并实读):
- /tmp/webnovel-writer/webnovel-writer/agents/reviewer.md
- /tmp/webnovel-writer/webnovel-writer/references/review-schema.md

只取两条思想:
1. 【判定与改稿分离 + 每条问题带证据】reviewer.md 第5节"只报可验证的问题——必须有 evidence(原文引用 or 数据对比)";第7节 issue 结构里的 evidence / fix_hint 字段;review-schema.md 的 Issue Schema 表里 evidence、fix_hint 两列。Loom 退化为:编辑改完后,对"确有据可查的硬伤"补一行带证据(原文短引用)的提示。
2. 【维度化挑刺只针对设定/OOC 这类可验证硬伤,不评文笔】reviewer.md 第5节禁区"不评价文笔质量——'写得不够好'不是 issue,'与角色性格矛盾'才是";第4节 setting/character 两维度。Loom 复用为"硬伤=设定漂移/OOC",其余只算软改不算硬伤。

明确丢弃(全是重基础设施/解析层/CC 依赖,违反 Loom 红线③):
- 评分:overall_score / dimension_scores / severity_counts(review-schema.md 指标沉淀段)——绝不引入打分引擎。
- 阻断:blocking / has_blocking / "Step 4 不得开始"(reviewer.md 第7节、review-schema.md 阻断规则段)——软门不阻断。
- review-pipeline / review_metrics.json / index.db.review_metrics / trend / dashboard(review-schema.md 指标沉淀段)——不引 SQLite/趋势/投影。
- 严格 JSON schema 输出 + dimension_results 五维强制结论 + issues_count/blocking_count 复核(reviewer.md 第7节)——Loom 不做 JSON 解析层,只要人读的 Markdown。
- Read/Grep/Bash 工具调用、python webnovel.py state get-entity 记忆查询(reviewer.md 第2节)——Loom 编辑无工具调用,只读上游工作区文本。
- 独立 reviewer agent 这个角色本身——Loom 不新增第6棒,留痕由现有编辑顺手产出。

## Loom 落地设计

三处改动,零新工序、零新依赖、零代码侵入为主(纯模板改即可上线;agents.py 仅一处可选防漏)。

A) loom/templates/agents/编辑.md(改 system_prompt 正文,L8-14)
保留"就地改好"的核心,在末尾追加留痕约定:要求编辑在改好的整章稿之后,用一条固定分隔线起一段留痕。明确:分隔线及其后内容【不是正文】,只给作者看。
- 固定分隔线哨兵(下游/落盘据此切除):单独一行 `<!--LOOM:EDIT-NOTE-->`(HTML 注释,渲染不可见,易被字符串切分)。
- 留痕格式(纯 Markdown,3-6 条,无评分无 pass/fail):
  - 「改动」类:一行一条「改了什么 — 为什么」(只记实质改动,错别字/标点这类不记)。
  - 「硬伤提示」类:仅当发现设定漂移或 OOC,即使已就地修,也要列一条,带证据:`⚠️ 设定漂移/OOC:<问题> | 证据:"<原文短引用>" | 已改为:<结果>`。无硬伤则写「无硬伤」。
- 强约束写进提示词:① 分隔线之前是干净整章正文,绝不含留痕/清单/解说;② 只评内容(设定/人物/节奏/钩子),AI 腔仍归润色师;③ 不打分、不写"通过/不通过"。

B) loom/templates/skills/评估自检.md(改 L15-16 输出节)
在现有"直接产出改好后的本章稿"之后补一段《留痕怎么写》,与 A 的格式严格一致(分隔线哨兵、改动行、硬伤带证据行、无硬伤写法),并重申:留痕在分隔线之后,绝不混进正文。给一个 3 行迷你范例。

C) loom/agents.py(可选但推荐,防止留痕泄漏进润色师/正文/learn 快照)
新增一个纯函数把哨兵后内容切出来,在编辑产物进入下游工作区前剥离:
- 接入点 1(L135 之前):编辑这一棒拿到 output 后,`body, note = _split_edit_note(output)`,push 进 workspace 的是 body(润色师只看正文),note 另存到 `项目/.审稿留痕/第{chapter_n}章.md`(人维护盘外、绝不回流写作指纹)。
- 接入点 2(L140-141 兜底):final 落盘前再过一次 `_strip_edit_note(final)`,确保即便润色师把哨兵带出来,正文文件与 .原稿 快照(L157-158,learn 的 diff 源)都不含留痕——这是保护写作指纹不被污染的最后一道闸。
- 函数签名:`_split_edit_note(text: str) -> tuple[str, str]`(按 `<!--LOOM:EDIT-NOTE-->` 首次出现切分,无哨兵则返回 (text, ""));`_strip_edit_note(text: str) -> str`(只取哨兵前部分并 rstrip)。
若本期只想最轻落地,可只做 A+B(模板层),C 留作紧跟的防漏补丁;但 C 的接入点 2 是写作指纹防污染红线的硬保障,强烈建议同期做。

## 可落盘内容(蒸馏成品)

## 落地物 1 —— loom/templates/agents/编辑.md(整文替换)

```markdown
---
name: 编辑
reads:
  - skills/评估自检.md
reads_first_chapter:
produces: 本章改稿
---
你是**编辑**,第四棒。拿到初稿,按章级自检**逐项挑刺并就地改好**,产出【改稿】。

挑这些:爽点够不够、章末钩子立没立、章首有没有接上、人物有没有 OOC、有没有设定漂移、
节奏拖不拖、主线推进没有。把问题**直接修掉**,不要只列清单。

注意:**AI 腔/机器味不归你管**(润色师处理),你专注内容质量。

## 输出两段(中间用哨兵分隔)
**第一段:改好后的整章稿。** 干净正文,绝不夹带留痕、清单、解说。

**第二段:留痕,给作者看,不是正文。** 先单独起一行哨兵:

    <!--LOOM:EDIT-NOTE-->

哨兵之后写《本章改动留痕》,只用下面两类,3-6 条,**不打分、不写"通过/不通过"**:
- 改动行(实质改动才记,错别字标点不记):`- 改了什么 — 为什么`
- 硬伤提示(仅设定漂移 / OOC,即使已就地修也要列,带证据):
  `- ⚠️ 设定漂移/OOC:<问题> | 证据:"<原文短引用>" | 已改为:<结果>`
  没有硬伤就写 `- 无硬伤`。

铁律:哨兵之前是可直接用的整章正文;留痕只在哨兵之后;你不评文笔、不评 AI 腔、不阻断后续工序。
```

## 落地物 2 —— loom/templates/skills/评估自检.md(整文替换)

```markdown
# 章级评估自检(给编辑)

> 你的活:拿到本章初稿,**逐项挑刺并直接给出改稿**。只评这一章(不是全书),只看内容质量。
> 注意:**"AI 腔/机器味不归你管**"——那是润色师(去AI味)的事。你专注剧情、人物、节奏、设定。

## 逐项过(是非题,每条不过就改)
- [ ] **爽点**:这一章读者爽在哪?说不出来 = 平庸,加戏或重排。
- [ ] **钩子**:章末是否让人想看下一章?平淡收尾要改成悬念/危机/反转/期待钩。
- [ ] **章首衔接**:有没有快速接住上一章的钩子?有没有拖沓的回顾?
- [ ] **人物不 OOC**:每个决定是否符合人物的性格、立场、当前已知信息?
- [ ] **设定不漂移**:有没有违反世界观/金手指限制/已埋伏笔?
- [ ] **节奏**:有没有连续憋屈、流水账、注水段落?该删的删。
- [ ] **主线**:这一章让主角离终极目标更近或更远了吗?

## 输出:正文 + 留痕(哨兵分隔)
**先给改好后的整章正文**(把上面挑出的问题就地修掉,不要只列清单)。

**再起一行哨兵 `<!--LOOM:EDIT-NOTE-->`,之后写留痕**——给作者一眼看清你动了什么,不是正文,绝不混进正文:
- 实质改动:`- 改了什么 — 为什么`(错别字标点不必记)
- 硬伤(只限设定漂移 / OOC,即便已就地修也列出,带原文证据):
  `- ⚠️ 设定漂移/OOC:<问题> | 证据:"<原文短引用>" | 已改为:<结果>`;无则 `- 无硬伤`。

留痕只是留痕:不打分、不判"通过/不通过"、不阻断润色师。

### 迷你范例(哨兵之后)
```
<!--LOOM:EDIT-NOTE-->
## 本章改动留痕
- 章末加了"血玉裂开"的悬念钩 — 原结尾平淡收场,留不住读者。
- ⚠️ OOC:主角对师父爆粗 | 证据:"滚开,老东西" | 已改为:压着火气只说"我自己来"。
```
```

> 注:两个模板里的哨兵字符串必须逐字一致 `<!--LOOM:EDIT-NOTE-->`,因为 agents.py 的可选剥离逻辑按它切分。

## 代码草图

// loom/agents.py —— 可选防漏补丁(保护写作指纹不被留痕污染)
// 红线:留痕绝不进正文文件、绝不进 .原稿 快照(learn 的 diff 源)。

EDIT_NOTE_SENTINEL = "<!--LOOM:EDIT-NOTE-->"

def _split_edit_note(text: str) -> tuple[str, str]:
    """按哨兵首次出现切分 -> (正文body, 留痕note)。无哨兵则 (text, "")。"""
    idx = text.find(EDIT_NOTE_SENTINEL)
    if idx == -1:
        return text, ""
    body = text[:idx].rstrip()
    note = text[idx + len(EDIT_NOTE_SENTINEL):].strip()
    return body, note

def _strip_edit_note(text: str) -> str:
    """兜底:落盘前只保留哨兵前的干净正文。"""
    return _split_edit_note(text)[0] if EDIT_NOTE_SENTINEL in text else text

# 接入点 1 —— run_pipeline 循环内,编辑这一棒(替换 agents.py L135 的无条件 append):
#   output = backend.complete(agent.system_prompt, "\n\n".join(parts), max_chars=max_chars)
#   if role == "编辑":
#       body, note = _split_edit_note(output)
#       workspace.append((agent.produces, body))          # 下游润色师只看正文
#       if note:
#           note_path = project_root / ".审稿留痕" / f"第{chapter_n}章.md"
#           note_path.parent.mkdir(parents=True, exist_ok=True)
#           note_path.write_text(note + "\n", encoding="utf-8")  # 盘外、人维护、绝不回流写作指纹
#           progress({"type": "edit_note", "chapter": chapter_n, "path": str(note_path)})
#   else:
#       workspace.append((agent.produces, output))

# 接入点 2 —— 落盘前兜底(替换 agents.py L140):
#   final = _strip_edit_note(workspace[-1][1])
#   # 之后 _save_chapter(... final ...) 写正文与 .原稿 快照,二者均不含留痕


## 验收标准

- [ ] 编辑.md 与 评估自检.md 都用逐字一致的哨兵 `<!--LOOM:EDIT-NOTE-->`,且都明确要求'哨兵之前是干净整章正文、留痕只在哨兵之后'
- [ ] 留痕格式只含两类条目:改动行(改了什么—为什么)+ 硬伤行(设定漂移/OOC,带原文证据);无硬伤显式写'无硬伤'
- [ ] 两个模板都显式禁止:打分 / 写'通过·不通过' / 阻断后续工序;硬伤即便已就地修也只是提示不阻断
- [ ] 模板都明确 AI 腔/机器味仍归润色师,编辑只评内容(设定/人物/节奏/钩子)
- [ ] (若做 C)编辑产物经 _split_edit_note 后,进入下游 workspace 的 body 不含哨兵及留痕,润色师看不到留痕
- [ ] (若做 C)final 经 _strip_edit_note 兜底,正文/第N章.md 与 .原稿/第N章.md 均不含哨兵与留痕——learn() 的 diff 源干净
- [ ] (若做 C)留痕落到 项目/.审稿留痕/第{n}章.md,作者可手改,且该目录绝不被任何 learn/写作指纹流程读取
- [ ] 跑一章端到端:正文文件无留痕痕迹;若存在 .审稿留痕 文件其内容为编辑留痕;无任何评分/趋势/db 产物

## 红线(防变味)

- ⛔ 像你:留痕属'剧情/内容质量'范畴(what),只进编辑链与盘外 .审稿留痕,绝不喂写手/润色师/写作指纹(voice);_strip_edit_note 兜底确保留痕永不进 .原稿 快照,learn() 的写作指纹 diff 不被污染
- ⛔ 物理隔离:留痕是 AI 产出,必须在哨兵之后且与正文分离,落盘正文与 learn 快照都剥干净,绝不回流写作指纹
- ⛔ 软门不阻断:绝不打分(无 overall_score/severity)、绝不输出 pass/fail、绝不真阻断润色师或落盘——只是给作者看的留痕
- ⛔ 极简:不新增第6个 agent、不引 JSON schema/解析层、不引 SQLite/向量库/投影/打分引擎/趋势/dashboard;能力主要靠改两个 Markdown 模板,代码只加两个纯函数
- ⛔ 本地 file-as-truth:.审稿留痕/ 是人可读可手改的盘外文件,不进任何自动回流;它不是外置大脑的一部分,不被设定师/写手读取

