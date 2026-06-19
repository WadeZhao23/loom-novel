# Loom v0.2 借鉴落地 · 工单板

> 来源:对 [webnovel-writer](https://github.com/lingfengQAQ/webnovel-writer) 的借鉴分析。原则:只搬**内容资产**和**范式最瘦子集**;拒绝向量库/SQLite/投影/打分/CC-hook 等重基础设施,守住 Loom「极简 + 像你」。

## 批次与执行顺序

### 批次1 · 零风险即做(纯内容/隔离小代码)

这五张都不碰『写作指纹 learn diff』链、不改 run_pipeline 主流程、彼此文件交集极小,失败也不污染『像你』。T2/T5 是纯 Markdown 增补(T2 只动 金手指.md + 世界观.md + 设定师 reads 一行;T5 只动 故事引擎/评估自检 两个 skill 文本)。T9 拆书是新增 deconstruct.py + 新增 拆书.md + cli.py 插一个子命令,产物落 外置大脑/.拆书/ 隔离区、任何 agent reads 都不含拆书、run_pipeline 不读它,与主流程零耦合。T3 errors.py 是纯数据+render、不 import loom 任何模块、只替换工程类错误文案。T4 doctor 是只读自检(stat/find_spec/which),不写文件、不调 LLM、不进 write/seed 前置门。先清掉这批拿到信心和绿测,再碰命门。

- [T2-golden-finger](T2-golden-finger.md) · 金手指 skill —— 从一句占位变成可填字段卡(内容补给) （content/small）
- [T5-reading-power](T5-reading-power.md) · 追读力 skill 文本增补：微兑现 + 章内/章末钩分工 + 两条章衔接自检 （content/small）
- [T9-deconstruct](T9-deconstruct.md) · 拆书引擎:离线 skill + loom deconstruct 命令(只抽可迁移框架、剥专名、产物供人确认,绝不回流指纹/canon) （hybrid/small）
- [T3-error-catalog](T3-error-catalog.md) · 错误目录 errors.py:把后端/CLI/Server 的"友好一行"升级成结构化四段(标题/原因/影响/下一步) （code/small）
- [T4-doctor](T4-doctor.md) · 极简 doctor 启动自检(loom doctor 子命令 + /api/doctor + WebUI 自检按钮) （code/small）

### 批次2 · 命门与续跑(改 agents/fingerprint 主流程,需谨慎)

T1 是灵魂命门:在 learn() 成功学完指纹后,从手改终稿蒸馏剧情摘要 write-once 回填 卡章纲.md。它直接挂在 fingerprint.py:learn() 上,必须保证 recap 失败绝不回滚 learn 本职、产物带 [AI回顾] 标记进缩进子块、只进卡章纲(大纲师/设定师域)绝不回流指纹。T6 ledger 改 run_pipeline 记 sha 跳过未变工序,落 正文/.原稿 区、复用现有『手改过拒覆盖』drift 逻辑。两者都触碰核心引擎、需要先有批次1 的 doctor/errors 兜底和回归测试垫底,故单独成批、串行做(先 T1 再 T6,避免同时改 agents.py 的快照/保存区)。

- [T1-chapter-recap](T1-chapter-recap.md) · 写后摘要补卡章纲(命门):learn 接受一章后从手改终稿抽摘要+伏笔行 write-once 回填卡章纲 （code/medium）
- [T6-ledger-resume](T6-ledger-resume.md) · 极简 ledger 断点续跑:记 sha + 跳过未变工序,省 DeepSeek 重算 （code/medium）

### 批次3 · 需用户裁决(与现有铁律/决定冲突)

T8 与现有编辑.md/评估自检.md 的明文决定『就地改好、不要只列清单』正面冲突——它要编辑在改稿后附《本章改动留痕》,本质是把『不列清单』反过来。且需在 agents.py 加 _strip_edit_note 保证留痕绝不进 .原稿 快照(否则污染 learn 的 diff),涉及对 workspace/落盘语义的精确理解,风险最高,必须先由用户拍板是否打破既有编辑哲学。T7 是 large:新增 37 个题材文件 + 改 scaffold.py(init 加 genre 参数、copytree ignore 题材目录、别名归一)+ 改 设定师 reads。内容量大、改 init 离线铁律、且与 T2 抢 设定师.md reads 块,需用户确认题材清单与 init 交互形态后再动。

- [T8-soft-review-gate](T8-soft-review-gate.md) · 审稿留痕(软门,不阻断):编辑在改稿后附《本章改动留痕》+ 硬伤不阻断高亮 （hybrid/small）
- [T7-genre-library](T7-genre-library.md) · T7-genre-library: 37 题材压一屏 → skills/题材/(hybrid), init 按选题只拷一份 （hybrid/large）

## 工单间冲突与调和

- **T8 vs 编辑.md/评估自检.md** — 『直接修掉不要只列清单』vs『附改动留痕清单』语义冲突
  - → 留痕限定为哨兵后附记+_strip_edit_note剥净快照,需用户拍板
- **T1/T7/T9 vs 外置大脑人维护铁律** — AI 生成物触及人维护外置大脑
  - → 统一隔离协议:标记/隐藏区/可手改 file-as-truth,绝不回流指纹
- **T2 vs T7** — 都改 设定师.md reads 块
  - → 串行 T2 先 T7 后,只追加设定师 reads
- **T5 vs T8** — 都改 评估自检.md
  - → T5 先同构追加,T8 后加且保持软门不打分
- **T1/T6/T8** — 都碰 agents.py 快照/落盘语义
  - → 串行 T1→T6→T8,守 .原稿 快照纯净不变量

## 起步建议

先动批次1 里的 T2、T5、T9 三张纯隔离工单——它们 100% 是 what/voice 物理隔离的安全区:T2/T5 纯 Markdown 增补、零代码风险、改完即真;T9 拆书是全新增文件 + cli 插一条子命令,产物落 .拆书/ 隔离区、任何 agent reads 不含它、run_pipeline 不读它,与核心引擎零耦合。这三张拿到第一波绿测和信心后,接 T3(errors.py 纯数据)→ T4(只读 doctor),清完整个批次1。\n\n然后才进批次2 命门:先 T1(写后摘要回填卡章纲),它直接挂 fingerprint.py:learn(),必须先把『recap 失败绝不回滚 learn 本职、产物带 [AI回顾] 标记进缩进子块、write-once 不覆盖人手改、绝不回流指纹』四条做对并加回归测试;再 T6 ledger。\n\nT8、T7 押后到批次3,因为它们分别与『编辑不列清单』既有决定、和『init 离线铁律 + 设定师 reads』有真冲突,且 T7 是 large 题材清单工程——这两张动手前必须先让用户裁决(T8 是否打破编辑哲学、T7 的题材清单与 init 交互形态)。整条线串行守住一个不变量:正文/.原稿 快照永远是纯净 AI 终稿,是 learn diff 的唯一对照源。

---

## 索引(workflow 生成)

# Loom Backlog 索引

> 9 张借鉴工单的执行排程。守两条灵魂:**极简**(反向量库/SQLite/打分引擎/重基础设施)与 **『像你』**(写作指纹只学手改 diff,what 与 voice 物理隔离)。
> 红线(所有工单必须守):① 剧情套路(题材/金手指/拆书)只进设定师/世界观,绝不喂写手/写作指纹;② AI 生成进外置大脑的东西必须可手改且物理隔离、绝不回流写作指纹;③ 不引入向量库/SQLite/投影链/打分引擎/CC hook 这类重基础设施。

## 批次划分

- **批次1 · 零风险即做**:T2, T5, T9, T3, T4 —— 纯内容/隔离小代码,不碰 learn 主链。
- **批次2 · 命门与续跑**:T1, T6 —— 改 fingerprint/agents 核心引擎,串行谨慎。
- **批次3 · 需用户裁决**:T8, T7 —— 与既有铁律/决定冲突,先拍板再动。

## 工单索引

| id | 标题 | 类型 | 批次 | effort | 依赖 |
|----|------|------|------|--------|------|
| T2-golden-finger | 金手指 skill:占位 → 可填字段卡 | content | 1 | small | — |
| T5-reading-power | 追读力 skill:微兑现 + 钩分工 + 两条章衔接自检 | content | 1 | — (与 T8 协调改 评估自检.md) | — |
| T9-deconstruct | 拆书引擎:离线 skill + loom deconstruct 命令 | hybrid | 1 | small | — |
| T3-error-catalog | errors.py:工程错误升级四段结构(标题/原因/影响/下一步) | code | 1 | small | — |
| T4-doctor | 极简 doctor 启动自检(子命令 + /api/doctor + 按钮) | code | 1 | — (排在 T3 后) | — |
| T1-chapter-recap | 写后摘要补卡章纲(命门):learn 后从手改终稿 write-once 回填 | code | 2 | medium | — |
| T6-ledger-resume | 极简 ledger 断点续跑:记 sha + 跳过未变工序 | code | 2 | medium | — (排在 T1 后) |
| T8-soft-review-gate | 审稿留痕(软门不阻断):编辑附《本章改动留痕》+ 硬伤高亮 | hybrid | 3 | small | 需用户裁决 |
| T7-genre-library | 37 题材压一屏 → skills/题材/,init 按选题只拷一份 | hybrid | 3 | large | 需用户裁决;改 设定师 reads 排在 T2 后 |

## 关键冲突摘要

1. **T8 vs 编辑.md『就地改好、不列清单』** —— 软门留痕与既有编辑哲学正面冲突,需用户拍板;落地需 `_strip_edit_note` 保证留痕绝不进 `.原稿` 快照、不污染 learn diff。
2. **T1/T7/T9 vs『外置大脑人维护』铁律** —— 三者 AI 生成物擦边外置大脑;统一用隔离协议(`[AI回顾]` 标记 / `.拆书/` 隐藏区 / 可手改 file-as-truth)化解,均不回流指纹。
3. **T2 vs T7 抢 设定师.md reads** —— 串行编辑(T2 先 / T7 后),只往设定师 reads 追加,绝不进写手/润色师/写作指纹 reads。
4. **T5 vs T8 同改 评估自检.md** —— T5 先落,沿用 `- [ ] **名**:问句 = 改法` 同构结构;T8 后追加且保持软门不打分。
5. **T1/T6/T8 同碰 agents.py 快照语义** —— 串行 T1→T6→T8,共享不变量:`.原稿` 快照永远是纯净 AI 终稿、是 learn diff 唯一对照源。

## 不变量(每张工单落地后都要复测)

- `正文/.原稿/第N章.md` 始终是**纯净 AI 终稿快照**,是 `learn()` diff 的唯一对照源。
- 任何 agent 的 `reads:` 永不含题材/金手指/拆书/留痕;写手/润色师/写作指纹永不读 what 域内容。
- AI 生成进外置大脑的产物一律可手改、物理隔离、绝不回流 `写作指纹.md`。
- 新增工具(doctor/deconstruct/ledger)绝不进 write/seed 前置门禁,失败降级不阻断主流程。
