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
| 质检·LLM | LLM-judge | `loom.gates.CRITIC_质检` | OOC / 设定漂移 / 断钩子 / 无爽点 / 信息越界 |
| 去AI味·LLM | LLM-judge | `loom.gates.CRITIC_去AI味` | LLM 视角下的 AI 腔命中 |

权重见 `harness.run_case`;一条 case「通过」= 所有 gating grader 都过。

## 数据集 = `cases/<id>/`

```
cases/case_01_clean/
  case.json     # 期望:must_include / must_not_include / max_aitell_hits / len_tolerance / setting
  chapter.md    # 被测产出(固定 fixture;也可换成 loom 现跑的某章)
```

仓库自带两个 case:
- `case_01_clean` —— 干净基准,**应当 PASS**。
- `case_02_flawed` —— 故意埋了 1 句 AI 翻转句 + 1 处设定漂移(二中)+ 漏写师姐,**应当 FAIL**,用来证明 grader 真抓得到。

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
