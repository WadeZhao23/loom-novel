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

## 为什么要有它(写给作者自己)

你已经有了 eval 的**零件**(aitell / gates 复审 / fatigue),缺的是把它们**组织成可回归的度量**。有了这层:① 调 prompt 不再「凭感觉变好了」,有数;② 换模型能一眼看出哪类质量掉了;③ 这套「数据集 + 复用检测器打分 + 回归门禁」本身,就是一份能讲的 eval engineering 实证。
