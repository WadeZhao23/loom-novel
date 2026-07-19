# evals · loom 的离线 eval harness(开发期 / CI 工具)

> 一句话:**改了 prompt / 换了模型 / 动了流水线后,跑一遍就知道生成质量是涨了还是回归了。**

## 它是什么 / 不是什么

| 是 | 不是 |
|---|---|
| 开发者 & CI 用的**回归评测**:在固定数据集上给引擎产出打分 | ❌ 运行时给用户的书打分 |
| 复用你已有的检测器(`aitell` / `gates` 复审)做**度量** | ❌ 一个新的「检测分数 KPI」 |
| 有回归就让 CI **红灯**,逼你正视质量下滑 | ❌ 阻断用户出稿 |

**守 [ADR-0002](../docs/adr/0002-fingerprint-purpose-and-division.md)「过检测不当 KPI」/ [ADR-0006](../docs/adr/0006-quality-gates-issue-driven-non-blocking.md)「不打分不阻断」**:产品里的 `gates` 面向**用户的某一章**、只挑硬伤不打分;这里的 eval 面向**引擎的某个版本**、为了回归对比才聚合成分数。两者目的不同、互不替代。

## 两套 suite:Fixture vs Generation

`evals/` 下实际是两条独立流水线,分工不同,别混:

| | Fixture suite(`evals/cases/` + `run_eval`) | Generation suite(`evals/gen_cases/` + `generate`) |
|---|---|---|
| 测的是什么 | grader 本身准不准(评测器自测) | loom 五 Agent 流水线的真实生成质量 |
| 输入 | 固定文本(`chapter.md`),不调用任何模型 | 固定 case(细纲/设定等 overlay)真调 `run_pipeline` |
| 要不要 key | 零 key、零联网 | demo 模式零 key(占位后端只证链路);`--backend configured` 才要 key |
| 什么时候跑 | 每次 push/PR 进 CI(`--gate`) | 手动/定时跑,**不进 PR CI** |
| 产物 | 无(分数只在内存里比对) | 落 `evals/runs/<run_id>/`(已 gitignore,不进版本库) |
| 命令 | `python -m evals.run_eval` | `python -m evals.generate` |

两套互不替代、也互不喂料:Fixture suite 保证「grader 没坏」,Generation suite 回答「生成质量
是不是真的变好/变差了」。Generation 的产出**不能**拿去更新 Fixture 的 `baseline.json`——demo
后端是罐头文本,口径完全不同;真机产出也因为没有 seed(见下文「不可复现声明」)不适合直接冻成
金标基线。Generation suite 的完整用法见后面「Generation suite:真调生成质量」一节。

### 退出码

| 命令 | 退出码 | 含义 |
|---|---|---|
| `run_eval`(不带 `--gate`) | 0 | 跑完打分(具体哪条 case 过没过看表格,不影响这个码) |
| `run_eval --gate` | 0 | 和基线比对,无回归 |
| `run_eval --gate` | 1 | 检测到质量回归——**CI 红灯就靠这个码** |
| `run_eval --gate` / `--baseline` | 2 | infra 问题:case 目录是空的 / 基线文件不存在,**不是质量回归** |
| `generate`(demo / configured) | 0 | 跑完(单条 case 的 ✅/❌ 只体现在打印和 `report.json` 里,不改变进程退出码) |
| `generate` | 2 | infra 问题:`gen_cases/` 目录不存在 / 指定的 `--case` 找不到 |

关键差异:`run_eval --gate` 把「回归」单独留成 1,好让 CI 只在这一种情况下拦人;`generate`
是手动/探索工具,不接 CI 门禁,目前没有为「这条 case 没通过」单开退出码——想知道结果,看命令行
打印的 ✅/❌ 或 `run_dir/report.json` 里的 `"passed"`。

## Fixture suite 怎么跑

```bash
# 1) 离线跑确定性 grader(不联网、不花钱),打印评分表
python -m evals.run_eval

# 2) 额外跑 LLM 复审 grader(离线默认走 DemoBackend 占位;要真评测见下)
python -m evals.run_eval --judge

# 3) 把当前结果存成基线
python -m evals.run_eval --baseline

# 4) 和基线比对,有回归则退出码 1 —— 这一条进 CI
python -m evals.run_eval --gate
```

### 真·LLM 评测(用真实模型当 judge)

默认 `--judge` 走离线 `DemoBackend`(占位,只为证明链路通)。要用真实模型复审:在一个配好后端的 loom 项目里 `unset LOOM_DEMO` 并备好 `.env`,judge 就会用 DeepSeek / Claude / Codex 实际复审。建议复审走便宜模型(`cheap_model`)。

## 评分维度(grader)

| grader | 类型 | 复用(经 `loom.evalapi`) | 看什么 |
|---|---|---|---|
| 长度达标 | 确定性 | — | 正文字数是否在目标 ±容差内 |
| 去AI味·确定性 | 确定性 | `detect_aitell` | 「不是A而是B」这类 AI 翻转句命中数(先过写作指纹 anchor 豁免) |
| 关键要素 | 确定性 | — | 必含项(主角/钩子)在不在、禁止项(设定漂移如「二中/一阶0级」)有没有冒出来 |
| 风格相似·像你 | 确定性 | `segment_sentences` | 生成稿到**作者真稿样本**的风格距离(纯字符串统计,口径见下节);case 里给了 `author_ref` 才启用,不给 `min_style_sim` 阈值就只观测不 gating |
| 指纹生效·A/B | 确定性 | `segment_sentences` | A/B 型 case 专用:「学过的指纹」产出是否比「中性默认指纹」产出**显著更接近**作者真稿(`min_style_gap`) |
| 质检·LLM | LLM-judge | `CRITIC_质检` + `parse_critic_verdict` | OOC / 设定漂移 / 断钩子 / 无爽点 / 信息越界 |
| 去AI味·LLM | LLM-judge | `CRITIC_去AI味` + `parse_critic_verdict` | LLM 视角下的 AI 腔命中 |

权重见 `harness.run_case`;一条 case「通过」= 所有 gating grader 都过。

**接缝约定**:evals 对 loom 的所有复用只走公共门面 [`loom/evalapi.py`](../loom/evalapi.py),不 import
loom 的私有符号;门面 import 失败**不降级**——被测物坏了评测当场崩、`--gate` 红(见下文「验证门禁真的会红」)。
引擎内部随便重构,但要保住 evalapi 里的名字和签名。

## 风格相似度(「越写越像你」):度量口径与局限

这是产品核心卖点「越写越像你」(ADR-0001/0005)在 evals 里的**回归度量**——此前 5 个 grader
全是"客观质量"维度,没有一个度量"生成稿更像指纹持有者",这一节补上这块。

**口径**(`graders.style_metrics`,纯字符串统计、零依赖、不发网、不引入向量库/embedding——守 CONTEXT 红线):

| 特征 | 算法 | 抓什么 |
|---|---|---|
| 句长分布 | 分桶(≤4/8/12/18/26/40/40+ 字)→ 1−JS散度 | 短句切碎 vs 长句连缀的节奏 |
| 标点频率 | 固定标点集的计数向量余弦 | 句号/逗号/破折号/省略号的使用配比 |
| 虚词频率 | 固定虚词+腔调副词清单(「仿佛/缓缓/瞬间/的地得…」)的计数向量余弦 | AI 默认腔高频词 vs 作者用词习惯 |
| bigram重合 | 汉字二元组集合 Jaccard | 措辞/口头禅级别的短语重合 |

综合相似度 = 四者均值(0~1);句切用 `loom.evalapi.segment_sentences`(即 fingerprint 的引号感知句切),与 learn 的对齐口径一致。A/B 型 case
(`case_03_style_ab`)是「指纹在生效」的**最小可证伪实验**:同一章、同一场景纲,唯一变量是指纹
(中性默认 vs 学过作者手改),断言学过版到真稿的相似度差 ≥ `min_style_gap`;score 把差距归一
(差距=阈值→0.5、≥2×阈值→1.0)进基线,差距缩水即回归。作者真稿参照系刻意选**不同场景**的片段,
避免把内容重合冒充风格相似。

**局限(诚实边界)**:
- **风格距离 ≠ 像你本人**。四个特征只覆盖节奏/标点/虚词/短语这类表层统计,抓不到叙事视角、
  幽默感、意象偏好这类深层嗓音;分数高只说明表层风格收敛,是**回归信号**,不是「像你」的证明。
  「越写越像你是否肉眼可见」仍要靠真稿压测(见 ADR-0005 的收口条件)。
- 文本越短越噪(几百字的样本,分布估计本来就糙);bigram 重合对不同场景的文本天然偏低,看 Δ 别看绝对值。
- 只和**这一份**作者样本比:样本换人/换风格,基线就得重打。
- **红线**:此分数只活在 evals 里给开发者回归用,绝不进产品 UI/用户路径——与 ADR-0002
  「过检测不当 KPI、不量化不上报」不冲突,那条约束的是产品给用户打分,这里评的是引擎版本。

## Fixture 数据集 = `cases/<id>/`

```
cases/case_01_clean/
  case.json     # 期望:must_include / must_not_include / max_aitell_hits / len_tolerance / setting
  chapter.md    # 被测产出(固定 fixture;也可换成 loom 现跑的某章)
```

A/B 型 case(`case.json` 里 `"type": "style_ab"`)则含 `author_ref.md`(作者真稿样本)+
`chapter_neutral.md` / `chapter_learned.md`(同一章的两份产出),只跑风格 grader。

仓库自带三个 case:
- `case_01_clean` —— 干净基准,**应当 PASS**。
- `case_02_flawed` —— `case.json` 里 `"case_type": "detector_contract"`:故意埋了 1 句 AI 翻转句 +
  1 处设定漂移(二中)+ 漏写师姐,`expect_fail_graders` 声明了「关键要素」「去AI味·确定性」这两个
  grader 必须命中缺陷。**契约语义**:声明的 grader 如约命中缺陷 = 契约成立 = 本 case 判定
  ✅PASS;哪天检测器漏抓了缺陷,这条 case 才会变 ❌FAIL——FAIL 在这里代表「检测器失灵」,
  不是「文本质量差」(文本本来就是故意写坏的)。
- `case_03_style_ab` —— 指纹生效性 A/B:学过的指纹产出须比中性默认指纹产出显著更接近作者真稿,**应当 PASS**;两份 fixture 对调即 FAIL(可证伪)。

**加一个 case**:新建 `cases/<id>/`,写 `case.json` + `chapter.md` 即可。想固化一份**真实生成**的
产出做 Fixture 基线,就用 `loom write N` 跑一章(或跑下面的 Generation suite),把终稿拷成某个
case 的 `chapter.md`,再 `--baseline` 固化当前水平——注意这只是「拿真实文本当固定输入」,和
Generation suite 直接真调流水线评「生成质量」是两回事(见下一节)。

## 进 CI(回归门禁)

已落地为 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml):每次 push / PR 在
ubuntu + windows 双平台跑全量 `pytest` + `python -m evals.run_eval --gate`(只含确定性
grader,零 key 零成本)。`evals/baseline.json` 已提交;有回归 → 退出码 1 → CI 红灯挡合入。
改 prompt 让某 case 掉分超过容差、或从通过变失败,CI 直接拦住。

基线更新:确认新分数是「有意为之的改进」后,本地 `python -m evals.run_eval --baseline`
重新固化,连同引起变化的改动一起提交。

### 验证门禁真的会红(动了 evals ↔ loom 接缝后必做)

门禁最危险的失败模式是「被测物坏了,门禁却绿」。evals 对 loom 的复用全走
`loom/evalapi.py` 且 import 失败不降级,所以「门禁会红」可以直接自证:

```bash
# 1) 故意改坏接缝任意一端:门面背后的私有实现……
sed -i.bak 's/^def _segment(/def _segment_broken(/' loom/fingerprint.py
#    ……或门面公共名本身
# sed -i.bak 's/as segment_sentences/as segment_sentences_broken/' loom/evalapi.py

# 2) 门禁必须红(ImportError 直指断掉的接缝,退出码非 0);
#    若仍是 0,说明有人又引入了静默降级,先修掉它
python -m evals.run_eval --gate; echo "exit=$?"     # 期望 exit≠0

# 3) 恢复,门禁必须回绿
mv loom/fingerprint.py.bak loom/fingerprint.py
python -m evals.run_eval --gate; echo "exit=$?"     # 期望 exit=0
```

本仓库在落地 ci.yml 时按上面步骤实测过:两种破坏方式 exit 均为 1,恢复后回 0。

## Generation suite:真调生成质量

Fixture suite 只验证「grader 没坏」,不碰模型。Generation suite 反过来:真铺一个
loom 项目、真调五 Agent 流水线生成候选正文,再复用同一批 grader 打分——回答的是
「prompt 变了 / 换模型了,生成质量是涨是跌」。复用照样只走 `loom.evalapi`。

### 数据集 = `gen_cases/<id>/`

```
gen_cases/gen_01_mine_rebirth/
  case.json                     # id / chapter_n / chapter_chars / expect(同 Fixture 口径)/ note
  overlay/正文/.细纲/第1章.md     # 固定细纲,旁路大纲师(细纲文件已存在 → WYSIWYG,不再调模型生成细纲)
```

`overlay/` 下的文件按相对路径原样铺进 scaffold 生成的空白项目(想固定设定/人物卡,
就往 `overlay/设定/...`、`overlay/人物卡/...` 放);没被 overlay 覆盖的部分吃 scaffold
模板缺省值——同样是固定输入,不是随机生成。

### 怎么跑

```bash
# demo 冒烟:LOOM_DEMO=1 占位后端,零 key,只证「链路通」,不证明「prompt 变化影响了输出」
LOOM_DEMO=1 python -m evals.generate --case gen_01_mine_rebirth

# 真机:走项目/用户配置的真实后端,要 key
python -m evals.generate --case gen_01_mine_rebirth --backend configured

# 临时换 provider/model 对比(不改配置文件)
python -m evals.generate --case gen_01_mine_rebirth --backend configured --provider deepseek --model deepseek-v4-pro

# 不给 --case 就把 gen_cases/ 下全部 case 跑一遍
python -m evals.generate --backend configured
```

key 走 `~/.loom/.env`(用户级默认,跨项目继承)或临时项目自己的 `.env`(`generate` 铺的是
`tempfile.mkdtemp()` 出来的一次性项目,没有自己的 `.env`,所以天然回退到用户级默认)。

跑完打一行 `✅/❌ <case_id>  score=<分数>  → <run 目录>`;产物落
`evals/runs/<run_id>/{manifest.json, report.json, case.json, chapter.md}`,这个目录已经
gitignore(`.gitignore` 里 `evals/runs/` 那一行),不会进版本库,也不会污染 `git status`。

### `manifest.json` 字段

| 字段 | 含义 |
|---|---|
| `backend_mode` | `demo` / `configured` / `injected(测试)`(测试注入 `ScriptedBackend` 时) |
| `backend_class` | **实际在跑的**后端类名(如 `DemoBackend`)。demo 模式下 `provider`/`model` 仍是 scaffold 项目配置里的缺省值(一份「配置残影」,并没有真的被拿去调用)——想知道这次到底是谁在生成,以 `backend_class` 为准,不要看 `provider` |
| `provider` / `model` | 项目配置值;`configured` 模式下这才等于真实调用的供应商/模型 |
| `prompt_hash` / `dataset_hash` | system prompt 集合 / case 数据目录内容的指纹,用来核对「这次跑的是不是同一套输入」 |
| `calls[]` | 每次模型调用的 system prompt 摘要(sha)、user/output 字符数、耗时 |
| `tokens` / `cost` | **恒为 `null`**——现在的 Backend 协议不回传 `usage`(`loom/backends.py` 里 `resp.usage` 被丢弃了),字符数是目前唯一能拿到的代理指标,不是漏填,是还没有这条数据通道 |
| `retries` | 恒为 `0`——`run_pipeline` 没有内建重试,失败就直接抛异常;断点续跑是跨进程级别的机制,不计在这里 |

**不可复现声明**:这条链路没有 seed 通道,同一个 case 跑两次不保证字符级甚至语义级一致——
这是当前 Backend 协议的现实,不是缺陷。判断「这次 prompt 改动到底有没有让生成变好」,
应该看**多次运行的分数分布**(比如同一 case 连续跑 5 次的区间),而不是拿单次结果定生死。

## Judge 校准数据集(Phase 2)

`evals/` 下其实是**三套**数据,不是两套:

| | Fixture(`evals/cases/`) | Generation(`evals/gen_cases/`) | **Judge 校准(`evals/dataset/`)** |
|---|---|---|---|
| 测的是什么 | grader 本身准不准 | 流水线生成质量 | **LLM judge(质检/去AI味复审)本身判得准不准** |
| 输入 | 固定 `chapter.md` | 固定 overlay,真调流水线 | 固定 `chapter.md` + 8 维显式标注(`case.json` 的 `labels`) |
| 金标来源 | 人写的期望值(`must_include` 等) | 无金标,只看分数回归 | **构造性**:先决定注入什么缺陷,再照注入清单填标签 |

第三套的数据结构、8 维定义(`DIMENSIONS`,与 `loom/gates.py` 里 `CRITIC_质检`/`CRITIC_去AI味`
硬伤原文一一对应)、rubric 操作化(`evals/dataset/rubric.md`)、schema 校验器
(`evals/dataset.py`)都已就位,详见 `evals/dataset/rubric.md` 开头的说明和
`evals/dataset.py` 顶部 docstring。这一节只讲这套数据的**含义与局限**,以及第三方读者
（或未来的你)如何把它用起来。

### 构造性金标的含义与局限

`evals/dataset/cases/<id>/case.json` 里的 `labels` 是**造出来的**,不是标出来的:每条
case 先由造数据的人决定"这一章要注入哪个硬伤",再照着注入清单反填 8 维标签。这保证了
标签内部自洽(校验器能核验 evidence 是不是正文子串、absence 型缺陷不许带引文),但
**这不能代替人工校准**——没有任何独立于构造过程的人,单纯读 context + chapter.md,
在不知道"这里被故意造了什么"的前提下,重新做出同样的 8 维判断。换句话说:标签为真是
因为缺陷是造的,不是因为有人真的认为它是硬伤。

这套构造性金标现在能做的事,是验证**校验器 / harness 管线没坏**(schema 对不对、
evidence 子串核验有没有生效)。它现在还不能做的事,是回答"这套 rubric 在真实/更模糊的
文本上,是否还能让两个不同的人做出一致判断"——这就是为什么还需要人工标注:
`evals/dataset/annotations/README.md` 如实记录了现状(零人工标注)和 Phase 3 的预注册
指标(人-人一致性 Cohen's κ,目标 ≥0.70,要在两名标注者独立标注 `calibration` split
之后才存在)。

### 如何开始标注

需要第二个人(不了解本仓库也没关系)按 `evals/dataset/ANNOTATION_GUIDE.md` 的流程,
对 `calibration` split 的 case 独立标注,产出 `evals/dataset/annotations/<case_id>.
<annotator_id>.json`。指南是自包含的:标注单位、标注纪律(只依据 rubric、不脑补、
不看他人结果、不看 `case.json` 里的金标 `labels`)、边界情形怎么记 note、工作表命名
和优先标注哪个 split,都写在那份文档里,这里不重复。

## Judge 校准:结构化输出 + meta-eval(Phase 3)

Phase 2 把 8 维数据集和 rubric 铺好了;Phase 3 在此之上补三件事:让 Judge 吐**可对账的
结构化 verdict**、把「Judge 判得准不准」量化成**可预注册的指标**、以及把「标注者不该看到
金标」从纪律条款变成**工具约束**。

### 结构化 Judge:`evals/judge.py`

```bash
# demo 冒烟(占位后端,不吐合法 JSON → 预期 infra_error,只证链路通)
python -m evals.judge --backend demo

# 真机(要配好后端/key)
python -m evals.judge --backend configured --out evals/runs/judge_verdicts.jsonl

# 只跑一个 case
python -m evals.judge --case ds_03_hook --backend configured
```

`judge_case` 把判据(引擎 `CRITIC_质检`/`CRITIC_去AI味` + `rubric.md` 操作化细则)喂给
后端,要求输出**严格 JSON 数组**(8 维、每维 `dimension`/`present`/`severity`/`evidence`/
`reason`),`parse_judge_verdict` 逐字段校验(维度需恰好覆盖 8 维不重不漏、`severity` 只在
`present=true` 时必填且 ∈ {高,中,低})。**后端异常或解析失败一律判 `infra_error`,绝不
假装"全维干净"**(P0-C 教训:静默把失败伪装成通过,会悄悄拉低高代价维的 recall)。

### 校准 meta-eval:`evals/calibration.py`

纯函数库(无 CLI,当前由测试驱动;接线进 `judge.py`/CI 属未来工作):

| 函数 | 算的是什么 |
|---|---|
| `cohen_kappa(a, b)` | 两个等长标签序列的 Cohen's κ(扣偶然一致后的一致性) |
| `prf_for_dimension(gold, pred)` | 单维度的 precision/recall/f1;分母为 0 记 `None`(未定义,不伪造 0/1) |
| `aligned_matrices(gold_cases, judge_results)` | 按 `case_id` 对齐金标与 Judge 结果、滤掉 infra case,杜绝「等长但顺序错位」的静默污染 |
| `build_calibration_report(gold, judge, human_pairs)` | 汇总成报告;`judge`/`human_pairs` 缺省时对应段如实留空位(`"待真机"`/`"待标注"`),不造数 |
| `write_report(report, out_dir)` | 落 `report.json` + `report.md` |

11 例数据集每维正例仅 1-2 个,总体 accuracy 会被大量 absent 格灌水,所以只看 κ(整体
一致性)和分维 recall(高代价维单独盯),不产「总体分」——继续守 ADR-0002「不打分」。

### 预注册阈值:`evals/calibration/targets.json`

```json
{
  "kappa_human_human": 0.70,
  "kappa_judge_gold": 0.60,
  "high_cost_recall": 0.85,
  "high_cost_dimensions": ["信息边界", "设定漂移"]
}
```

**预注册**的意思是:这份阈值在任何真实校准结果算出来之前就已提交进版本库,git 历史证明
它不是看完分数倒推出来的。达标的维度才可晋级为硬门禁(Phase 4);当前都还没有真实数字。

### 无剧透标注包导出:`evals/export_packets.py`

```bash
# 全部 case 一键导出成无剧透标注包(每个 case 一个子目录)
python -m evals.export_packets --out /tmp/annotate_export

# 只导 calibration split(κ 校准优先标这个)
python -m evals.export_packets --out /tmp/annotate_export --split calibration
```

`export_packet(case_dir, out_dir)` 只读 `case.json` 的 `context` 四键(`setting`/
`characters`/`prev_hook`/`chapter_goal`)+ `chapter.md`,**不 copy 整个 `case.json`**——
`labels`/`construction_note`/`detector_note` 这些金标字段从代码路径上就够不着,而不是靠
标注者自律「别打开」。这是把 `ANNOTATION_GUIDE.md`「最稳的做法」从人工纪律变成结构保证
(T6 审查发现 `case.json` 含金标剧透之后的工具化收口)。

### 诚实边界(Phase 3 收工时的真实状态)

- **`kappa_judge_gold`(Judge vs 构造性金标)待真机**:`judge.py` 的 demo 后端只证链路通,
  不吐合法 JSON,真实数字要接一个配好 key 的后端跑一遍 `evals/dataset/cases/` 全集才有。
- **`kappa_human_human`(人-人一致性)待标注**:需要至少两名独立标注者按
  `ANNOTATION_GUIDE.md` 标完 `calibration` split,`build_calibration_report` 的
  `human_human_kappa` 字段现在如实写着 `"status": "待标注"`,不是空白就是没做,是做了但
  数据还不存在。
- 这两个数字出来之前,`targets.json` 里的阈值都只是**待验收标准**,不是「已达标」的宣称——
  报告里刻意留空位,而不是拿构造性金标的自洽性冒充人工验证。

## 分层 CI + 评测报告(Phase 4)

两条 CI 通道,按「零 key 还是要 key」分层——这是整套 eval 能安全进 CI 的关键:

```
PR / push ──→ ci.yml(每次都跑)
                ├─ pytest 全量(含 FakeBackend Judge 合同测试,零 key)
                ├─ evals.run_eval --gate(确定性门禁,零 key,有回归退出码 1 挡合入)
                └─ 生成 fixture 评测报告 → 上传 artifact(shell:bash + continue-on-error:
                   报告生成失败只降级留痕,绝不否决已通过的门禁)

手动 / 每周一 ──→ eval-real.yml(workflow_dispatch + schedule)
                └─ evals.judge --backend configured --calibrate(真调 LLM Judge,要 key)
                   → 校准报告上传 artifact
```

**为什么分层**:fork PR 读不到仓库 secret(GitHub 的机制,防 fork 恶意代码窃密),`pull_request_target` 又会把 secret 暴露给 fork 代码(pwn request)。所以真 Judge 只挂 `workflow_dispatch`+`schedule`(仅仓库自身触发),PR CI 永远零 key、零成本、双平台稳过。`eval-real.yml` 用最小 `contents: read` 权限,不碰发版流程。

**要真跑 eval-real,你得先加一个 repo secret**(Claude 不能也不应代加密钥):

> GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret
> 名字 `DEEPSEEK_API_KEY`(或所配 provider 的 key 名),值填你的 key。
> 没加时 workflow 会 `exit 2` 如实报「缺 key = infra 缺失」,**不会伪装成质量 PASS**。

**门禁策略 `evals/calibration/gating.json`**:每个维度一个策略——`observe`(只记录不拦截)/ `soft`(警告不拦截)/ `hard`(参与门禁拦截)。**现在 8 维全 `observe`**。任一维度要晋级 `soft`/`hard`,必须先有 Phase 3 校准报告证明它达标(κ/recall 过预注册阈值),不凭印象晋级(ADR-0002)。晋级本身是一次可审查的 `gating.json` diff,不在本期。

**评测报告 `evals/report.py`**:把三套 suite 的结果(Fixture 门禁 / Generation manifest / Judge 校准)合成 JSON + MD 上传 artifact,构成「commit → 模型 → prompt hash → 结论」的可追溯链。报告**禁止只看加权总分**:高代价维(信息边界 / 设定漂移)的 recall 在校准段**单列**;缺哪源就如实标「未跑 / 待真机」,不造数;真 Judge 一次 infra 掉了 case,报告披露「N 例中 M 例掉出、只在 K 例上算」,不把子集标成全量。

## 为什么要有它(写给作者自己)

你已经有了 eval 的**零件**(aitell / gates 复审 / fatigue),缺的是把它们**组织成可回归的度量**。有了这层:① 调 prompt 不再「凭感觉变好了」,有数;② 换模型能一眼看出哪类质量掉了;③ 这套「数据集 + 复用检测器打分 + 回归门禁」本身,就是一份能讲的 eval engineering 实证。
