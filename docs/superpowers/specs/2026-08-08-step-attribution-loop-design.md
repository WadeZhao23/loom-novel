# 棒级归因闭环 · 设计

> 目标一句话：**让 eval 的分数能直接翻译成「改哪一棒的 prompt」，而不是只告诉你「这章掉分了」。**
>
> 日期：2026-08-08 · 前置：eval Phase 0–4 + 门控真拦截已合入 main（v0.4.2）

## 1. 为什么是现在

现有三套 suite 各司其职，但**没有一套回答「这版 agent 比上版写得好吗」**：

| suite | 回答的问题 | 状态 |
|---|---|---|
| Fixture（`evals/cases/`） | grader 本身准不准 | 活的，进 PR CI |
| Judge 校准（`evals/dataset/`） | LLM Judge 准不准 | 最扎实的一环（κ=0.8231，信息边界晋级 hard） |
| **Generation（`evals/gen_cases/`）** | **生成质量是涨是跌** | **只 demo 冒烟过链路，真机验收从未跑** |

所以「优化 agent 能力」目前**没有任何数据支撑**，只能凭感觉。这份 spec 补的就是这一环。

而且即便真机跑通，现有形状也只产出**章级总分**——分掉了，你不知道该改五棒里的哪一棒。
本设计的核心是把归因粒度做到**棒级**。

### 闭环还没跑，第一个目标已经确认

`loom/templates/skills/评估自检.md` 给编辑列了 12 项自检，其中 **6 项要求它核对结构上拿不到的材料**：

| 自检项 | 需要 | 编辑实际有吗 |
|---|---|---|
| 承诺兑现 / 章首衔接 | 上一章正文 | ❌ `StepSpec("编辑", …)` 无 `wants_prev`（`loom/agents.py:66`） |
| 设定不漂移 | 世界观 / 金手指限制 | ❌ 无 `wants_hardfacts`；reads 只有 `skills/评估自检.md` |
| 人物不 OOC | 人物卡 | ❌ |
| 物品/状态连续性 | 状态账本、卡章纲 `[AI回顾]` | ❌ |
| 时间连续性 | 前情时刻 | ❌ |

它只有工作区里的**设定锚点**（≤350 字的选择性摘要）+ 细纲 + 初稿。
而挂在它后面的质检 gate **拿得到**这些（`_GATES["编辑"]` 列了 `WORLD_DIR_REL`/`CHARS_REL`/`STATEBOOK_REL` + 上一章，
`loom/agents.py:37-41`），但默认 `轮数=1` 时 gate **只诊断不回炉**。

净效果：**有材料的不改，改的没材料。** 这正是棒级归因该抓的第一类问题，
且它是结构性的——不花钱跑真机就能确认。

## 2. 已拍板的决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 走**闭环**：eval 驱动 agent 改进 | 两半（完善评测 / 优化 agent）在这条线上同时推进 |
| 2 | 归因做到**棒级** | 章级总分翻译不成「改哪一棒」 |
| 3 | **多次运行取分布**，不给 backends 加 temperature=0 通道 | 守「产品码不动」；且用户真实体验就跑在 temp=0.9 |
| 4 | 本轮**不拉「像你」**，只攻客观质量 | 确定性 grader 对同一文本可复现，噪声只来自生成侧；风格链另起一轮 |
| 5 | 路线 B：建闭环 + **只修会污染数字的** eval 缺陷 | 闭环的价值靠「第一次跑就抓到真问题」证明 |
| 6 | 覆盖面 = 五棒 + **状态账本回写链** | 回写链与已确认的 continuity 四个 bug 是同一条链，不纳入就修不干净 |
| 7 | `rewrite.py` 数据丢失**拆成独立修复** | 确定性 bug + 零测试模块，与闭环设计正交 |

## 3. 架构

**接线点**：`evals/generate.py:173`（`_grade_candidate` 之前）插一步，把 ledger 里的五棒产物收进 `run_dir`。

机制上几乎白送：`run_pipeline` 对 `PIPELINE` 里**每一个** role 都调了
`ledger.record_step(project_root, chapter_n, role, output, up_sha)`（`loom/agents.py:707`），
`output` 是**该棒完整产物原文**。`generate_one` 在 `line 145` 就持有临时项目根 `project`，
只是跑完只拷了终稿，把 ledger 扔了。

```
evals/
  generate.py        改：收 ledger → run_dir/steps/*.md；新增 --repeat N
  stepgraders.py     新：棒级体检项（纯确定性，零 LLM，同一文本可复现）
  aggregate.py       新：N 次 → 分布（中位数 / 区间 / 有效次数）
  gen_cases/
    gen_01_mine_rebirth/   现有：overlay 带固定细纲 → 大纲师被 WYSIWYG 旁路
    gen_02_<新>/           新增：不带 overlay 细纲，让大纲师真跑
  runs/<batch_id>/
    runs/<run_id>/steps/{设定师,大纲师,写手,编辑,润色师}.md   新
    runs/<run_id>/step_report.json                          新
    summary.json / summary.md                               新
```

**为什么需要 `gen_02`**：`gen_01` 的 `overlay/正文/.细纲/第1章.md` 让细纲文件先存在，
大纲师走 WYSIWYG 旁路不调模型。实测 manifest `n_calls=7` = 设定师/写手/编辑/质检 critic/润色师/去AI味 critic/标题
——**没有大纲师**。不加一个无 overlay 细纲的 case，大纲师这一棒永远评不到。

## 4. 棒级体检项

设计原则：每一项都是**「上游有、这一棒输出里没了」的差分**，所以命中就能定位到棒。
全部确定性、零 LLM 调用。

| 棒 | 体检项 |
|---|---|
| 设定师 | 锚点是否含 case 声明的硬设定专名/等级；是否 ≤350 字（`_SHORT["设定师"]`） |
| 大纲师 | 细纲是否覆盖 `must_include`；**场次数落在 `_scene_budget(chapter_chars)` 声明的区间内**；每场标了「约X字」且各场预算合计对得上章目标；有没有点名章末钩类型 |
| 写手 | 初稿字数 vs 目标；`must_include` 命中；`aitell` 命中数 |
| 编辑 | 改稿 vs 初稿：字数变化、`must_include` 有没有被改丢、留痕哨兵 `<LOOM:EDIT-NOTE>` 是否成对 |
| 润色师 | 终稿 vs 改稿：`aitell` 命中降了没、字数掉了多少 |

**复用纪律**：一切对 loom 的复用照旧只走 `loom/evalapi.py` 门面，import 失败不降级。
若某体检项需要新的引擎能力，走 evalapi 加接缝，不 import 私有符号。已确认可复用、需加接缝的：

- `_scene_budget(chapter_target)` / `_parse_scene_budgets(outline)`（`loom/agents.py:529,134`）
  —— 场次预算判据已在产品里实现，**别在 evals 里重写一套**，否则两边会漂
- `_hardfacts_for` 的专名册（设定师体检项要用）
- `aitell.detect`（已在 evalapi 里）

## 5. 数据流

```
python -m evals.generate --case X --backend configured --repeat 5
  每次：mkdtemp → scaffold → overlay → run_pipeline
        → 收 ledger 五棒产物 + 终稿
        → 终稿  跑现有章级 grader（harness.run_case）
        → 五棒产物 跑 stepgraders
  聚合：每项取 中位数 + 区间(min~max) + 有效次数
  落   evals/runs/<batch_id>/{runs/*, summary.json, summary.md}

python -m evals.generate --compare <batch_a> <batch_b>
  → 逐棒逐项列 Δ（中位数差 + 区间是否重叠）
```

**判据纪律**：区间重叠 = **不宣称有改进**。单次分数差一律不作结论——
这把 `evals/README.md` 已经写下的「看多次运行的分数分布，而不是拿单次结果定生死」
从文档声明变成工具行为。

## 6. 只修会污染闭环数字的 eval 缺陷

| 缺陷 | 证据 | 修法 |
|---|---|---|
| LLM grader fail-open | `evals/graders.py:205-232`：`parse_critic_verdict` 解析不出 → 0 条硬伤 → `score=1/(1+0)=1.0` → 通过 | 解析失败判 infra，不判满分。与 `evals/judge.py:168-184` 的 `infra_error` 同口径 |
| LLM grader `gating=True` 却不在 baseline | `graders.py:35` gating 默认 True；仅 except 分支设 False（`:212,227`）；`run_eval.py` 的 `--judge` 与 `--gate` 无互斥 | `--judge --gate` 同传时权重和从 0.70 跳到 1.00，所有 case 分数整体位移 → 必然伪回归。互斥或进 baseline |
| `len_tolerance=0.6` | `cases/case_01`,`case_02`,`gen_cases/gen_01` 三处全是 0.6 | 见下方「字数容差怎么定」 |
| `pyproject` dev 缺 pyyaml | `pyproject.toml:21` `dev = ["pytest>=8.0"]`；`ci.yml` 装 `-e ".[dev]"`；`tests/test_eval_workflows.py:14,25,34,45` 全是 `importorskip("yaml")` | 一行依赖。这 4 个护栏守的是「PR CI 绝不碰 secret」「eval-real 绝不挂 pull_request」，在 CI 上**全部静默 skip**、从未生效 |

### 字数容差怎么定（避免又一个拍脑袋阈值）

分两步，**不在 spec 里硬拍数字**：

1. **先量**：第一份真机基线（§12.6）跑完后，看 `gen_01`/`gen_02` 各 5 次的实际字数分布。
2. **再定**：容差取「能让『目标 3000 字交 400 字』判失败」的量级，且**封顶 0.25**——
   超过 0.25 就说明这个 grader 事实上不设防，不如老实标成 observe。
   定下的值连同基线数据一起提交，git 历史即「先量后定、非事后倒推」的证据（同 `targets.json` 预注册纪律）。

**连带后果**：`evals/cases/*` 的 `len_tolerance` 一改，Fixture 基线分数就变，
必须 `python -m evals.run_eval --baseline` 重新固化并**与改动同一个 commit 提交**。

`case_02_flawed` 的契约**不受影响**（已核对 `evals/harness.py:75-82`）：`contract_ok` 只检查
`expect_fail_graders` 里点名的两个 grader（关键要素 / 去AI味·确定性），长度达标不在其中。
但 `_weighted(graders)` 仍含长度达标，所以它的**分数**会变——这正是必须重新固化基线的原因。

## 7. 状态账本回写链 + continuity 四个 bug

### 回写链

`loom/agents.py:722` 在 `_save_chapter` 之后调 `_scan_continuity(…, final_body, …)`——
吃的是**未经作者手改的 AI 终稿**；结果 write-once 落状态账本，
再同时充当写手 prompt 的「当前状态」权威 + 四个确定性检测器的唯一事实源。

**一条幻觉入账，会同时污染后续所有章的 prompt 和所有确定性检测。**

产品把「AI 绝不回写自己的输出」当铁律，但那条铁律的作用域只是**写作指纹**（ADR 0001/0002）；
what 维度上恰恰相反。本 spec 不推翻这个设计，只要求：
1. 入账项可追溯到章号
2. LLM 侧失败不再被裸 `except` 吞掉（`loom/continuity.py:430`）——现在哑掉与「本章无矛盾」表象完全一样
3. eval 侧开一条能覆盖除虫的口径：`evals/generate.py:63` 现在强制 `continuity_scan=False`，除虫在评测里从没跑过

### continuity 四个 bug（逐一验证过）

| bug | 证据 | 后果 |
|---|---|---|
| `char_names` 是死参数 | `detect_char_continuity` 函数体从头到尾没引用它 | 账本里任何 `[状态]` 行左半段（哪怕「阵法」「城主府」）都进别名匹配 |
| `prior` 用泄漏的循环变量 `m` | `prior=f"第{m}章账本…"`，`m` 是 `for m in reversed(sorted(…))` 结束后的残值 | 永远指向**最早**那章，不是状态实际所在章；「双证据」卖点指错地方 |
| `state_line not in body[:500]` 实质恒真 | `state_line` 是账本行（如「沈砚:重伤」），几乎不可能是正文前 500 字的子串 | 书里有闭关/重伤角色，之后每章只要他露面就固定刷一条 3 星报告 |
| 单姓别名 + `set` 遍历 | `aliases.append(name[0])`；`for alias in set(…)` 后 `break` | 单汉字必然撞词（苏醒/苏州）；set 遍历受 hash 随机化影响，同一稿两次除虫产出不同证据，破坏「纯函数可复现」定位 |

**测试为什么全绿**：`tests/test_continuity.py` 的账本恰好把特殊状态放在**第 1 章**，
掩盖了 `m` 泄漏。新回归 fixture **必须把状态放在非第 1 章**。

## 8. 错误处理（守「不造数」红线）

- 单次 run 崩（后端超时/空响应）→ 记 infra，**不计进分布**；summary 如实写「5 次里 4 次有效」。
  **绝不用 4 次均值冒充 5 次。**
- ledger 缺某棒（WYSIWYG 旁路或续跑跳过）→ 该棒记 `skipped`，**不记 0 分**（旁路 ≠ 失败）。
- 全部 run infra → 退出码 2，沿用现有三态（0 通过 / 1 回归 / 2 infra）。
- `--compare` 时任一批的有效次数为 0 → 拒绝出结论，退出 2。

## 9. 测试策略

| 对象 | 怎么测 |
|---|---|
| stepgraders 每一项 | 合成夹具 TDD，零 key 零联网，进 PR CI |
| 聚合逻辑 | 合成分数序列：正常 / infra 掉数 / 全 infra / 只剩单次有效 |
| 收 ledger | `ScriptedBackend` 注入，断言五棒产物都落盘、被旁路的棒记 `skipped` |
| continuity 四个 bug | 各一条回归测试，**fixture 状态放非第 1 章** |
| LLM grader fail-open | 注入不可解析输出，断言判 infra 而非 score=1.0 |
| CI 护栏 | 补 pyyaml 后确认那 4 个测试真的跑（不再 skip） |

## 10. 第一批 agent 修复目标

**不预先假定要改，先跑基线再照数据定。** 但已确认结构性缺陷、大概率被第一次闭环点名的：

1. **编辑失明**：6/12 自检项材料缺失（§1）
2. **设定师失明**：被要求产出「要接住上一章哪个钩子」「已埋伏笔」，但无 `wants_prev`、不 reads 卡章纲
3. **续跑吃细纲 WYSIWYG**：细纲文件不在大纲师 reads → 不进签名 → 半截章续跑时大纲师被判「上游未变」跳过，
   workspace 回填 ledger 里的旧细纲，**作者手改的细纲根本没被读**
4. **大纲师字数指令自相矛盾**：`_length_hint` 要求细纲 ≤450 字，同段任务却要 6 场 × 5 要素 + 爆发点 + 接钩 + 钩类型 + 爽点

改动允许落到 `loom/templates/agents/*.md` 与 `agents.py` 的 `StepSpec`——那正是「优化 agent 能力」本身。
**决策 3 的「不动产品码」特指不加 temperature=0 通道，不涵盖 agent prompt。**

## 11. 明确挂账（不在本 spec）

- 「像你」/风格链评测（`seed → 手改 → 句级对齐 → learn → 指纹 → 写手/润色师` 整条零 eval）
- `draft` / `diagnose` / `enrich` / `recap` 的 prompt 面评测——它们生产的是流水线的**输入**
- `diagnose` 的「逐条带 (第N章) 出处」红线：只存在于 docstring 与 prompt 字符串，**代码零实现**
  （对比 `draft` 那条红线有 `loom/draft.py:79-87` `_is_blank_or_template` 真实现）
- 领航员 Phase 5 对话协议 eval
- `rewrite.py` 数据丢失（已拆独立任务）
- 人-人 κ / κ 可复现 / hard 门禁部分-infra 静默变绿 —— Judge 元门禁线，与生成质量闭环正交
- 供应商轴：所有真机结论目前只对 deepseek 一家成立；claude/codex CLI 后端丢弃 `max_chars`
  且 `_GUARD` 与编辑棒的留痕协议正面冲突
- 输入上下文无界增长：`budget.py` 只折叠 AI 追加块，人写的卡章纲/世界观/人物随书龄无界增长；
  Generation suite 只跑第 1 章，永远看不到增长曲线

## 12. 验收

1. `--repeat N` 跑通，`run_dir/steps/` 落齐五棒（`gen_02` 上大纲师不再是 `skipped`）
2. 一份 `summary.md` 能读出「哪一棒的哪一项最弱」，且区间重叠时不宣称改进
3. 全量 `pytest` 绿 + `python -m evals.run_eval --gate` 码 0
4. 补 pyyaml 后那 4 个 CI 护栏测试不再 skip
5. continuity 四条回归测试在修复前红、修复后绿
6. **真机基线**：`gen_01` + `gen_02` 各跑 5 次，产出第一份棒级基线报告（要花 API 费，择时跑）

## 13. 贯穿红线（继承既有约定）

1. **不造数**：真人/真机才有的数留空位，不冒充
2. **产品侧不打分不阻断**（ADR-0002 / ADR-0006）：分数、阈值、区间只活在 `evals/`
3. **两套 suite 分离**：Fixture 零 key 进 PR CI；Generation 要 key，手动/定时
4. **evalapi 单一接缝**：import 失败不降级
