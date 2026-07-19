# Eval Phase 4:分层 CI + 评测报告 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 把三套 suite 的结果收敛成可追溯的 JSON/MD 报告并上传 CI artifact;PR CI 继续零 key 跑 fixture,真 Judge(要 key)另开一个只挂 `workflow_dispatch`+`schedule` 的 workflow;Judge 维度初始全 observe,校准达标才晋级硬门禁。顺带补齐 Phase 3 终审的硬前置(报告披露 infra 掉数)。

**Architecture:** 新增 `evals/report.py`(三源统一报告)、`evals/calibration/gating.json`(维度门禁策略,初始全 observe);扩 `evals/calibration.py`(dropped 披露 + calibrate 闭环便捷函数)与 `evals/judge.py`(CLI 加 `--calibrate` 端到端跑 judge→报告);改 `.github/workflows/ci.yml`(加 fixture 报告 artifact 上传,仍零 key)、新增 `.github/workflows/eval-real.yml`(workflow_dispatch+schedule,真 Judge,读 secret,成本上限)。**不碰 release.yml**(发版 needs 链是安全网)。

**Tech Stack:** Python 3.11 + pytest(现基线 663 绿)+ PyYAML(仅测试解析 workflow 用;`pyyaml` 是否已在 dev 依赖需实现时验证,不在则测试改用 stdlib 手解析关键行,不新增依赖)。

**权威 spec:** `/Users/chambers/Desktop/loom-novel_eval补齐计划.md` §Phase 4 + 路线图 `docs/superpowers/plans/2026-07-17-eval-roadmap-phase3-5.md` + 侦察档案 `.superpowers/sdd/recon-p14/ci.md`(ci.yml/release.yml 逐字)。

## Global Constraints

- **文件白名单**:新建 `evals/report.py`、`evals/calibration/gating.json`、`.github/workflows/eval-real.yml`、`tests/test_eval_report.py`、`tests/test_eval_gating.py`、`tests/test_eval_workflows.py`;修改 `evals/calibration.py`(dropped 披露 + calibrate + gating loader)、`evals/judge.py`(CLI 加 --calibrate)、`.github/workflows/ci.yml`(加 artifact 步骤)、`evals/README.md`(Task 6)。**不碰** `.github/workflows/release.yml`(发版安全网)、`evals/run_eval.py`/`harness.py`/`graders.py`/`generate.py`/`metering.py`/`export_packets.py`、`evals/dataset/**`(数据集/rubric 冻结)、其余 `loom/**`(含 evalapi——Phase 4 不需要新接缝)。
- **PR CI 永远零 key(spec §Phase4 红线)**:`ci.yml` 改动只准加「零 key、离线」的步骤(fixture 报告 + FakeBackend judge 合同测试已在 pytest 里);**绝不**给 ci.yml 加 secret 引用或 `--judge-backend configured`。真 Judge 只进 `eval-real.yml`。
- **eval-real.yml 触发器安全(基于 GitHub 机制)**:只挂 `workflow_dispatch` + `schedule`,**绝不**挂 `pull_request`(fork 读不到 secret)或裸 `pull_request_target`(把 secret 暴露给 fork 代码,pwn request)。secret 缺失时 job 应如实失败/报 infra,不静默跳过、不伪装 PASS。permissions 在 eval-real.yml 自己声明(最小 `contents: read`),不复用/扩大 release.yml 的 `contents: write`。
- **release.yml needs 链不碰**:`test → build-mac/build-windows → release` 是发版硬门禁 + Windows 冒烟安全网(1.0.0 双击崩事故后加的),Phase 4 一个字不改 release.yml。
- **不打分不阻断延续(ADR-0002/0006)**:gating.json 初始**全 observe**;晋级 soft/hard 必须有 Phase 3 校准报告为证(本 Phase 只建策略机制 + 保持全 observe,不晋级任何维度)。报告里可呈现 κ/PRF(eval 侧),但产品 gates.py/parse.py 仍不碰。
- **不造数 + 披露掉数(spec §5 + Phase3 终审硬前置)**:真 Judge 一次 infra 掉了 case,报告必须**披露**「N 例中 M 例 infra 掉出、只在 K 例上算 P/R/F1」,不得把子集结果标成「全量已计算」。
- 既有测试(663)断言禁改。提交信息 `type(scope): 中文摘要` + 末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件,绝不 `git add -A`。
- 环境 `.venv/bin/python`;测试 `.venv/bin/python -m pytest`。

## 现状锚点(侦察核实,别猜)

- `.github/workflows/ci.yml`(36 行):触发 `push`+`pull_request`;matrix `[ubuntu,windows]` fail-fast:false;env `PYTHONUTF8:"1"`;单 job `test`:checkout@v4 → setup-python@v5(3.11)→ `pip install -e ".[dev]"` → `python -m pytest tests/ -q` → `python -m evals.run_eval --gate`。**无 secret / 无 artifact / 无 workflow_dispatch / 无 schedule**。
- `.github/workflows/release.yml`(121 行):触发 `push.tags:["v*"]`+`workflow_dispatch`;`permissions: contents: write`;job 链 `test → build-mac/build-windows(needs:test)→ release(needs:两者, if: always() && build-mac.result=='success' && startsWith(ref,'refs/tags/'))`;唯一用 `${{ github.token }}`(非 repo secret)。**Phase 4 不碰它。**
- 全仓库现状:`secrets.*` 自定义 0 处;`schedule:` 0 处;`upload-artifact`/`download-artifact`/`workflow_dispatch` 仅 release.yml。
- `evals/calibration.py`(Phase 3):`cohen_kappa`/`prf_for_dimension`/`present_matrix`/`verdict_matrix`(遇 infra raise)/`aligned_matrices(gold_cases, judge_results) -> (gold_matrix, judge_matrix, dropped_infra_ids)`/`build_calibration_report(gold, judge, human_pairs) -> dict`/`write_report(report, out_dir) -> (json,md)`/`load_targets`/`evaluate_against_targets`。
- `evals/judge.py`(Phase 3):`judge_case(case, backend) -> JudgeResult(case_id, verdicts, infra_error, error, elapsed_s)`;`main(argv)` 有 `--case/--backend/--dataset-dir/--out`,退出码 0/2。
- `evals/dataset.py`:`DIMENSIONS`(8 维)、`load_case`、`discover_cases`。
- `evals/run_eval.py`:`--gate`(退出码 0/1/2)、`aggregate`;Fixture suite 入口,**本 Phase 不改它**,只在 CI 里额外加一步生成报告。

---

### Task 1: 报告披露 infra 掉数 + calibrate 闭环(Phase 3 终审硬前置)

**Files:**
- Modify: `evals/calibration.py`
- Test: `tests/test_eval_calibration.py`(扩)

**Interfaces:**
- Consumes: Phase 3 的 `aligned_matrices`/`build_calibration_report`/`present_matrix`/`verdict_matrix`。
- Produces:
  - `build_calibration_report` 新增可选参 `dropped_infra: list | None = None`、`n_total: int | None = None`:报告加 `coverage` 段 `{n_total, n_evaluated, n_infra_dropped, dropped_case_ids}`;MD 披露「N 例中 M 例因 infra 掉出,P/R/F1 只在 K 例上算」。缺省(None)时 coverage 段标 `待真机/未评`。
  - `calibrate(gold_cases: list[dict], judge_results: list) -> dict`:端到端——`aligned_matrices` → `present_matrix`/`verdict_matrix`(已在 aligned 内)→ `build_calibration_report`,自动把 dropped/n_total 织进报告。**这是防止「天真接线丢掉 dropped」的唯一安全入口。**

- [ ] **Step 1: 写失败测试**

`tests/test_eval_calibration.py` 追加(顶部已有 `from evals.dataset import DIMENSIONS`;补 `from evals.judge import JudgeResult, DimensionVerdict`):

```python
def _vr(cid, present_dim):
    vs = [DimensionVerdict(d, d == present_dim, "高" if d == present_dim else None, "", "")
          for d in DIMENSIONS]
    return JudgeResult(cid, vs, infra_error=False)


def _gold_case(cid, present_dim):
    return {"id": cid, "labels": [{"dimension": d, "present": d == present_dim} for d in DIMENSIONS]}


def test_calibrate_discloses_infra_dropped():
    from evals.calibration import calibrate
    gold = [_gold_case("c1", "AI腔"), _gold_case("c2", "设定漂移"), _gold_case("c3", None)]
    judge = [_vr("c1", "AI腔"),
             JudgeResult("c2", [], infra_error=True, error="[infra]"),   # c2 掉
             _vr("c3", None)]
    rep = calibrate(gold, judge)
    cov = rep["coverage"]
    assert cov["n_total"] == 3 and cov["n_evaluated"] == 2 and cov["n_infra_dropped"] == 1
    assert cov["dropped_case_ids"] == ["c2"]
    # P/R/F1 只在 c1,c3 上算(c2 未污染):AI腔 c1 命中→tp;c3 干净
    assert rep["judge_vs_gold"]["AI腔"]["tp"] == 1


def test_calibrate_md_discloses_dropped(tmp_path):
    from evals.calibration import calibrate, write_report
    gold = [_gold_case("c1", "AI腔"), _gold_case("c2", "设定漂移")]
    judge = [_vr("c1", "AI腔"), JudgeResult("c2", [], infra_error=True, error="[infra]")]
    rep = calibrate(gold, judge)
    _, m = write_report(rep, tmp_path)
    md = m.read_text(encoding="utf-8")
    assert "infra" in md and ("掉" in md or "掉出" in md or "未评" in md)   # MD 必须披露掉数


def test_build_report_coverage_pending_when_no_judge():
    from evals.calibration import build_calibration_report
    gold = {d: [False] for d in DIMENSIONS}
    rep = build_calibration_report(gold, None, None)
    assert rep["coverage"]["n_evaluated"] is None or rep["coverage"]["status"] == "待真机"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -v -k "calibrate or coverage"`
Expected: FAIL——`cannot import name 'calibrate'` / 报告无 coverage 段。

- [ ] **Step 3: 实现**

`evals/calibration.py`:`build_calibration_report` 签名改为 `(gold, judge, human_pairs, dropped_infra=None, n_total=None)`,在 report dict 里加:

```python
    n_eval = None
    if judge:
        # judge 是 {dim:[bool per evaluated case]},取任一维长度即已评例数
        n_eval = len(next(iter(judge.values()))) if judge else 0
    report["coverage"] = {
        "status": "已计算" if judge else "待真机",
        "n_total": n_total,
        "n_evaluated": n_eval,
        "n_infra_dropped": len(dropped_infra) if dropped_infra is not None else None,
        "dropped_case_ids": list(dropped_infra) if dropped_infra is not None else [],
    }
```

`_md_report` 顶部(人-人段之前)加披露行:

```python
    cov = report.get("coverage", {})
    if cov.get("n_infra_dropped"):
        lines += [f"⚠ 覆盖:共 {cov['n_total']} 例,{cov['n_infra_dropped']} 例因 infra 掉出"
                  f"({cov['dropped_case_ids']}),P/R/F1 只在 {cov['n_evaluated']} 例上算。", ""]
    elif cov.get("status") == "待真机":
        lines += ["覆盖:待真机(未跑真实 Judge)。", ""]
```

新增便捷闭环:

```python
def calibrate(gold_cases: list, judge_results: list) -> dict:
    """端到端安全入口:对齐(滤 infra)→ 算 P/R/F1+κ → 报告自动披露掉数。
    Phase 4 接线只准走这个,别手工 aligned_matrices 后把 dropped 丢了(会掩盖 infra 掉数)。"""
    gold_matrix, judge_matrix, dropped = aligned_matrices(gold_cases, judge_results)
    return build_calibration_report(gold_matrix, judge_matrix, human_pairs=None,
                                    dropped_infra=dropped, n_total=len(judge_results))
```

- [ ] **Step 4: 跑测试通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -q` → 全绿。
Run: `.venv/bin/python -m pytest -q` → 全绿(既有 build_calibration_report 调用点因新参数有默认值不受影响)。

- [ ] **Step 5: Commit**

```bash
git add evals/calibration.py tests/test_eval_calibration.py
git commit -m "$(cat <<'EOF'
feat(eval): calibrate 闭环 + 报告披露 infra 掉数(Phase3 终审硬前置)

build_calibration_report 加 coverage 段(n_total/n_evaluated/n_infra_dropped/
dropped_case_ids),MD 披露「N 例中 M 例 infra 掉出、只在 K 例上算」;新增 calibrate()
安全闭环,把 aligned_matrices 的 dropped 自动织进报告,堵「天真接线丢 dropped 把子集
标成全量」。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: judge CLI `--calibrate` 端到端(judge→报告,离线可冒烟)

**Files:**
- Modify: `evals/judge.py`(main 加 --calibrate/--report-dir)
- Test: `tests/test_eval_judge_structured.py`(扩)

**Interfaces:**
- Consumes: Task 1 `calibrate`/`write_report`、`evals.dataset.load_case`/`discover_cases`。
- Produces: `main` 新增 `--calibrate`(judge 完全部 case 后,用金标 labels + verdicts 跑 calibrate 写报告)+ `--report-dir`(报告落盘目录,默认 evals/runs/judge-<ts>)。demo 模式下所有 case infra → 报告如实全 dropped、coverage 披露(证明诚实链路,不崩)。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_judge_structured.py` 追加:

```python
def test_cli_calibrate_demo_all_infra_reports_honestly(tmp_path, monkeypatch):
    # demo 后端吐罐头非 JSON → 全 case infra → 报告 coverage 如实全 dropped,不崩、退出码 0
    monkeypatch.setenv("LOOM_DEMO", "1")
    from evals.judge import main
    rdir = tmp_path / "rep"
    code = main(["--backend", "demo", "--calibrate", "--report-dir", str(rdir)])
    assert code == 0
    import json
    rep = json.loads((rdir / "report.json").read_text(encoding="utf-8"))
    assert rep["coverage"]["n_infra_dropped"] == rep["coverage"]["n_total"]   # 全掉
    assert rep["coverage"]["n_evaluated"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -v -k "calibrate_demo"`
Expected: FAIL——main 不认 --calibrate。

- [ ] **Step 3: 实现**

`evals/judge.py` main 里 argparse 加:

```python
    ap.add_argument("--calibrate", action="store_true", help="judge 完跑校准并写报告(金标 labels vs verdicts)")
    ap.add_argument("--report-dir", type=Path, default=None, help="校准报告落盘目录")
```

在 judge 循环收集 `results`(JudgeResult 列表)与对应 `gold_cases`(load_case 的 dict,含 labels)后,`--calibrate` 时:

```python
    if args.calibrate:
        from .calibration import calibrate, write_report
        report = calibrate(gold_cases, results)   # gold_cases 与 results 同 case 顺序
        rdir = args.report_dir or (RUNS_DIR_FALLBACK)   # 见下
        j, m = write_report(report, rdir)
        cov = report["coverage"]
        print(f"→ 校准报告:{j}(评 {cov['n_evaluated']}/{cov['n_total']} 例,"
              f"infra 掉 {cov['n_infra_dropped']})")
```

(`RUNS_DIR_FALLBACK`:judge.py 无 runs 常量,用 `Path("evals/runs") / f"judge-{时间戳}"`;时间戳别用 datetime.now()——测试环境无妨,但为确定性可用 `os.getpid()` 或让 --report-dir 必填于测试。实现时:`--report-dir` 缺省则 `Path("evals/runs")/("judge-"+str(len(results))+"cases")`,避免时间依赖;真机跑时人工指定 --report-dir。gold_cases 收集:循环里 `load_case(cdir)` 的返回就是 gold case dict,附带存一份。)

- [ ] **Step 4: 跑测试通过 + demo 冒烟**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -q` → 全绿。
Run: `LOOM_DEMO=1 .venv/bin/python -m evals.judge --backend demo --calibrate --report-dir /tmp/jrep; echo 码=$?`
Expected: 打印「评 0/11 例,infra 掉 11」+ 码 0;`/tmp/jrep/report.md` 含 infra 披露行。

- [ ] **Step 5: Commit**

```bash
git add evals/judge.py tests/test_eval_judge_structured.py
git commit -m "$(cat <<'EOF'
feat(eval): judge CLI --calibrate 端到端——judge→报告,demo 全 infra 也诚实

--calibrate/--report-dir:judge 完用金标 labels+verdicts 跑 calibrate 写报告。demo
后端全 case infra → 报告 coverage 如实全 dropped、n_evaluated=0,不崩不假通过。真机
--backend configured 才产真校准数。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: gating.json 维度门禁策略(初始全 observe)

**Files:**
- Create: `evals/calibration/gating.json`
- Modify: `evals/calibration.py`(load_gating + gate_policy)
- Test: `tests/test_eval_gating.py`(新建)

**Interfaces:**
- Produces:
  - `evals/calibration/gating.json`:`{dimension: "observe"}`×8 + `note`(晋级 soft/hard 需校准报告为证)。
  - `load_gating() -> dict`;`gate_policy(dimension: str, gating: dict) -> str`(返回 observe/soft/hard,未知维度默认 observe)。
- Consumes: `DIMENSIONS`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_gating.py`:

```python
"""维度门禁策略:初始全 observe,校准达标才晋级(本 Phase 只建机制不晋级)。"""
from evals.calibration import gate_policy, load_gating
from evals.dataset import DIMENSIONS


def test_gating_covers_all_dims_initially_observe():
    g = load_gating()
    for d in DIMENSIONS:
        assert g["dimensions"][d] == "observe"      # 初始全 observe(无校准前不硬门禁)
    assert "校准" in g["note"] or "达标" in g["note"]


def test_gate_policy_unknown_dim_defaults_observe():
    assert gate_policy("不存在的维度", load_gating()) == "observe"


def test_gate_policy_reads_declared():
    g = {"dimensions": {"AI腔": "hard"}}
    assert gate_policy("AI腔", g) == "hard"
    assert gate_policy("设定漂移", g) == "observe"   # 未声明 → observe
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_gating.py -v`
Expected: FAIL——`cannot import name 'gate_policy'` / gating.json 不存在。

- [ ] **Step 3: 实现**

新建 `evals/calibration/gating.json`:

```json
{
  "note": "维度门禁策略。observe=只记录不拦截;soft=出警告不拦截;hard=参与门禁拦截。初始全 observe——任一维度晋级 soft/hard 必须有 Phase 3 校准报告(达标 κ/recall)为证,不得凭印象晋级(spec §Phase3/4、ADR-0002)。",
  "dimensions": {
    "人物OOC": "observe", "设定漂移": "observe", "断钩子": "observe", "无爽点": "observe",
    "信息边界": "observe", "物品状态连续性": "observe", "时间连续性": "observe", "AI腔": "observe"
  }
}
```

`evals/calibration.py` 追加(顶部路径常量区加 `GATING_PATH`):

```python
GATING_PATH = Path(__file__).resolve().parent / "calibration" / "gating.json"


def load_gating() -> dict:
    return json.loads(GATING_PATH.read_text(encoding="utf-8"))


def gate_policy(dimension: str, gating: dict) -> str:
    """维度的门禁策略;未声明的维度默认 observe(最保守,不拦截)。"""
    return gating.get("dimensions", {}).get(dimension, "observe")
```

- [ ] **Step 4: 跑测试通过 + 全 observe 护栏**

Run: `.venv/bin/python -m pytest tests/test_eval_gating.py -q` → 3 passed。
补一条护栏(可并入上面测试文件):断言 gating.json 里**没有任何维度**是 hard(本 Phase 不晋级)——`assert "hard" not in load_gating()["dimensions"].values()`,防误晋级。

- [ ] **Step 5: Commit**

```bash
git add evals/calibration/gating.json evals/calibration.py tests/test_eval_gating.py
git commit -m "$(cat <<'EOF'
feat(eval): 维度门禁策略 gating.json——初始全 observe,晋级需校准为证

observe/soft/hard 三档,初始 8 维全 observe(无校准报告前不硬门禁,ADR-0002)。
load_gating/gate_policy(未声明维默认 observe 最保守)。护栏测试钉死本 Phase 无任何
维度是 hard——晋级是 Phase 3 校准达标后的显式 diff,不在本 Phase。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: evals/report.py 三源统一报告

**Files:**
- Create: `evals/report.py`
- Test: `tests/test_eval_report.py`(新建)

**Interfaces:**
- Consumes: `evals.run_eval`(fixture gate 结果结构)、`evals.generate` 的 manifest 结构、Task 1 的 calibration report。
- Produces:
  - `build_run_report(fixture: dict | None, generation: list | None, calibration: dict | None) -> dict`:三源合一,缺的段标 `待/未跑`。
  - `write_run_report(report, out_dir) -> tuple[Path, Path]`(JSON+MD)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_report.py`:

```python
"""三源统一报告(fixture/generation/judge 校准),缺源诚实留空。零真实模型。"""
import json


def test_report_assembles_three_sources(tmp_path):
    from evals.report import build_run_report, write_run_report
    fixture = {"passed": 3, "cases": 3, "regressions": []}
    generation = [{"run_id": "r1", "git_commit": "abc", "backend_class": "DemoBackend"}]
    calibration = {"coverage": {"n_total": 11, "n_evaluated": 8, "n_infra_dropped": 3,
                                "dropped_case_ids": ["a", "b", "c"]}, "judge_vs_gold": {}}
    rep = build_run_report(fixture, generation, calibration)
    assert rep["fixture"]["passed"] == 3
    assert rep["generation"][0]["run_id"] == "r1"
    assert rep["calibration"]["coverage"]["n_infra_dropped"] == 3
    j, m = write_run_report(rep, tmp_path)
    assert j.is_file() and m.is_file()
    assert json.loads(j.read_text(encoding="utf-8"))["fixture"]["passed"] == 3


def test_report_missing_sources_marked_pending(tmp_path):
    from evals.report import build_run_report, write_run_report
    rep = build_run_report({"passed": 3, "cases": 3, "regressions": []}, None, None)
    assert rep["generation"]["status"] == "未跑" or rep["generation"] == []
    assert rep["calibration"]["status"] == "待真机"
    _, m = write_run_report(rep, tmp_path)
    assert "待真机" in m.read_text(encoding="utf-8")     # MD 如实标缺源
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_report.py -v`
Expected: FAIL——`No module named 'evals.report'`。

- [ ] **Step 3: 实现**

新建 `evals/report.py`:

```python
"""三源统一评测报告:Fixture 门禁 + Generation manifest + Judge 校准,合成 JSON/MD。

缺哪源就标缺(未跑/待真机),不造数;上传 CI artifact 供追溯(commit→模型→prompt hash
→结论一条链)。禁止只看加权总分——高代价维在 calibration 段单列(Phase3 报告口径)。
"""

from __future__ import annotations

import json
from pathlib import Path


def build_run_report(fixture: dict | None, generation: list | None,
                     calibration: dict | None) -> dict:
    return {
        "fixture": fixture if fixture is not None else {"status": "未跑"},
        "generation": generation if generation else {"status": "未跑"},
        "calibration": calibration if calibration is not None else {"status": "待真机"},
    }


def _md(report: dict) -> str:
    lines = ["# Loom 评测报告", ""]
    fx = report["fixture"]
    lines += ["## Fixture 门禁(确定性,零 key)",
              (f"- 通过 {fx.get('passed')}/{fx.get('cases')},回归 {len(fx.get('regressions', []))}"
               if "passed" in fx else f"- 状态:{fx.get('status')}"), ""]
    gen = report["generation"]
    lines += ["## Generation suite(真调五 Agent)"]
    if isinstance(gen, list):
        for g in gen:
            lines.append(f"- run {g.get('run_id')} @ {g.get('git_commit')} "
                         f"({g.get('backend_class')})")
    else:
        lines.append(f"- 状态:{gen.get('status')}")
    lines.append("")
    cal = report["calibration"]
    lines += ["## Judge 校准"]
    if "coverage" in cal:
        cov = cal["coverage"]
        lines.append(f"- 覆盖:{cov.get('n_evaluated')}/{cov.get('n_total')} 例"
                     f"(infra 掉 {cov.get('n_infra_dropped')})")
    else:
        lines.append(f"- 状态:{cal.get('status')}")
    return "\n".join(lines) + "\n"


def write_run_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "run_report.json"
    m = out_dir / "run_report.md"
    j.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    m.write_text(_md(report), encoding="utf-8")
    return j, m
```

- [ ] **Step 4: 跑测试通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_report.py -q` → 全绿。
Run: `.venv/bin/python -m pytest -q` → 全绿。

- [ ] **Step 5: Commit**

```bash
git add evals/report.py tests/test_eval_report.py
git commit -m "$(cat <<'EOF'
feat(eval): 三源统一报告 report.py——fixture/generation/judge 校准,缺源诚实留空

build_run_report 合三源为 JSON+MD;缺哪源标「未跑/待真机」不造数。calibration 段带
infra 覆盖披露。为 CI artifact 追溯链(commit→模型→prompt hash→结论)铺路。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: ci.yml 报告 artifact(零 key)+ eval-real.yml 真 Judge workflow

**Files:**
- Modify: `.github/workflows/ci.yml`(加 fixture 报告生成 + artifact 上传步骤)
- Create: `.github/workflows/eval-real.yml`(workflow_dispatch+schedule,真 Judge)
- Test: `tests/test_eval_workflows.py`(新建,解析校验)

**Interfaces:**
- Produces:两个 workflow 文件的结构不变量,由测试钉死。
- Consumes:Task 2 judge CLI、Task 4 report。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_workflows.py`(先验证 pyyaml 可用,不可用则退回逐行断言):

```python
"""workflow 结构不变量:PR CI 零 key、eval-real 只手动/定时、release 不被碰。"""
from pathlib import Path

WF = Path(".github/workflows")


def _load(name):
    import yaml    # pyyaml 在 .[dev]?不在则本测试 pytest.importorskip
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def test_ci_stays_zero_key():
    import pytest
    pytest.importorskip("yaml")
    text = (WF / "ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in text                    # PR CI 绝不碰 secret
    assert "--judge-backend configured" not in text  # 绝不在 PR CI 跑真 Judge
    ci = _load("ci.yml")
    # artifact 上传步骤存在(报告可追溯)
    assert "actions/upload-artifact" in text


def test_eval_real_triggers_are_dispatch_and_schedule_only():
    import pytest
    pytest.importorskip("yaml")
    wf = _load("eval-real.yml")
    on = wf[True] if True in wf else wf.get("on")     # yaml 把 on 解析成 True 键
    assert set(on.keys()) <= {"workflow_dispatch", "schedule"}   # 绝不 pull_request(_target)
    assert "pull_request" not in on


def test_release_yml_untouched_needs_chain():
    text = (WF / "release.yml").read_text(encoding="utf-8")
    assert "needs: test" in text and "needs: [build-mac, build-windows]" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_workflows.py -v`
Expected: FAIL——ci.yml 无 upload-artifact / eval-real.yml 不存在。

- [ ] **Step 3: 实现**

`ci.yml` 在 `test` job 末尾 `eval 回归门禁` 步骤**之后**追加(不动既有步骤/触发器/matrix):

```yaml
      - name: 生成 fixture 评测报告(零 key)
        run: |
          python - <<'PY'
          from pathlib import Path
          from evals.run_eval import run_suite, aggregate, load_baseline, compare_to_baseline
          from evals.report import build_run_report, write_run_report
          import evals.run_eval as R
          results = run_suite(R.HERE / "cases")
          summ = aggregate(results)
          base = load_baseline(R.HERE / "baseline.json")
          regs = compare_to_baseline(results, base) if base else []
          rep = build_run_report({"passed": summ["passed"], "cases": summ["cases"], "regressions": regs},
                                 None, None)
          write_run_report(rep, Path("eval-report"))
          PY
      - name: 上传评测报告
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-report-${{ matrix.os }}
          path: eval-report/
```

(实现时验证 `run_suite`/`aggregate`/`load_baseline`/`compare_to_baseline`/`HERE` 的真实可 import 名——侦察时它们在 run_eval/harness,但 run_suite 在 harness、run_eval re-import;以实际 import 路径为准调整内联脚本,别改 run_eval.py 本身。若内联脚本太脆,可退化为只上传 `--gate` 的 stdout 到文件再 upload——但优先用 report.py。)

新建 `.github/workflows/eval-real.yml`:

```yaml
name: Eval Real Judge

# 真 Judge(要 LLM API key):只手动/定时跑,绝不挂 pull_request(fork 读不到 secret /
# pull_request_target 会把 secret 暴露给 fork 代码)。PR CI 的零 key 门禁在 ci.yml。
on:
  workflow_dispatch:
  schedule:
    - cron: "0 3 * * 1"   # 每周一 03:00 UTC

permissions:
  contents: read           # 最小权限,不复用 release.yml 的 contents:write

env:
  PYTHONUTF8: "1"

jobs:
  judge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: 安装依赖
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: 真 Judge + 校准报告(要 key,secret 缺失则失败不伪装 PASS)
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        run: |
          if [ -z "$DEEPSEEK_API_KEY" ]; then
            echo "✗ 缺 DEEPSEEK_API_KEY secret —— 真 Judge 无法跑(这是 infra 缺失,不是质量 PASS)"
            exit 2
          fi
          python -m evals.judge --backend configured --calibrate --report-dir eval-real-report
      - name: 上传校准报告
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-real-report
          path: eval-real-report/
```

- [ ] **Step 4: 跑测试通过 + workflow 结构验证**

Run: `.venv/bin/python -m pytest tests/test_eval_workflows.py -q` → 全绿。
Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); yaml.safe_load(open('.github/workflows/eval-real.yml')); print('两 workflow YAML 合法')"`
Expected: 打印合法(语法无误)。
**注**:eval-real.yml 真跑需用户在 GitHub 仓库 Settings→Secrets 加 `DEEPSEEK_API_KEY`——**Claude 不能也不应代加 secret**,这是用户动作。本任务只落地 workflow 文件(未 push 前不会触发)。

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/eval-real.yml tests/test_eval_workflows.py
git commit -m "$(cat <<'EOF'
feat(eval): 分层 CI——ci.yml 加零 key 报告 artifact + eval-real.yml 真 Judge

ci.yml 追加 fixture 报告生成+artifact 上传(仍零 key、不碰 secret/不跑真 Judge)。
新增 eval-real.yml:workflow_dispatch+schedule(周一)跑真 Judge+校准,读
DEEPSEEK_API_KEY secret,缺失则 exit 2 不伪装 PASS,最小 contents:read 权限。绝不挂
pull_request(fork 安全)。release.yml 一字未动。测试钉死三不变量。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 控制者终审验收 + README Phase 4(无代码改动的验证 + 文档)

**Files:**
- Modify: `evals/README.md`(Phase 4 节)
- 其余只验证。

- [ ] **Step 1: 全量 + 分层链路自跑**

Run: `.venv/bin/python -m pytest -q` → 全绿(663 基线 + Phase 4 新增)。
Run: `.venv/bin/python -m evals.run_eval --gate; echo $?` → 0(PR CI 门禁无恙)。
Run: `LOOM_DEMO=1 .venv/bin/python -m evals.judge --backend demo --calibrate --report-dir /tmp/p4rep; echo $?` → 0,报告 coverage 全 dropped 披露。
Run: `.venv/bin/python -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/ci.yml','.github/workflows/eval-real.yml','.github/workflows/release.yml']]; print('三 workflow 合法')"`。

- [ ] **Step 2: 红线抽查**

- `git diff main..HEAD -- .github/workflows/release.yml` → 空(release.yml 零改动)。
- ci.yml 无 `secrets.` / 无 `--judge-backend configured`(grep)。
- eval-real.yml 触发器只 workflow_dispatch/schedule;permissions 只 contents:read。
- gating.json 全 observe(无 hard)。
- 报告链无造数:demo 全 infra → 报告 n_evaluated=0 + 披露,不标「已达成」。

- [ ] **Step 3: README Phase 4 节**

追加:分层 CI 图(PR=fixture 零 key 报告 artifact;eval-real=手动/定时真 Judge)、**用户需加 `DEEPSEEK_API_KEY` repo secret** 才能跑 eval-real(给出 Settings→Secrets 路径)、gating.json observe/soft/hard 语义 + 「晋级 hard 需 Phase 3 校准报告为证」、报告 artifact 在哪下载。

- [ ] **Step 4: 汇报 + ledger**

向用户报:Phase 4 新增测试计数、分层链路自跑、红线抽查、**待用户动作(加 repo secret + 真机 Judge 校准跑一轮才有真 κ)**。不合并、不推送——等验收。

---

## Phase 5 预告(候选,待用户拍板)

伙伴/领航员 agent 对话协议 eval:对话 golden(脚本化多轮 + 协议解析对抗样本集),覆盖真机踩过的坑(括号壳漏字/协议行渲染/重复卡)。新范围,另立计划。
