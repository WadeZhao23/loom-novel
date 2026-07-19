# Eval 门控真拦截:hard 维度强制 + 首个校准晋级 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 让 `gating.json` 不再是空壳——`hard` 维度的 Judge recall 掉破预注册 target 就让门禁红(元门禁:校准过的 Judge 必须保持校准);并基于真机校准数据(κ=0.82,信息边界 P=R=1.0)把「信息边界」晋级为首个 hard 维度,把真实校准报告提交进库当证据。

**Architecture:** `evals/calibration.py` 加 `gate_hard_dimensions`(纯判定);`evals/judge.py` main 加 `--gate`(判定后退出码 0/1/2);`evals/calibration/gating.json` 把信息边界 observe→hard;`evals/calibration/report.{json,md}` 提交真报告 + 出处;`.github/workflows/eval-real.yml` 的 judge 调用加 `--gate`。全部 eval 侧,产品零改动。

**Tech Stack:** Python 3.11 + pytest(现基线 680 绿,在分支 `eval-gating-live`,起点=main 603259e)。零新依赖。

**权威依据:** 真机校准结果(本会话跑,deepseek-v4-pro,11 例 0 infra,整体 Judge-金标 κ=0.8231):信息边界/断钩子/无爽点/物品状态连续性/时间连续性 P=R=F1=1.0;人物OOC/设定漂移 recall=1.0 precision=0.5(均在 ds_05 一个坏 case 上多报);AI腔 recall=0.5(漏 ds_09 翻转句)。高代价维 targets=[信息边界,设定漂移],target recall≥0.85。

## Global Constraints

- **文件白名单**:改 `evals/calibration.py`(加 gate_hard_dimensions)、`evals/judge.py`(main 加 --gate)、`evals/calibration/gating.json`(信息边界→hard)、`.github/workflows/eval-real.yml`(judge 加 --gate)、`evals/README.md`;新建 `evals/calibration/report.json`、`evals/calibration/report.md`(真报告证据)、`evals/calibration/PROVENANCE.md`(出处),扩 `tests/test_eval_gating.py`、`tests/test_eval_judge_structured.py`。**不碰** 其它 eval 模块、`ci.yml`、`release.yml`、`loom/**`、`evals/dataset/**`。
- **诚实性(spec §5)**:晋级必须有已提交的真校准报告为证(本计划提交 report.*);报告/出处如实写「n=1~2/维 小样本、构造性金标、无人-人 κ、deepseek-v4-pro/日期/commit」。不夸称统计验证。AI腔 明确不晋级(recall 0.5 不达标)。
- **只晋级达标高代价维**:本计划只把 **信息边界**(P=R=1.0)翻 hard;设定漂移(precision 0.5)与其余保持 observe。晋级是可审查的 gating.json 一行 diff。
- **产品红线延续**:gate 判定只在 eval 侧;无数值 score 进产品;infra≠pass(P0-C)延续到 --gate。
- **CI 安全延续**:eval-real.yml 仍只 workflow_dispatch+schedule、contents:read、secret 缺 exit 2;ci.yml(PR 零 key)不碰。
- 既有 680 测试断言禁改(除本计划显式更新的 gating 护栏测试)。提交 `type(scope): 中文摘要`+`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件。
- 环境 `.venv/bin/python`。

## 现状锚点

- `evals/calibration.py`:`load_gating()`/`gate_policy(dim,gating)->str`/`load_targets()`/`evaluate_against_targets`/`build_calibration_report(...,dropped_infra,n_total)`(报告含 `coverage`{n_total,n_evaluated,n_infra_dropped,dropped_case_ids} + `judge_vs_gold`{dim:{tp,fp,fn,precision,recall,f1}} + `judge_vs_gold_status`)/`calibrate(gold_cases,judge_results)`。
- `evals/judge.py` main:`--case/--backend{demo,configured}/--dataset-dir/--out/--calibrate/--report-dir`;退出码 0=完成 / 2=infra(无 case 目录/找不到 case)。`--calibrate` 后 `calibrate(gold_cases,results)`→`write_report`。
- `evals/calibration/gating.json`:`{note, dimensions:{8维:"observe"}}`。`targets.json`:`{kappa_human_human:0.70, kappa_judge_gold:0.60, high_cost_recall:0.85, high_cost_dimensions:["信息边界","设定漂移"]}`。
- `tests/test_eval_gating.py::test_gating_has_no_hard_dimensions_yet`:断言无 hard——**本计划要更新它**(改成"hard 维度必须是达标高代价维且有报告为证")。
- `.github/workflows/eval-real.yml`:`python -m evals.judge --backend configured --calibrate --report-dir eval-real-report`。
- 真报告在 scratchpad `judge-calib-real/report.{json,md}`——Task 2 拷进 `evals/calibration/`。

---

### Task 1: gate_hard_dimensions 强制判定 + judge `--gate`(机制,先不晋级)

**Files:**
- Modify: `evals/calibration.py`(加 gate_hard_dimensions)
- Modify: `evals/judge.py`(main 加 --gate)
- Test: `tests/test_eval_gating.py`(扩)、`tests/test_eval_judge_structured.py`(扩)

**Interfaces:**
- Produces:
  - `gate_hard_dimensions(report: dict, gating: dict, targets: dict) -> tuple[bool, list, list]`:对每个 policy=hard 的维度,取 `report["judge_vs_gold"][dim]["recall"]`,断言 ≥ `targets["high_cost_recall"]`;recall=None(无金标正例/未评)→ 记 warning 跳过不算失败;返回 `(ok, failures, warnings)`。
  - `judge.main` 加 `--gate`:`--calibrate` 后若 `--gate`:先看 coverage.n_evaluated==0(全 infra)→ return 2;否则跑 gate_hard_dimensions,有 failures→打印+return 1,否则打印通过。退出码矩阵 0=通过/1=hard 维掉破 target/2=infra。
- Consumes: `load_gating`/`load_targets`/`gate_policy`。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_gating.py` 追加(顶部 `from evals.calibration import gate_hard_dimensions, load_targets`):

```python
def _report_with(recalls: dict):
    # 构造最小 report:judge_vs_gold 每维给定 recall
    from evals.dataset import DIMENSIONS
    jvg = {d: {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0,
               "recall": recalls.get(d), "f1": None} for d in DIMENSIONS}
    return {"judge_vs_gold": jvg}


def test_gate_passes_when_hard_dim_clears_target():
    gating = {"dimensions": {"信息边界": "hard"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": 1.0}), gating, load_targets())
    assert ok is True and failures == []


def test_gate_fails_when_hard_dim_below_target():
    gating = {"dimensions": {"信息边界": "hard"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": 0.5}), gating, load_targets())
    assert ok is False and any("信息边界" in f for f in failures)


def test_gate_ignores_observe_dims():
    gating = {"dimensions": {"信息边界": "observe", "AI腔": "observe"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": 0.1, "AI腔": 0.0}), gating, load_targets())
    assert ok is True and failures == []          # observe 不参与门禁


def test_gate_warns_on_unmeasurable_hard_dim():
    gating = {"dimensions": {"信息边界": "hard"}}
    ok, failures, warns = gate_hard_dimensions(_report_with({"信息边界": None}), gating, load_targets())
    assert ok is True and failures == [] and any("信息边界" in w for w in warns)  # 无正例→跳过不失败
```

`tests/test_eval_judge_structured.py` 追加(demo 全 infra + --gate → exit 2):

```python
def test_cli_calibrate_gate_demo_all_infra_is_infra_2(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOM_DEMO", "1")
    from evals.judge import main
    code = main(["--backend", "demo", "--calibrate", "--gate", "--report-dir", str(tmp_path / "r")])
    assert code == 2          # 全 infra + --gate → infra 退出码,不伪装通过
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_gating.py tests/test_eval_judge_structured.py -v -k "gate"`
Expected: FAIL——`cannot import name 'gate_hard_dimensions'` / main 不认 --gate。

- [ ] **Step 3: 实现**

`evals/calibration.py` 追加:

```python
def gate_hard_dimensions(report: dict, gating: dict, targets: dict) -> tuple[bool, list, list]:
    """对每个 policy=hard 的维度,断言 recall ≥ high_cost_recall target。
    recall=None(无金标正例/未评)→ 记 warning 跳过,不算失败(测不了的不能拦)。
    返回 (ok, failures, warnings)。这是「校准过的 Judge 必须保持校准」的元门禁。"""
    target = targets["high_cost_recall"]
    jvg = report.get("judge_vs_gold", {})
    failures, warnings = [], []
    for dim, policy in gating.get("dimensions", {}).items():
        if policy != "hard":
            continue
        m = jvg.get(dim)
        recall = m.get("recall") if m else None
        if recall is None:
            warnings.append(f"{dim}:无金标正例/未评,无法门禁(跳过)")
            continue
        if recall < target:
            failures.append(f"{dim}:recall {recall} < 目标 {target}")
    return (not failures, failures, warnings)
```

`evals/judge.py` main:argparse 加 `--gate`;`--calibrate` 写完报告后:

```python
        if args.gate:
            from .calibration import gate_hard_dimensions, load_gating, load_targets
            cov = report["coverage"]
            if cov.get("n_total") and not cov.get("n_evaluated"):
                print("✗ 全部 case infra,无可评例 → 门禁无法判定(infra,不伪装通过)")
                return 2
            ok, failures, warnings = gate_hard_dimensions(report, load_gating(), load_targets())
            for w in warnings:
                print(f"⚠ {w}")
            if not ok:
                print("❌ hard 维度掉破 target:")
                for f in failures:
                    print(f"   · {f}")
                return 1
            print("✅ 所有 hard 维度保持达标(或无 hard 维度)")
```

(注意:`--gate` 不带 `--calibrate` 时无报告可判——argparse 层或 main 里做:`--gate` 隐含需要 `--calibrate`,不满足则 print 提示 return 2;实现时 `if args.gate and not args.calibrate: print(...); return 2`。)

- [ ] **Step 4: 跑测试通过 + demo 冒烟**

Run: `.venv/bin/python -m pytest tests/test_eval_gating.py tests/test_eval_judge_structured.py -q` → 全绿。
Run: `LOOM_DEMO=1 .venv/bin/python -m evals.judge --backend demo --calibrate --gate --report-dir /tmp/g; echo 码=$?`
Expected: 全 infra → 码 2(gating 现在全 observe,但全 infra 先触发 infra 分支)。

- [ ] **Step 5: Commit**

```bash
git add evals/calibration.py evals/judge.py tests/test_eval_gating.py tests/test_eval_judge_structured.py
git commit -m "$(cat <<'EOF'
feat(eval): gate_hard_dimensions 强制 + judge --gate——让 gating 不再空壳(机制)

hard 维度 recall 掉破 high_cost_recall target 即失败(元门禁:校准过的 Judge 必须保持
校准);recall=None 跳过不拦(测不了的不拦)。judge --gate:全 infra→2、hard 掉破→1、
保持达标→0。本 commit 只建机制,gating 仍全 observe(晋级在下个 commit)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 晋级信息边界为 hard + 提交真校准报告证据 + 接线 eval-real + 文档

**Files:**
- Modify: `evals/calibration/gating.json`(信息边界 observe→hard)
- Create: `evals/calibration/report.json`、`evals/calibration/report.md`(真报告)、`evals/calibration/PROVENANCE.md`(出处 + 小样本 caveat)
- Modify: `.github/workflows/eval-real.yml`(judge 加 --gate)、`evals/README.md`、`tests/test_eval_gating.py`(更新护栏测试)

**Interfaces:**
- Consumes: Task 1 的 gate 机制。
- Produces: 信息边界=hard(有报告为证);eval-real.yml 真跑时强制信息边界 recall≥0.85。

- [ ] **Step 1: 更新护栏测试(先红)**

`tests/test_eval_gating.py`:把 `test_gating_has_no_hard_dimensions_yet` 替换为:

```python
def test_hard_dims_are_calibration_backed_high_cost():
    """晋级纪律:任何 hard 维度必须①是预注册高代价维、②有已提交校准报告为证。
    防凭印象把维度翻 hard(spec §Phase3/4:校准达标才晋级)。"""
    import json
    from pathlib import Path
    from evals.calibration import load_gating, load_targets
    g = load_gating()["dimensions"]
    hard = [d for d, p in g.items() if p == "hard"]
    high_cost = set(load_targets()["high_cost_dimensions"])
    for d in hard:
        assert d in high_cost, f"{d} 晋级 hard 但不是高代价维"
    report = Path("evals/calibration/report.json")
    if hard:
        assert report.is_file(), "有 hard 维度但缺 evals/calibration/report.json 校准证据"
        jvg = json.loads(report.read_text(encoding="utf-8"))["judge_vs_gold"]
        target = load_targets()["high_cost_recall"]
        for d in hard:
            assert jvg[d]["recall"] is not None and jvg[d]["recall"] >= target, \
                f"{d} 是 hard 但校准报告里 recall 未达 {target}"


def test_current_hard_is_exactly_信息边界():
    from evals.calibration import load_gating
    g = load_gating()["dimensions"]
    assert [d for d, p in g.items() if p == "hard"] == ["信息边界"]   # 本期只晋级这一项
```

Run: `.venv/bin/python -m pytest tests/test_eval_gating.py -v -k "hard"`
Expected: FAIL(gating 现在全 observe、report.json 未提交)。

- [ ] **Step 2: 拷真报告 + 写出处 + 晋级**

拷真校准报告(scratchpad → 库):

```bash
cp /private/tmp/claude-501/-Users-chambers-Desktop-Project-playground-Loom/1e6630b2-66c2-4900-9249-d6bfa243fdd2/scratchpad/judge-calib-real/report.json evals/calibration/report.json
cp /private/tmp/claude-501/-Users-chambers-Desktop-Project-playground-Loom/1e6630b2-66c2-4900-9249-d6bfa243fdd2/scratchpad/judge-calib-real/report.md  evals/calibration/report.md
```

新建 `evals/calibration/PROVENANCE.md`:

```markdown
# 校准报告出处(report.json / report.md)

- 生成命令:`python -m evals.judge --backend configured --calibrate`
- 后端 / 模型:deepseek-v4-pro(直调,thinking mode 默认开)
- 数据集:evals/dataset/cases/(11 例,构造性金标)
- 代码 commit:603259e(合并 PR#7 后的 main)
- 生成日期:2026-07-19
- 整体 Judge-金标 κ:0.8231

## 诚实边界(必读,别当统计验证)
- **小样本**:每维度只有 1~2 个金标正例。recall=1.0 = "抓到了那 1 个例子",不是统计意义的验证。
- **构造性金标**:标签因缺陷是注入的而为真,不是人工共识。**人-人 κ 仍待标注**(需两名标注者按 ANNOTATION_GUIDE.md 标 calibration split),报告里 human_human_kappa 如实为「待标注」。
- **已知弱点**:AI腔 recall=0.5(漏 ds_09 孤立翻转句,rubric 缺口);人物OOC/设定漂移 precision=0.5(在 ds_05 一个坏 case 上过度归因)。
- **晋级范围**:据此只把「信息边界」(P=R=1.0)晋级 hard 做示范;设定漂移(precision 0.5)与其余保持 observe。数据集做大或有人工标注后再评扩。
```

`evals/calibration/gating.json` 把信息边界改 hard:

```json
    "信息边界": "hard",
```
(其余 7 维不变;`note` 补一句「信息边界已据 report.json 校准达标晋级 hard(2026-07-19),recall=1.0≥0.85」。)

- [ ] **Step 3: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_gating.py -q` → 全绿(护栏测试现在被真报告 + 信息边界=hard 满足)。

- [ ] **Step 4: 接线 eval-real.yml + README**

`.github/workflows/eval-real.yml`:judge 调用 `--calibrate` 改 `--calibrate --gate`(真跑时信息边界 recall<0.85 就让 job 红)。

`evals/README.md`:补「门控真拦截」小节——gating.json observe/soft/hard 现状(信息边界=hard,余 observe)、hard 的含义(元门禁:Judge 这项 recall 掉破 0.85 才红,拦的是"Judge 退化"不是"你的书")、晋级证据在 report.json/PROVENANCE.md、小样本 caveat、AI腔 未晋级原因。

- [ ] **Step 5: 全量 + 接线冒烟 + Commit**

Run: `.venv/bin/python -m pytest -q` → 全绿。
Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/eval-real.yml')); print('eval-real.yml 合法')"`。
Run: `.venv/bin/python -m evals.run_eval --gate; echo $?` → 0(Fixture 门禁无恙)。

```bash
git add evals/calibration/gating.json evals/calibration/report.json evals/calibration/report.md evals/calibration/PROVENANCE.md .github/workflows/eval-real.yml evals/README.md tests/test_eval_gating.py
git commit -m "$(cat <<'EOF'
feat(eval): 信息边界晋级 hard(真校准 P=R=1.0 为证)+ eval-real 接 --gate

据真机校准(deepseek-v4-pro,κ=0.82,信息边界 P=R=1.0≥0.85)把信息边界晋级为首个
hard 维度,report.json/PROVENANCE.md 提交为证(含 n=1~2 小样本/无人-人κ/AI腔漏判
caveat,不夸称统计验证)。eval-real.yml judge 加 --gate 真拦。护栏测试升级为「hard 必须
高代价维+有报告 recall 达标」。设定漂移/AI腔 不晋级。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 控制者验收(无代码改动)

- [ ] 全量 pytest 绿;`run_eval --gate`=0(Fixture 无恙);`LOOM_DEMO=1 judge --backend demo --calibrate --gate`=2(全 infra 不伪装)。
- [ ] gating.json 只有信息边界=hard;report.json/PROVENANCE.md 在库、出处诚实标小样本 caveat。
- [ ] 构造"信息边界 recall=0.5"的合成报告喂 gate_hard_dimensions → 失败(证明 hard 真会拦)。
- [ ] eval-real.yml 触发器仍 dispatch+schedule、contents:read、secret 缺 exit 2、现加 --gate;ci.yml/release.yml 未碰。
- [ ] 汇报用户:真晋级已落地(信息边界 hard 有据),真拦机制上线,证据入库;仍待用户决定合并/推送 + 数据集做大/人工标注才能扩晋级。
