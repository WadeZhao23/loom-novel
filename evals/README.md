# evals · loom 的离线 eval harness(开发期 / CI 工具)

> 一句话:**改了 prompt / 换了模型 / 动了流水线后,跑一遍就知道生成质量是涨了还是回归了。**

## 它是什么 / 不是什么

| 是 | 不是 |
|---|---|
| 开发者 & CI 用的**回归评测**:在固定数据集上给引擎产出打分 | ❌ 运行时给用户的书打分 |
| 复用你已有的检测器(`aitell` / `gates` 复审)做**度量** | ❌ 一个新的「检测分数 KPI」 |
| 有回归就让 CI **红灯**,逼你正视质量下滑 | ❌ 阻断用户出稿 |

**守 [ADR-0002](../docs/adr/0002-fingerprint-purpose-and-division.md)「过检测不当 KPI」/ [ADR-0006](../docs/adr/0006-quality-gates-issue-driven-non-blocking.md)「不打分不阻断」**:产品里的 `gates` 面向**用户的某一章**、只挑硬伤不打分;这里的 eval 面向**引擎的某个版本**、为了回归对比才聚合成分数。两者目的不同、互不替代。

## 怎么跑

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

| grader | 类型 | 复用 | 看什么 |
|---|---|---|---|
| 长度达标 | 确定性 | — | 正文字数是否在目标 ±容差内 |
| 去AI味·确定性 | 确定性 | `loom.aitell.detect` | 「不是A而是B」这类 AI 翻转句命中数(先过写作指纹 anchor 豁免) |
| 关键要素 | 确定性 | — | 必含项(主角/钩子)在不在、禁止项(设定漂移如「二中/一阶0级」)有没有冒出来 |
| 风格相似·像你 | 确定性 | — | 生成稿到**作者真稿样本**的风格距离(纯字符串统计,口径见下节);case 里给了 `author_ref` 才启用,不给 `min_style_sim` 阈值就只观测不 gating |
| 指纹生效·A/B | 确定性 | — | A/B 型 case 专用:「学过的指纹」产出是否比「中性默认指纹」产出**显著更接近**作者真稿(`min_style_gap`) |
| 质检·LLM | LLM-judge | `loom.gates.CRITIC_质检` | OOC / 设定漂移 / 断钩子 / 无爽点 / 信息越界 |
| 去AI味·LLM | LLM-judge | `loom.gates.CRITIC_去AI味` | LLM 视角下的 AI 腔命中 |

权重见 `harness.run_case`;一条 case「通过」= 所有 gating grader 都过。

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

综合相似度 = 四者均值(0~1);句切与 `loom.fingerprint._segment` 同口径。A/B 型 case
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

## 数据集 = `cases/<id>/`

```
cases/case_01_clean/
  case.json     # 期望:must_include / must_not_include / max_aitell_hits / len_tolerance / setting
  chapter.md    # 被测产出(固定 fixture;也可换成 loom 现跑的某章)
```

A/B 型 case(`case.json` 里 `"type": "style_ab"`)则含 `author_ref.md`(作者真稿样本)+
`chapter_neutral.md` / `chapter_learned.md`(同一章的两份产出),只跑风格 grader。

仓库自带三个 case:
- `case_01_clean` —— 干净基准,**应当 PASS**。
- `case_02_flawed` —— 故意埋了 1 句 AI 翻转句 + 1 处设定漂移(二中)+ 漏写师姐,**应当 FAIL**,用来证明 grader 真抓得到。
- `case_03_style_ab` —— 指纹生效性 A/B:学过的指纹产出须比中性默认指纹产出显著更接近作者真稿,**应当 PASS**;两份 fixture 对调即 FAIL(可证伪)。

**加一个 case**:新建 `cases/<id>/`,写 `case.json` + `chapter.md` 即可。想评真实生成质量,就用 `loom write N` 跑一章,把终稿拷成某个 case 的 `chapter.md`,再 `--baseline` 固化当前水平。

## 进 CI(回归门禁)

```yaml
# .github/workflows/eval.yml
- run: pip install -e .
- run: python -m evals.run_eval --gate   # baseline.json 已提交;有回归 → 退出 1 → CI 红灯
```

第一次先本地 `--baseline` 生成 `evals/baseline.json` 并提交;之后每个 PR 自动比对。改 prompt 让某 case 掉分超过容差、或从通过变失败,CI 直接拦住。

## 为什么要有它(写给作者自己)

你已经有了 eval 的**零件**(aitell / gates 复审 / fatigue),缺的是把它们**组织成可回归的度量**。有了这层:① 调 prompt 不再「凭感觉变好了」,有数;② 换模型能一眼看出哪类质量掉了;③ 这套「数据集 + 复用检测器打分 + 回归门禁」本身,就是一份能讲的 eval engineering 实证。
