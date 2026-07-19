# Loom Eval 补齐 · 路线图与设计决策(Phase 3–5)

> 本文档是「为什么这么做」的落档。逐期的「怎么做」在各自的实现计划里(见文末链接)。
> 权威需求:`/Users/chambers/Desktop/loom-novel_eval补齐计划.md`。执行流程:superpowers:subagent-driven-development。
> 分支:`navigator-reliability-p1`(与书房伙伴线共用,eval 提交正交叠加;不 push、不 merge、不发版,做完等用户验收)。

## 全景与进度

| 期 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 门禁语义可信(契约样本 / 双向 baseline / 退出码三态 / Judge 不假通过) | ✅ 完成 |
| Phase 1 | Generation suite(evalapi 接缝 → 真调五 Agent → runs 落盘 → manifest 可追溯) | ✅ 完成 |
| Phase 2 | 数据集与 rubric(8 维校验器 / 操作化 rubric / 11 例三 split / 标注工具) | ✅ 完成 |
| **Phase 3** | **LLM-Judge 校准链(结构化 verdict + κ/PRF meta-eval + 预注册阈值 + 报告)** | **← 执行中** |
| Phase 4 | 分层 CI + 评测报告(PR=fixture 零 key;手动/定时=generation+真 Judge) | ⬜ 待 |
| Phase 5 | 伙伴/领航员 agent 对话协议 eval(**新范围**,待用户拍板) | ❓ 待定 |

截至 Phase 2 收口:全量 **618 passed**、fixture `--gate` 码 0、generation demo 跑通。

## 贯穿全程的第一原则

1. **两套 suite 分离**:Fixture suite(评测器自测,零 key,进 PR CI)与 Generation/Judge suite(被测系统质量,要 key 或 demo,手动/定时)。这是整个补齐计划的骨架——面试时能诚实区分「评测器不坏」与「生成质量回归」。
2. **不造数(spec §5 红线)**:凡是需要真人或真模型才能产生的数字(κ人人、Judge-金标 κ、真机 token/成本),工具与计算全部先建好并用合成夹具 TDD,但报告里如实标「待标注 / 待真机」,**绝不用计划阈值冒充已实现结果**。
3. **产品侧红线不破(ADR-0002 / ADR-0006)**:分数、阈值、κ 只存在于 `evals/`,产品 `gates.py`/`parse.py`/UI 一个字不动;评测只走 `loom.evalapi` 门面,import 失败不降级。
4. **可追溯**:每次 generation/judge run 的 manifest 记 git commit + provider + 精确 model + prompt/dataset hash;报告能回放到具体 commit。

---

## Phase 3:LLM-Judge 校准链

### 目标

把 Judge 从「自由文本 + `_parse_verdict`」升级成**结构化 JSON verdict**,并建立 meta-eval(Cohen's κ + 每维 P/R/F1)与预注册阈值,产出可追溯的校准报告——真实的人-人 / Judge-人一致性数字**留空位等真标注**。

### 架构

```
evals/judge.py            结构化 Judge(eval 侧,产品永不 import)
  ├ DimensionVerdict      {dimension, present, severity∈{高,中,低,null}, evidence, reason}
  ├ build_judge_prompt    system = CRITIC_质检+CRITIC_去AI味(经 evalapi,引擎权威判据)
  │                                + rubric.md 操作化细节(严重度/证据/边界)
  │                                + 严格 JSON 输出指令(覆盖 8 维);user = context四键+chapter
  ├ parse_judge_verdict   严格解析:非法 JSON / 维度越界 / 缺维 / 非法 severity → JudgeParseError
  └ judge_case            跑一例:后端失败 OR 解析失败 → infra_error(不假通过,延续 P0-C)
evals/calibration.py      纯函数 meta-eval
  ├ cohen_kappa           扣除偶然一致的一致性
  ├ per_dimension_prf     每维 precision/recall/f1/tp/fp/fn
  └ evaluate_against_targets  指标 vs 预注册阈值(纯比较,不调参)
evals/calibration/
  ├ targets.json          预注册阈值(先提交=git 证明没事后倒推)
  ├ report.json / .md     报告生成器(缺数据的格子如实留空位)
evals/export_packets.py   无剧透标注包导出(context四键+chapter,替代标注者自律)
```

### 关键设计决策与理由

**① 结构化 JSON verdict,但住在 eval 侧、判据单源自 evalapi+rubric。**
产品 `gates.py` 的 CRITIC 输出自由文本,且**必须保持**——`events.py`/前端在消费 `Issue` 的中文 key 结构(`类别/问题/证据`),改它就破事件契约;ADR-0002 又禁止产品侧出分数。所以结构化 Judge 是一个**独立的 eval 侧层**:它的 system prompt = `CRITIC_质检`+`CRITIC_去AI味`(经 evalapi 导入,引擎的权威维度判据)+ `rubric.md`(Phase 2 已逐字对齐 CRITIC 的操作化细节)+ **只替换输出格式指令**为严格 JSON。判据仍单源(引擎改 CRITIC → 导入变 → Judge 变),不是「复制另一套 prompt」(spec 明禁),只是换了输出形状好逐维对账。

**② severity 用类别 {高,中,低,null},不用数值分。**
逐维可判对错才能算 κ;但一旦引入数值 score 就滑向「总体文学分」(ADR-0002 红线,rubric 也明禁)。类别型 severity 与 rubric 分级一一对应,既够算一致性又不越线。

**③ 后端/解析失败 = infra_error,不假通过。**
延续 P0-C:Judge 后端挂了或吐出非法 JSON,返回 infra 三态(passed=False + detail[infra]),绝不当成「无硬伤=质量 PASS」。这也是 Phase 4 真 Judge 进 CI 时「后端不可用报 infra 不伪装 PASS」的地基。

**④ κ + 每维 P/R/F1,不用总体准确率。**
11 例数据集每维正例仅 1–2 个,总体准确率会被约 79 个 absent 格灌水到 90%+ 而无意义。κ 扣除偶然一致;分维 recall 让高代价维(信息边界/设定漂移)单独受检——直接支撑 Phase 4「禁止只看加权总分,高代价维单独门禁」。

**⑤ 阈值预注册进版本库。**
spec 明令「先预注册验收标准再看结果,禁止看完分数倒推阈值」。`targets.json` 先提交,git 历史即「没事后调阈值」的证据。初始目标(是待验收标准、非当前事实):人-人 κ≥0.70、Judge-金标每核心维 κ≥0.60、高代价维 recall≥0.85。

**⑥ 报告留诚实空位。**
κ人人 需两名真人对 calibration split 独立标注(唯一不可自动化环节);Judge-金标 κ 需真机跑 Judge(花 API 费)。二者的工具/计算/报告器全部 TDD 建好,但报告里这两格写「待标注 N=0」「待真机」——面试只报报告里的真实数字。

**⑦ 标注包导出工具化(吸收 Phase 2 T6 审查发现)。**
`case.json` 里的 `construction_note`/`detector_note` 构造档案字段是金标剧透;靠「标注者别看」是纪律,靠「给标注者的包里根本没有」是结构。导出脚本只吐 context 四键 + chapter,结构上杜绝泄露。

**⑧ 吸收三个挂账项**:`dataset.py` 的 dimension 字段类型防御(P2.T1 残留,非 str → 裸 TypeError)、思考型模型(DeepSeek v4 默认思考、reasoning 吃 max_tokens)的 Judge 预算 note、T6 标注指南 Minor backlog(jq 命令补 mkdir 等)。

### 验收

合成夹具全绿 + `python -m evals.judge --backend demo` 跑通(demo 只证链路)+ 校准报告生成且诚实留空位。真机 Judge 校准(改 prompt→verdict 可观察变化、算真 κ)留成文档化手动命令,等用户择时或授权。

---

## Phase 4:分层 CI + 评测报告

### 架构

```
.github/workflows/ci.yml       语义不动,仅加一步:评测报告 artifact 上传(仍零 key)
.github/workflows/eval-real.yml 新增:workflow_dispatch + schedule(周)
                                → generation suite + 真 Judge(repo secret 取 key)
                                → 样本/成本上限 → runs+报告 artifact;secret 缺=infra 红
evals/report.py                 JSON + Markdown 双格式报告(fixture/generation/judge 三源)
evals/gating.json               维度→{observe|soft|hard};初始全 observe
```

### 关键设计决策与理由

**① PR CI 永远零 key。** fork PR 读不到 secrets 是 GitHub 机制;`pull_request_target` 会把 secrets 暴露给不可信 fork 代码(pwn request 风险)。所以真 Judge 只走 `workflow_dispatch`+`schedule`——不是保守,是唯一安全解(侦察已核实:仓库现零自定义 secrets,artifact 上传仅 release.yml 有先例)。

**② Judge 初始全 observe、不进硬门禁。** spec 明令「校准后才硬门禁」「无校准报告前不让 Judge 拦发布」。`gating.json` 把「哪个维度凭什么报告晋级 hard」变成一次可审查的 diff。

**③ 报告双格式 + artifact。** JSON 给机器(趋势),MD 给人(回看/简历证据);artifact 让每次运行的结论可追溯下载,与 manifest 一起构成「commit→模型→prompt hash→结论」完整链。

**④ release.yml 的 needs 链不碰。** test→build-mac/win→release 是发版安全网,Phase 4 只加旁路 job 不插队。

**⑤ 顺序 3→4。** CI 层消费 judge/report 模块;先建 CI 只是给空槽接线。

### 需要用户侧动作

`eval-real.yml` 用的 `DEEPSEEK_API_KEY`(或所选 provider 的 key)repo secret 需用户在 GitHub 仓库设置里加;workflow 会先落地,secret 缺失时如实红(不静默跳过)。

---

## Phase 5(候选 · 新范围):伙伴/领航员 agent 对话协议 eval

现有 eval 覆盖「五 Agent 章节流水线 + 8 维 Judge」;书房伙伴/领航员对话 agent(多候选卡、协议解析、思考层)只有单测,无 eval 级回归面。真机踩过的坑(括号壳照抄漏字、协议行渲染、重复卡)值得一套对话 golden + 协议解析对抗样本集。**这是新范围,不是对 Phase 0–4 的调整**,待用户拍板后另立计划。

---

## 简历表述的解锁条件(spec §4,防过度宣称)

- 当前可诚实说:自建数据集驱动的离线 eval harness;确定性 grader + baseline 回归比较接入 CI;LLM Judge 为可选复审链,**尚未完成人工金标校准**。
- Phase 1 后解锁:Fixture CI 保评测器不回归;Generation suite 真调五 Agent 追踪 prompt/模型/架构改动。
- Phase 3–4 后才可用:人工金标 + 分维 rubric 校准的 LLM-as-Judge,以 κ/P/R/F1 验证可信性;达标维进分层门禁。**每个数字都指向已提交报告。**

---

## 逐期实现计划链接

- Phase 0:`docs/superpowers/plans/2026-07-17-eval-phase0-gate-credibility.md`
- Phase 1:`docs/superpowers/plans/2026-07-17-eval-phase1-generation-suite.md`
- Phase 2:`docs/superpowers/plans/2026-07-17-eval-phase2-dataset-rubric.md`
- Phase 3:`docs/superpowers/plans/2026-07-17-eval-phase3-judge-calibration.md`
- Phase 4:`docs/superpowers/plans/2026-07-17-eval-phase4-layered-ci.md`(待写)
