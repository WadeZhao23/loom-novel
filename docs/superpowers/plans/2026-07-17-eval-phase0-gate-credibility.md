# Eval Phase 0:让门禁语义可信 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 修掉 eval 门禁的三个「本该红却绿」的语义漏洞(坏样本 FAIL→PASS 不报警 / 新增删除 case 绕过 baseline / Judge 后端失败假通过),并给 harness 补上第一层单测,让 `python -m evals.run_eval --gate` 真正能证明「grader/harness/负向控制样本没被改坏」。

**Architecture:** 全部改动收敛在 `evals/` 三个文件(graders.py / harness.py / run_eval.py)+ 四个新测试文件。零 key、零真实模型、可全 TDD——Judge 相关测试用 conftest 已有的 FakeBackend/ScriptedBackend。case 分两类(quality / detector_contract),后者显式声明「哪个 grader 必须命中缺陷」,检测器坏了直接红;门禁比对补双向(新增/删除 case 报警);Judge 后端失败从「假通过」改成「infra_error」三态。

**Tech Stack:** Python 3.11 + pytest(现 542 绿)。无新依赖。

**权威 spec:** `/Users/chambers/Desktop/loom-novel_eval补齐计划.md`(§2 两个 P0 + §3 Phase 0)+ 本会话侦察报告(把 spec 翻译成真实坐标)。

## Global Constraints

- **只改 `evals/graders.py`、`evals/harness.py`、`evals/run_eval.py` + 新建 `tests/test_eval_graders.py`、`tests/test_eval_harness.py`、`tests/test_eval_judge.py`、`tests/test_eval_cli.py`**。不碰 loom/ 产品代码、不碰 `.github/workflows/`(那是 Phase 4)、不碰 `evals/cases/` 的 chapter.md fixture 文本。**允许改 `evals/cases/case_02_flawed/case.json`(加契约字段)和 `evals/baseline.json`(重新固化)**。
- **零真实模型调用**:Judge 测试全走 `tests/conftest.py:23-39` 的 `FakeBackend`(`FakeBackend(responder)`,responder 内 `raise` 即测后端失败路径)和 `:61-83` 的 `ScriptedBackend`(按序 pop 回复)。**绝不在测试里初始化真后端。**
- **evalapi 红线不许破**:`loom/evalapi.py` 的「evals 只准 import evalapi」+「import 失败不降级、--gate 当场红」是设计,别引入 try/except 把 import 失败吞掉。
- **门禁有两个消费方**:`.github/workflows/ci.yml:36` 和 `release.yml:35` 都跑 `--gate`——改退出码/CLI 参数要保证这两处的现有调用(`python -m evals.run_eval --gate`)仍语义正确(退出码 0=通过、非 0=有问题)。**本计划不改 workflow 文件,但改动必须向后兼容它们的调用形式。**
- **Windows CI**:`ci.yml:15` 设了 `PYTHONUTF8: "1"`(✅❌ 等字符 cp1252 会炸)。本计划不新增 subprocess,输出走 print 无妨;但测试里别硬编码依赖 locale 的路径分隔。
- **既有测试红了 = 实现错了,禁改断言**:尤其 `tests/test_length_screws.py:70-77`(已有的 `grade_length(text, target, tol)` 护栏,**不许改这个签名**)。
- 提交信息 `type(scope): 中文摘要`,末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件,绝不 `git add -A`。
- 环境 `.venv/bin/python`;测试 `.venv/bin/python -m pytest`;eval 自跑 `.venv/bin/python -m evals.run_eval`。

## 现状锚点(实现者必读——这些是当前真实代码,别猜)

- `evals/harness.py:38-46` `CaseResult(case_id, title, score, passed, graders)` + `as_dict()`。
- `evals/harness.py:55-72` `run_case(case_dir, *, backend=None, judge=False)`:读 case.json → 组 graders → `passed = all(g.passed for g in graders if g.gating)` → `CaseResult`。style_ab 型走 `_run_style_ab_case`(:75)。
- `evals/harness.py:118-121` `save_baseline`:存 `{"cases": {id: {score, passed}}, "summary": aggregate(...)}`。
- `evals/harness.py:130-144` `compare_to_baseline(results, baseline, tol=0.05)`:只有两个分支——`if b["passed"] and not r.passed`(通过→失败)、`elif r.score + tol < b["score"]`(分数下滑);`if not b: continue`(新 case 跳过);**从不反向遍历 baseline**。
- `evals/graders.py:30-44` `GraderResult(name, score, passed, weight=1.0, gating=True, detail="", evidence=[])`。
- `evals/graders.py:205-214`(质检)/`:220-227`(去AI味):后端异常 → `return GraderResult(名, 0.0, True, weight, gating=False, detail="(后端调用失败 …)")`——**passed=True 是假通过**。
- `evals/run_eval.py:60-70`:`os.environ.setdefault("LOOM_DEMO", "1")` 后 `get_backend(Config())`。
- `evals/run_eval.py:81-84`:`if args.baseline: save; return 0`——**在 gate 检查之前 return,`--baseline --gate` 同传会静默跳过门禁**。
- `evals/run_eval.py:71-73/86-96`:三处 `return 1`(无 case / 无 baseline / 有回归)不可区分。

---

### Task 1: detector_contract_case 契约——检测器坏了直接红(P0-A)

**Files:**
- Modify: `evals/harness.py`(CaseResult 加字段 + run_case 加契约判定)
- Modify: `evals/cases/case_02_flawed/case.json`(把 `note` 的人类语义落成机器字段)
- Test: `tests/test_eval_harness.py`(新建)

**Interfaces:**
- Produces:
  - `CaseResult` 新增字段 `case_type: str = "quality"` 和 `contract_ok: bool = True`。
  - `run_case` 对 `case.json` 里 `"case_type": "detector_contract"` + `"expect_fail_graders": [grader名…]` 的 case:判定「这些 grader 是否都如约命中缺陷(passed=False)」;任一本该失败的 grader 反而通过(或不存在)→ `contract_ok=False`,且 `passed` 置为 `False`(契约违约=这个负向控制样本坏了=该红)。
- Consumes: 无(第一个任务)。

**背景:** 现在 case_02 的「它应当 FAIL」只写在 `note` 自由文本里、代码零消费。检测器若坏了(恒返「无问题」),case_02 三个 gating grader 全过 → `passed` 从 False 变 True、分数上升,门禁不报警(harness.py:138 因基线 passed=False 短路)。本任务让契约进代码:声明「关键要素 / 去AI味·确定性 这些 grader **必须**在这一章命中缺陷」,检测器坏了→契约违约→case 判 False。

grader 的 name 字段(用于 `expect_fail_graders` 匹配)取自 graders.py:各 grade_* 返回的 `GraderResult.name`——确定性维度是「长度达标」「去AI味·确定性」「关键要素」「风格相似·…」(见 baseline.json:19-24 的 per_grader 键)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_harness.py`:

```python
"""eval harness 门禁语义:契约样本/双向比对/退出码。零真实模型。"""
import json
from pathlib import Path

from evals import harness
from evals.graders import GraderResult
from evals.harness import CaseResult, compare_to_baseline


def _cr(cid, passed, score, case_type="quality", contract_ok=True, graders=None):
    return CaseResult(cid, cid, score, passed, graders or [], case_type=case_type, contract_ok=contract_ok)


def test_detector_contract_pass_when_flaw_caught(tmp_path):
    # 契约样本:声明「关键要素」必须命中缺陷;检测器正常命中 → contract_ok=True、case passed=True(契约成立=绿)
    d = tmp_path / "c"; d.mkdir()
    (d / "case.json").write_text(json.dumps({
        "id": "det", "chapter_chars": 600, "fixture": "chapter.md",
        "case_type": "detector_contract", "expect_fail_graders": ["关键要素"],
        "expect": {"must_include": ["师姐"], "must_not_include": ["二中"]},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "chapter.md").write_text("这一章缺了师姐,还写了二中。" * 30, encoding="utf-8")  # 缺师姐+有二中→关键要素必fail
    r = harness.run_case(d)
    assert r.case_type == "detector_contract"
    assert r.contract_ok is True          # 缺陷被抓到,契约成立
    assert r.passed is True               # 契约样本:契约成立=这个case是绿的


def test_detector_contract_fails_when_detector_broke(tmp_path):
    # 检测器坏了(章节其实干净、grader 没东西可抓)→ 声明该fail的grader反而pass → 契约违约 → case passed=False
    d = tmp_path / "c"; d.mkdir()
    (d / "case.json").write_text(json.dumps({
        "id": "det", "chapter_chars": 600, "fixture": "chapter.md",
        "case_type": "detector_contract", "expect_fail_graders": ["关键要素"],
        "expect": {"must_include": ["师姐"], "must_not_include": ["二中"]},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "chapter.md").write_text("师姐登场,这一章很干净没有禁词。" * 30, encoding="utf-8")  # 师姐在+无二中→关键要素会pass
    r = harness.run_case(d)
    assert r.contract_ok is False         # 本该命中缺陷的grader却通过=检测器失灵
    assert r.passed is False              # 契约违约 → 该红
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -v -k "detector_contract"`
Expected: FAIL——`CaseResult` 不接受 `case_type`/`contract_ok` 参数(TypeError)。

- [ ] **Step 3: 实现**

`evals/harness.py` 的 `CaseResult`(:38-46)加两个字段:

```python
@dataclass
class CaseResult:
    case_id: str
    title: str
    score: float
    passed: bool
    graders: list[GraderResult] = field(default_factory=list)
    case_type: str = "quality"        # "quality" | "detector_contract"
    contract_ok: bool = True          # detector_contract:声明必须命中缺陷的 grader 是否都如约失败

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "title": self.title, "score": self.score,
                "passed": self.passed, "case_type": self.case_type,
                "contract_ok": self.contract_ok, "graders": [g.as_dict() for g in self.graders]}
```

`run_case`(:55-72)末尾,把 `passed`/返回改成走契约判定(替换 :71-72 的 `passed = …; return CaseResult(...)`):

```python
    case_type = case.get("case_type", "quality")
    if case_type == "detector_contract":
        want_fail = set(case.get("expect_fail_graders", []))
        by_name = {g.name: g for g in graders}
        # 契约成立 = 每个声明必须命中缺陷的 grader 都存在且 passed=False
        contract_ok = bool(want_fail) and all(
            (name in by_name) and (by_name[name].passed is False) for name in want_fail)
        return CaseResult(case["id"], case.get("title", case["id"]), _weighted(graders),
                          contract_ok, graders, case_type=case_type, contract_ok=contract_ok)
    passed = all(g.passed for g in graders if g.gating)
    return CaseResult(case["id"], case.get("title", case["id"]), _weighted(graders),
                      passed, graders, case_type=case_type)
```

`evals/cases/case_02_flawed/case.json` 加两个字段(在 `"fixture"` 后、`"note"` 前),不动其余:

```json
  "case_type": "detector_contract",
  "expect_fail_graders": ["关键要素", "去AI味·确定性"],
```
(理由:这一章注入了 AI 翻转句(去AI味·确定性 必命中)+ 漏师姐/写二中(关键要素 必命中);声明这两个 grader 必须失败。`note` 保留作人类可读说明。)

- [ ] **Step 4: 跑测试确认通过 + 自跑 eval**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -q`
Expected: 2 passed。
Run: `.venv/bin/python -m evals.run_eval`(不带 --gate,只看表)
Expected: case_02_flawed 现在 `passed=True`(契约成立,检测器抓到了缺陷)——**这与旧 baseline 的 passed=False 相反,Task 3 会重新固化 baseline;本步只确认自跑不崩。**

- [ ] **Step 5: Commit**

```bash
git add evals/harness.py evals/cases/case_02_flawed/case.json tests/test_eval_harness.py
git commit -m "$(cat <<'EOF'
feat(eval): detector_contract 契约样本——检测器坏了直接红(P0-A)

case_02 的「它应当FAIL」从note自由文本落成机器字段 case_type/expect_fail_graders:
声明「关键要素/去AI味·确定性」必须在这坏章上命中缺陷。检测器若坏了(恒返无问题)→
声明该fail的grader反而pass→contract_ok=False→case passed=False→门禁红。堵住
「坏样本FAIL→PASS+分数上升不报警」的漏洞。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: compare_to_baseline 双向核对——新增/删除 case 不再绕过(P0-B)

**Files:**
- Modify: `evals/harness.py:130-144`(compare_to_baseline)
- Test: `tests/test_eval_harness.py`(扩)

**Interfaces:**
- Consumes: Task 1 的 `CaseResult`(含 case_type)。
- Produces: `compare_to_baseline(results, baseline, tol=0.05)` 返回的回归项 dict 多两种 `kind`:`"未固化(新case未进baseline)"` 和 `"case消失(baseline有现无)"`。

**背景:** 现在 `if not b: continue` 让新 case 直接跳过比较(未固化也不报警);函数只遍历 results、从不反向遍历 baseline,删掉的 case 无声无息。两个方向都能绕过门禁。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_harness.py` 追加:

```python
def test_new_case_not_in_baseline_flagged(tmp_path):
    base = {"cases": {"old": {"score": 1.0, "passed": True}}}
    results = [_cr("old", True, 1.0), _cr("new", True, 0.9)]   # new 不在 baseline
    regs = compare_to_baseline(results, base)
    assert any(x["case"] == "new" and "未固化" in x["kind"] for x in regs)


def test_deleted_baseline_case_flagged(tmp_path):
    base = {"cases": {"old": {"score": 1.0, "passed": True}, "gone": {"score": 1.0, "passed": True}}}
    results = [_cr("old", True, 1.0)]                          # gone 从数据集删了
    regs = compare_to_baseline(results, base)
    assert any(x["case"] == "gone" and "消失" in x["kind"] for x in regs)


def test_no_false_regression_when_matched(tmp_path):
    base = {"cases": {"old": {"score": 1.0, "passed": True}}}
    results = [_cr("old", True, 1.0)]
    assert compare_to_baseline(results, base) == []            # 对齐时零回归
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -v -k "new_case or deleted or false_regression"`
Expected: 前两条 FAIL(未固化/消失均未报),第三条 PASS。

- [ ] **Step 3: 实现**

`evals/harness.py` 的 `compare_to_baseline`(:130-144)替换为:

```python
def compare_to_baseline(results: list[CaseResult], baseline: dict, tol: float = 0.05) -> list[dict]:
    """回归项:通过→失败 / 分数下滑超 tol / 新 case 未固化 / baseline case 消失。"""
    base = baseline.get("cases", {})
    seen = {r.case_id for r in results}
    regressions: list[dict] = []
    for r in results:
        b = base.get(r.case_id)
        if not b:
            regressions.append({"case": r.case_id, "kind": "未固化(新case未进baseline)",
                                "was": None, "now": r.score})
            continue
        if b["passed"] and not r.passed:
            regressions.append({"case": r.case_id, "kind": "通过→失败", "was": b["score"], "now": r.score})
        elif r.score + tol < b["score"]:
            regressions.append({"case": r.case_id, "kind": f"分数下滑 >{tol}", "was": b["score"], "now": r.score})
    for cid in base:
        if cid not in seen:
            regressions.append({"case": cid, "kind": "case消失(baseline有现无)",
                                "was": base[cid]["score"], "now": None})
    return regressions
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -q`
Expected: Task 1+2 全绿。

- [ ] **Step 5: Commit**

```bash
git add evals/harness.py tests/test_eval_harness.py
git commit -m "$(cat <<'EOF'
fix(eval): compare_to_baseline 双向核对——新增/删除case不再绕过门禁(P0-B)

新case不再 continue 静默跳过而报「未固化」;反向遍历baseline,删掉的case报「消失」。
堵住「加个失败case不更新baseline绿灯/删掉baseline里的case无声」两个方向。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: baseline schema 升级(per-grader 明细 + case 类型 + 版本)+ 重新固化

**Files:**
- Modify: `evals/harness.py:118-121`(save_baseline)
- Modify: `evals/baseline.json`(重新固化,含 case_02 契约翻转)
- Test: `tests/test_eval_harness.py`(扩)

**Interfaces:**
- Consumes: Task 1 的 CaseResult.case_type/contract_ok。
- Produces: baseline.json 每 case 存 `{score, passed, case_type, graders: {name: {score, passed, gating}}}` + 顶层 `schema_version: 1`。`load_baseline` 不变(仍 `json.loads`)。`compare_to_baseline` 现读的 `b["score"]`/`b["passed"]` 键名不变(向后兼容),新增的 graders 明细供未来 grader 级回归用,本 Phase 不消费其比对逻辑(只存,不比——避免 scope 膨胀)。

**背景:** 现在 baseline 只存 case 级 `{score, passed}`,grader 坏了但 case 级分数没跌破 tol 就抓不到。本任务把 per-grader 明细存进 baseline(为 Phase 后续的 grader 级门禁铺路),并顺手把 Task 1 导致的 case_02 契约翻转(passed False→True)重新固化。

- [ ] **Step 1: 写失败测试**

```python
def test_baseline_stores_per_grader_and_version(tmp_path):
    from evals.harness import save_baseline, CaseResult
    from evals.graders import GraderResult
    g = GraderResult("关键要素", 0.5, False, 1.0, True)
    r = CaseResult("c", "c", 0.5, False, [g], case_type="detector_contract", contract_ok=True)
    p = tmp_path / "b.json"
    save_baseline(p, [r])
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    c = data["cases"]["c"]
    assert c["case_type"] == "detector_contract"
    assert c["graders"]["关键要素"] == {"score": 0.5, "passed": False, "gating": True}
    assert c["score"] == 0.5 and c["passed"] is False   # 旧键仍在(向后兼容 compare)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -v -k "per_grader"`
Expected: FAIL——baseline 无 `schema_version`/`graders`/`case_type`。

- [ ] **Step 3: 实现**

`evals/harness.py` 的 `save_baseline`(:118-121)替换为:

```python
def save_baseline(path: Path, results: list[CaseResult]) -> None:
    payload = {
        "schema_version": 1,
        "cases": {r.case_id: {
            "score": r.score, "passed": r.passed, "case_type": r.case_type,
            "graders": {g.name: {"score": g.score, "passed": g.passed, "gating": g.gating}
                        for g in r.graders},
        } for r in results},
        "summary": aggregate(results),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 跑测试通过 + 重新固化 baseline**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -q` → 全绿。
重新固化(命令行,无 LOOM_GOLDEN_WRITE 那套——那是 test_golden_pipeline 的机制,别混):
Run: `.venv/bin/python -m evals.run_eval --baseline`
然后 `git diff evals/baseline.json` **人工审**:确认 case_02_flawed 的 `passed` 变 `true`(契约成立)、多了 `schema_version`/per-grader,case_01/03 分数不变。**若 case_01/03 的分数/passed 有任何变化,停下报告——那是 Task 1 意外碰到了它们。**

- [ ] **Step 5: Commit**

```bash
git add evals/harness.py evals/baseline.json tests/test_eval_harness.py
git commit -m "$(cat <<'EOF'
feat(eval): baseline schema v1——per-grader明细+case类型+版本,重固化

baseline 每case存grader级{score,passed,gating}+case_type+schema_version(为后续
grader级门禁铺路,本Phase只存不比)。旧键score/passed保留(compare向后兼容)。顺手
重固化:case_02契约翻转passed→true(检测器抓到缺陷=契约成立=绿)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 退出码三态 + `--baseline --gate` 静默跳过修复

**Files:**
- Modify: `evals/run_eval.py:71-98`(main 的收尾逻辑)
- Test: `tests/test_eval_cli.py`(新建)

**Interfaces:**
- Consumes: Task 2 的 compare_to_baseline(返回含新 kind)。
- Produces: `main(argv)` 退出码语义化——`0`=通过/已固化;`1`=质量回归(有 regressions);`2`=infra(无 case 目录 / 无 baseline 文件)。且 `--baseline` 与 `--gate` 同传时**先固化再照常跑门禁**(不再 return 0 跳过)。

**背景:** 现在三处 `return 1` 不可区分(无 case / 无 baseline / 回归),CI 分不清「环境坏了」和「真回归」;且 `--baseline` 在 gate 前 return 0,`--baseline --gate` 同传静默跳过门禁(第三个绕过面)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_cli.py`:

```python
"""run_eval CLI 退出码矩阵:0通过/1回归/2infra。零真实模型。"""
from evals.run_eval import main


def test_no_cases_is_infra_2(tmp_path):
    assert main(["--cases", str(tmp_path), "--gate"]) == 2      # 空目录=infra,不是回归


def test_no_baseline_is_infra_2(tmp_path, monkeypatch):
    # 有 case 但没 baseline 文件 → infra_error 2(不是 1)
    import evals.run_eval as re
    code = main(["--gate", "--baseline-file", str(tmp_path / "nope.json")])
    assert code == 2


def test_gate_pass_is_0():
    # 默认 cases + 默认 baseline(已固化)对齐 → 0
    assert main(["--gate"]) == 0


def test_baseline_and_gate_together_still_gates(tmp_path, monkeypatch):
    # --baseline --gate 同传:固化后仍跑门禁,不静默跳过(此处固化到临时文件不影响真baseline)
    bf = tmp_path / "b.json"
    assert main(["--baseline", "--baseline-file", str(bf)]) == 0   # 先固化
    assert main(["--gate", "--baseline-file", str(bf)]) == 0        # 再门禁,对齐=0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_cli.py -v`
Expected: `test_no_cases_is_infra_2`/`test_no_baseline_is_infra_2` FAIL(现返 1 不是 2)。

- [ ] **Step 3: 实现**

`evals/run_eval.py` 的 `main`,把 `results = run_suite(...)` 之后(:71)到函数末尾替换为:

```python
    results = run_suite(args.cases, backend=backend, judge=args.judge)
    if not results:
        print(f"✗ 在 {args.cases} 下没找到任何 case(需要 <case>/case.json)。")
        return 2   # infra:数据集缺失,不是质量回归

    _print_table(results)
    summ = aggregate(results)
    print(f"通过率 {summ['passed']}/{summ['cases']} = {summ['pass_rate']:.0%}   "
          f"平均分 {summ['mean_score']:.3f}")
    print("各维度均分:" + " · ".join(f"{k} {v:.2f}" for k, v in summ["per_grader"].items()))

    if args.baseline:
        save_baseline(args.baseline_file, results)
        print(f"\n✓ 已写入基线:{args.baseline_file}")
        if not args.gate:
            return 0
        # --baseline --gate 同传:固化后照常跑门禁,不静默跳过

    if args.gate:
        baseline = load_baseline(args.baseline_file)
        if baseline is None:
            print(f"\n✗ 没有基线可比对({args.baseline_file})。先跑一次 --baseline。")
            return 2   # infra:基线文件缺失,不是质量回归
        regs = compare_to_baseline(results, baseline, tol=args.tol)
        if regs:
            print("\n❌ 检测到回归:")
            for x in regs:
                print(f"   · {x['case']}:{x['kind']}(基线 {x['was']} → 现在 {x['now']})")
            return 1   # 质量回归
        print("\n✅ 无回归(与基线一致或更好)。")
    return 0
```

- [ ] **Step 4: 跑测试通过 + 双消费方冒烟**

Run: `.venv/bin/python -m pytest tests/test_eval_cli.py -q` → 全绿。
Run: `.venv/bin/python -m evals.run_eval --gate; echo "退出码=$?"`
Expected: `✅ 无回归` + `退出码=0`(ci.yml/release.yml 的调用形式仍语义正确)。

- [ ] **Step 5: Commit**

```bash
git add evals/run_eval.py tests/test_eval_cli.py
git commit -m "$(cat <<'EOF'
fix(eval): 退出码三态(0通过/1回归/2infra)+ --baseline --gate 不再静默跳门禁

无case/无baseline文件从「return 1」改「return 2 infra」,CI能分清环境坏vs真回归;
--baseline与--gate同传时固化后照常跑门禁(堵第三个绕过面)。ci.yml/release.yml的
--gate调用退出码语义不变(0通过/非0有问题)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Judge 后端失败 → infra_error,不再假通过(P0-C)+ `--judge-backend` 显式

**Files:**
- Modify: `evals/graders.py:205-227`(两个 LLM grader 的 except 分支)
- Modify: `evals/run_eval.py:60-70`(后端选择)
- Test: `tests/test_eval_judge.py`(新建)

**Interfaces:**
- Consumes: conftest `FakeBackend`。
- Produces:
  - `grade_quality_llm`/`grade_deslop_llm` 后端异常时返回的 GraderResult 带 `detail` 前缀 `"[infra]"` 且 **`passed=False`**(不再 True);仍 `gating=False`(不拖垮 case 通过判定),但 case 层能据 detail 识别 infra。
  - `run_eval.py` 新增 `--judge-backend {demo,configured}`(默认 demo);替代 `os.environ.setdefault("LOOM_DEMO","1")`。`demo`→显式设 `LOOM_DEMO=1`;`configured`→不设 LOOM_DEMO、走项目配置后端。

**背景(P0-C):** 现在后端挂了(网络/无 key)→ 两个 LLM grader 返回 `passed=True, gating=False`——「后端失败 = 假通过」。而且 `os.environ.setdefault("LOOM_DEMO","1")` 是进程级变异、`"0"` 也算真、`configured` 时裸 `Config()` 不读项目 .env。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_judge.py`:

```python
"""LLM-judge grader:后端失败不假通过、非法输出、正常判断。用 FakeBackend,零真实模型。"""
from conftest import FakeBackend
from evals.graders import grade_quality_llm, grade_deslop_llm


def _boom(system, user, **kw):
    raise RuntimeError("后端炸了")


def test_backend_failure_not_fake_pass():
    g = grade_quality_llm("正文", "设定", FakeBackend(_boom))
    assert g.passed is False          # 后端失败绝不假通过
    assert "[infra]" in g.detail      # 标成 infra 供上层识别


def test_deslop_backend_failure_not_fake_pass():
    g = grade_deslop_llm("正文", "指纹", FakeBackend(_boom))
    assert g.passed is False and "[infra]" in g.detail


def test_clean_verdict_passes():
    g = grade_quality_llm("正文", "设定", FakeBackend(lambda s, u, **k: "通过"))
    assert g.passed is True           # 复审回「通过」→ 无硬伤 → passed


def test_issues_found_fails():
    verdict = "- OOC：主角性格崩了\n- 断钩：章末没留悬念"
    g = grade_quality_llm("正文", "设定", FakeBackend(lambda s, u, **k: verdict))
    assert g.passed is False          # 挑出硬伤 → 不通过
```

(已核实 conftest.py:23-35:`FakeBackend(responder)` 的 responder 以 `responder(system, user)` 两参调用,`FakeBackend.complete(self, system, user, *, max_chars=None, on_chunk=None)` 已吃 `max_chars`——上面的 `_boom(system, user, **kw)` 和 `lambda s, u, **k: …` 都能直接跑,`**kw`/`**k` 是无害冗余,可留可删。`grade_quality_llm` 内部调 `backend.complete(CRITIC_质检, user, max_chars=600)`,签名对得上,不用改 conftest。)

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_judge.py -v`
Expected: `test_backend_failure_not_fake_pass`/`test_deslop_…` FAIL(现返 passed=True)。

- [ ] **Step 3: 实现**

`evals/graders.py:205-214`(质检)的 except 分支:

```python
    except Exception as e:  # noqa: BLE001 — 后端报错=infra,绝不假通过
        return GraderResult("质检·LLM", 0.0, False, weight, gating=False, detail=f"[infra] 后端调用失败 — {e}")
```
`:220-227`(去AI味)的 except 分支同样改:`passed` 从 `True` 改 `False`,`detail` 前缀 `[infra]`。

`evals/run_eval.py:49-68` 的后端选择,把 argparse 加一行 + 改 backend 初始化:

```python
    ap.add_argument("--judge-backend", choices=["demo", "configured"], default="demo",
                    help="judge 用哪个后端:demo(离线占位,默认)/ configured(读项目配置,要 key)")
    args = ap.parse_args(argv)

    backend = None
    if args.judge:
        if args.judge_backend == "demo":
            os.environ["LOOM_DEMO"] = "1"   # 显式设,不用 setdefault(避免 "0" 也算真、进程串染)
        try:
            from loom.backends import get_backend
            from loom.config import Config
            backend = get_backend(Config())
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 无法初始化后端(judge-backend={args.judge_backend}):{e}")
```

- [ ] **Step 4: 跑测试通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_judge.py -q`
Expected: 4 passed。
Run: `.venv/bin/python -m evals.run_eval --judge --judge-backend demo`(离线 demo judge 冒烟)
Expected: 不崩、judge grader 挂上(demo 占位不会挑出硬伤)。

- [ ] **Step 5: Commit**

```bash
git add evals/graders.py evals/run_eval.py tests/test_eval_judge.py
git commit -m "$(cat <<'EOF'
fix(eval): Judge后端失败→infra不假通过(P0-C)+ --judge-backend显式

两个LLM grader后端异常从「passed=True假通过」改「passed=False+detail[infra]」;
--judge-backend demo|configured 替代 os.environ.setdefault(LOOM_DEMO)(避免"0"算真/
进程串染/configured裸Config)。堵住「后端挂了=质量PASS」。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 确定性 grader 的正反例边界测试(补测试网,不改逻辑)

**Files:**
- Test: `tests/test_eval_graders.py`(新建)

**Interfaces:**
- Consumes: `evals.graders` 的 `grade_length`/`grade_aitell`/`grade_keywords`/`grade_style_ab`。
- Produces: 无(纯测试)。

**背景:** 确定性 grader 目前只有 `test_length_screws.py:70-77` 一个护栏。本任务给每个确定性 grader 补正例(该过)、反例(该抓)、边界,让「有人把检测器改坏」有测试网接住(这是 P0-A 的补充:契约样本靠数据、单测靠代码,两层都要)。

- [ ] **Step 1: 写测试**(先读 graders.py 各 grade_* 的真实签名/返回,把断言写到能跑)

新建 `tests/test_eval_graders.py`:

```python
"""确定性 grader 的正反例+边界。别与 test_length_screws.py 重复 grade_length 的既有断言。"""
from evals.graders import grade_aitell, grade_keywords


def test_keywords_must_include_missing_fails():
    g = grade_keywords("这章没有那个词", must_include=["师姐"], must_not_include=None)
    assert g.passed is False and "师姐" in "".join(g.evidence)


def test_keywords_must_not_include_present_fails():
    g = grade_keywords("这章写了二中", must_include=None, must_not_include=["二中"])
    assert g.passed is False


def test_keywords_clean_passes():
    g = grade_keywords("师姐登场了", must_include=["师姐"], must_not_include=["二中"])
    assert g.passed is True


def test_aitell_flip_sentence_caught():
    # AI 翻转句(「不是…而是…」式)该被抓
    flip = "他不是不想说,而是不敢说。" * 3
    g = grade_aitell(flip, anchors=[], max_hits=0)
    assert g.passed is False and g.score < 1.0


def test_aitell_anchor_exempts():
    # 作者签名句在 anchors 里 → 豁免,不算 AI 腔
    g = grade_aitell("他没说话。", anchors=["他没说话。"], max_hits=0)
    assert g.passed is True
```

(**关键**:先 `.venv/bin/python -c "from evals.graders import grade_aitell, grade_keywords; help(...)"` 或读 graders.py:58/71/81 确认参数名/顺序/AI翻转句的真实判据——上面的断言按侦察的维度名写,若 grade_aitell 的 anchors 参数名或翻转句判据不同,以真实代码为准改测试,别改 graders.py。若某反例构造不出命中,读 graders 的正则/词表挑一个真能命中的。)

- [ ] **Step 2: 跑测试**

Run: `.venv/bin/python -m pytest tests/test_eval_graders.py -v`
Expected: 全绿(这是给既有正确逻辑补网,应直接过;若红,是断言构造不对——改测试不改 graders)。

- [ ] **Step 3: Commit**

```bash
git add tests/test_eval_graders.py
git commit -m "$(cat <<'EOF'
test(eval): 确定性grader正反例+边界护栏——检测器被改坏有测试网接住

grade_keywords(必含缺失/禁词出现/干净)、grade_aitell(翻转句命中/anchor豁免)各补
正反例。与契约样本(P0-A靠数据)互补:单测靠代码。不改grader逻辑。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 全量回归 + 故障注入验收(控制者)

**Files:** 无代码改动;只验证。

- [ ] **Step 1: 全量 + eval 自跑**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿(542 基线 + Phase 0 新增,约 560+)。
Run: `.venv/bin/python -m evals.run_eval --gate; echo "码=$?"`
Expected: `✅ 无回归` + `码=0`。

- [ ] **Step 2: 故障注入验收(spec §Phase0 验收的三条,手工做完复原)**

逐条做、看到红、复原:
1. **坏检测器**:临时让 `grade_keywords` 恒返 `passed=True`(改一行)→ `.venv/bin/python -m evals.run_eval --gate` → 应报 case_02 `通过→失败`(契约违约)+ 码 1。**复原**。
2. **未固化 case**:临时 `cp -r evals/cases/case_01_clean evals/cases/case_tmp` → `--gate` → 应报 case_tmp `未固化` + 码 1。**删掉 case_tmp**。
3. **删 baseline case**:临时把 baseline.json 里 case_01 整段删掉 → `--gate` → 应报 case_01 `消失` + 码 1。**git checkout 复原**。
4. **infra 区分**:`.venv/bin/python -m evals.run_eval --gate --baseline-file /tmp/nope.json; echo $?` → 码 2(不是 1)。

- [ ] **Step 3: 双消费方语义核对**

确认 `.github/workflows/ci.yml:36` 与 `release.yml:35` 的调用是 `python -m evals.run_eval --gate`(无参数变化),退出码 0=通过/非 0=有问题的语义在本 Phase 后仍成立(Task 4 只把「无 case/无 baseline」从 1 细分到 2,通过仍是 0、真回归仍是 1——CI 的 `if 非0则失败` 不受影响)。**不改 workflow 文件。**

- [ ] **Step 4: 汇报**

向用户报:Phase 0 新增测试计数、故障注入四条的红/复原截图或输出、eval 自跑绿。不合并——等用户验收(且 eval 分支策略见下)。

---

## Phase 1-4 预告(本计划不含,各自另立)

| 期 | 内容 | 前置 |
|---|---|---|
| Phase 1 | Generation suite:`run_pipeline`(agents.py:596)真调五 Agent 生成正文再 grade;Fixture/Generation 二分;manifest 记 commit/model/hash | Phase 0 门禁可信 |
| Phase 2 | schema/rubric + 小型平衡数据集(dev/calibration/holdout);**需第二人工标注者** | Phase 1 |
| Phase 3 | LLM-Judge 校准:结构化 JSON verdict + 人-人/Judge-人 kappa/PRF meta-eval,预注册阈值 | Phase 2 |
| Phase 4 | 分层 CI(PR 跑 fixture、手动/定时跑真 Judge)+ 可追溯报告 | Phase 3 |

**分支策略**(侦察建议 + 控制者附议):eval 工作与伙伴 v1a **正交**(43 commit 没碰 evals/)。建议 v1a 先合 main、eval 从干净 main 开分支;若 v1a 仍要调,eval 也可从当前分支尖开(正交,后 rebase 无痛)。Phase 2-3 的**第二标注者是唯一不能自动化的环节**(Judge-人校准的「人」不能是 LLM),需提前找人。
