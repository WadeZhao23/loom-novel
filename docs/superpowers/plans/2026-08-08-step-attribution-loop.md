# 棒级归因闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Generation suite 的分数能直接翻译成「改哪一棒的 prompt」，而不只是「这章掉分了」。

**Architecture:** `run_pipeline` 已把每一棒的完整产出写进 ledger（`loom/agents.py:707`），`evals/generate.py` 跑完只拷终稿就把它扔了。把 ledger 收进 `run_dir/steps/`，给每棒产物挂各自的**确定性**体检项（每项都是「上游有、这一棒输出里没了」的差分），再用 `--repeat N` 多次运行取分布对抗 temp=0.9 无 seed 的噪声。

**Tech Stack:** Python 3.11 · pytest · 纯标准库（零新运行时依赖；只加 `pyyaml` 到 `[dev]`）

**Spec:** `docs/superpowers/specs/2026-08-08-step-attribution-loop-design.md`

## Global Constraints

- **evalapi 单一接缝**：`evals/` 只准 `from loom.evalapi import ...`，禁止 import loom 私有符号。需要新能力就先往 `loom/evalapi.py` 加导出 + 进 `__all__`。门面 import 失败**不降级**。
- **不造数**：真人/真机才有的数留空位。N 次运行里有 M 次 infra，报告写「N 次里 M 次有效」，**绝不用 M 次均值冒充 N 次**。
- **产品侧不打分不阻断**（ADR-0002 / ADR-0006）：分数、阈值、区间只活在 `evals/`。`loom/gates.py`、`loom/parse.py`、UI 一个字不动。
- **两套 suite 分离**：Fixture 零 key 进 PR CI；Generation 要 key，手动/定时。
- **退出码三态**：0=通过 / 1=质量回归 / 2=infra。
- **别碰 `loom/rewrite.py`**：有独立任务正在另一个会话里改它。本计划不触碰该文件。
- **旁路 ≠ 失败**：ledger 里缺某棒（WYSIWYG 旁路或续跑跳过）记 `skipped`，**不记 0 分**。
- 提交信息用中文，与仓库既有风格一致；结尾带 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 |
|---|---|
| `loom/evalapi.py` | 改：加棒级归因接缝导出 |
| `loom/agents.py` | 改：`_scene_range` 数值化（`_scene_budget` 的单一真相） |
| `evals/stepgraders.py` | **新**：棒级体检项，纯确定性，零 LLM |
| `evals/aggregate.py` | **新**：N 次运行 → 分布（中位数/区间/有效次数） |
| `evals/generate.py` | 改：收 ledger、`--repeat`、`--compare`、batch 落盘 |
| `evals/graders.py` | 改：LLM grader 解析失败判 infra |
| `evals/run_eval.py` | 改：`--judge` 与 `--gate` 互斥 |
| `evals/gen_cases/gen_02_*/` | **新**：无 overlay 细纲的 case，让大纲师真跑 |
| `loom/continuity.py` | 改：修四个 bug + LLM 侧失败不再裸 except 吞 |
| `pyproject.toml` | 改：`[dev]` 加 `pyyaml` |
| `tests/test_eval_stepgraders.py` | **新** |
| `tests/test_eval_aggregate.py` | **新** |
| `tests/test_eval_generate.py` | 改：收 ledger / gen_02 八调契约 |
| `tests/test_continuity.py` | 改：四条回归测试，fixture 状态放**非第 1 章** |

---

## Task 1: 补 pyyaml，让 4 个 CI 结构护栏真正生效

**Files:**
- Modify: `pyproject.toml:21`
- Test: `tests/test_eval_workflows.py`（已存在，验证它不再 skip）

**Interfaces:**
- Consumes: 无
- Produces: 无（纯依赖修复）

**Why:** `ci.yml` 装的是 `pip install -e ".[dev]"`，而 `dev = ["pytest>=8.0"]` 不含 pyyaml。`tests/test_eval_workflows.py:14,25,34,45` 四个测试全以 `pytest.importorskip("yaml")` 开头，因此在 GitHub Actions 上**全部静默 skip**。它们守的是「PR CI 绝不碰 secret」「eval-real 绝不挂 `pull_request`（防 pwn request 泄 key）」——在唯一需要它们的地方是哑的。

- [ ] **Step 1: 先证明它现在是哑的**

```bash
python -m pytest tests/test_eval_workflows.py -v 2>&1 | tail -20
```

记下当前有几个 passed、几个 skipped。若本机装了 pyyaml 会全 passed —— 那就用下面这条模拟 CI 环境：

```bash
python -c "
import subprocess, sys
r = subprocess.run([sys.executable, '-c', 'import yaml; print(yaml.__file__)'], capture_output=True, text=True)
print('本机 yaml:', r.stdout.strip() or r.stderr.strip())
"
```

- [ ] **Step 2: 加依赖**

`pyproject.toml` 第 21 行：

```toml
dev = ["pytest>=8.0", "pyyaml>=6.0"]   # 跑测试:pip install -e ".[dev]" && pytest
```

- [ ] **Step 3: 装上并确认 4 个测试真的跑**

```bash
pip install -e ".[dev]" && python -m pytest tests/test_eval_workflows.py -v
```

Expected: 4 passed, **0 skipped**。若有 skipped，说明 `importorskip` 还在挡——检查 pyyaml 是否装进了当前解释器。

- [ ] **Step 4: 全量回归**

```bash
python -m pytest tests/ -q && python -m evals.run_eval --gate; echo "gate exit=$?"
```

Expected: 全绿；`gate exit=0`。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'MSG'
fix(ci): dev 依赖补 pyyaml——4 个 CI 结构护栏此前在 CI 上全静默 skip

tests/test_eval_workflows.py 的四个测试都以 importorskip("yaml") 开头，
而 ci.yml 装的 ".[dev]" 只有 pytest。它们守的是「PR CI 绝不碰 secret」
「eval-real 绝不挂 pull_request(防 pwn request 泄 key)」——在唯一需要
它们的地方从未生效。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 2: LLM grader 解析失败判 infra，不再 fail-open

**Files:**
- Modify: `evals/graders.py:205-232`
- Test: `tests/test_eval_graders.py`（若不存在则创建）

**Interfaces:**
- Consumes: `GraderResult`（`evals/graders.py:29-44`）
- Produces: `grade_quality_llm` / `grade_deslop_llm` 在解析失败时返回 `GraderResult(..., passed=False, gating=False, detail="[infra] …")`

**Why:** `parse_critic_verdict` 解析不出条目 → `n=0` → `score=1/(1+0)=1.0` → `passed=True`。模型换成编号列表或散文段落，就静默判「无硬伤=满分通过」。这与 `evals/judge.py:168-184` 已有的 `infra_error` 口径矛盾，也违背 `graders.py:9-11` 自己写的原则。

**判据**：`parse_critic_verdict` 返回空列表 **且** 判词里没有「通过」二字 → infra。（模型如约只回一行「通过」是合法的零硬伤，必须与解析失败区分开。）

- [ ] **Step 1: 写失败测试**

Create `tests/test_eval_graders.py`：

```python
"""grader 的失败路径:LLM 判词解析不出时必须判 infra,绝不假装满分通过。"""
from evals.graders import grade_deslop_llm, grade_quality_llm


class _FixedBackend:
    """恒定回同一段判词,用来钉死解析分支。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
        return self.reply


def test_quality_llm_unparsable_verdict_is_infra_not_pass():
    # 模型回编号列表(prompt 要的是 `- ` 开头),parse_critic_verdict 抓不到条目
    be = _FixedBackend("1. 人物OOC:主角性格突变\n2. 断钩子:章末平淡")
    g = grade_quality_llm("正文", "设定", be)
    assert g.passed is False, "解析失败不得判通过"
    assert g.gating is False, "infra 不该参与 gating"
    assert g.detail.startswith("[infra]")
    assert g.score == 0.0


def test_quality_llm_explicit_pass_is_a_real_pass():
    # 模型如约只回一行「通过」= 合法的零硬伤,必须与解析失败区分开
    g = grade_quality_llm("正文", "设定", _FixedBackend("通过"))
    assert g.passed is True
    assert g.gating is True
    assert g.score == 1.0


def test_deslop_llm_unparsable_verdict_is_infra_not_pass():
    be = _FixedBackend("整体读下来还行，没什么大问题。")
    g = grade_deslop_llm("正文", "指纹", be)
    assert g.passed is False
    assert g.gating is False
    assert g.detail.startswith("[infra]")


def test_deslop_llm_explicit_pass_is_a_real_pass():
    g = grade_deslop_llm("正文", "指纹", _FixedBackend("通过"))
    assert g.passed is True and g.gating is True
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_graders.py -v
```

Expected: `test_quality_llm_unparsable_verdict_is_infra_not_pass` 与 `test_deslop_llm_unparsable_verdict_is_infra_not_pass` FAIL（现在会 `passed is True`）；两个 `explicit_pass` 测试 PASS。

- [ ] **Step 3: 实现**

`evals/graders.py`，在 `# ─── LLM-judge grader ───` 分隔线下方、`grade_quality_llm` 之前插入：

```python
def _verdict_is_unparsable(verdict: str, n_issues: int) -> bool:
    """判词解析不出任何条目、且没有明确说「通过」→ infra(格式不合),不是「零硬伤」。

    prompt 约定:无硬伤只回一行「通过」;有则每条一行 `- 类别 | 问题 | 证据:"引文"`。
    模型改回编号列表 / 散文段落时 parse_critic_verdict 抓 0 条——旧代码把它当满分,
    这正是门禁最危险的失败模式(被测物坏了却变绿)。
    """
    return n_issues == 0 and "通过" not in verdict
```

再把两个 grader 的解析段改掉。`grade_quality_llm` 的 `issues = parse_critic_verdict(verdict)` 起替换为：

```python
    issues = parse_critic_verdict(verdict)
    n = len(issues)
    if _verdict_is_unparsable(verdict, n):
        return GraderResult("质检·LLM", 0.0, False, weight, gating=False,
                            detail=f"[infra] 判词解析不出条目也没说「通过」 — {verdict[:60]!r}")
    return GraderResult("质检·LLM", round(1.0 / (1.0 + n), 3), n == 0, weight,
                        detail=f"复审挑出 {n} 处硬伤",
                        evidence=[f"{i.kind}:{i.desc}" for i in issues])
```

`grade_deslop_llm` 同款：

```python
    issues = parse_critic_verdict(verdict)
    n = len(issues)
    if _verdict_is_unparsable(verdict, n):
        return GraderResult("去AI味·LLM", 0.0, False, weight, gating=False,
                            detail=f"[infra] 判词解析不出条目也没说「通过」 — {verdict[:60]!r}")
    return GraderResult("去AI味·LLM", round(1.0 / (1.0 + n), 3), n == 0, weight,
                        detail=f"复审命中 {n} 处 AI 腔",
                        evidence=[f"{i.kind}:{i.desc}" for i in issues])
```

- [ ] **Step 4: 跑测试确认全绿**

```bash
python -m pytest tests/test_eval_graders.py -v && python -m pytest tests/ -q
```

Expected: 4 passed；全量绿。

- [ ] **Step 5: Commit**

```bash
git add evals/graders.py tests/test_eval_graders.py
git commit -m "$(cat <<'MSG'
fix(eval): LLM grader 解析失败判 infra——不再把「抓 0 条」当满分通过

parse_critic_verdict 抓不到条目时 score=1/(1+0)=1.0 且 passed=True。
模型换成编号列表或散文段落就静默满分——门禁最危险的失败模式。
与 judge.py 的 infra_error 口径对齐;明确回「通过」仍是合法零硬伤。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 3: `--judge` 与 `--gate` 互斥

**Files:**
- Modify: `evals/run_eval.py`（`main` 的参数校验段）
- Test: `tests/test_eval_cli.py`（已存在，追加）

**Interfaces:**
- Consumes: 无
- Produces: `run_eval.main(["--judge", "--gate"])` → 返回 `2`

**Why:** 两个 LLM grader 成功路径上 `gating=True`（`graders.py:35` 默认 True，只在 except 分支设 False），但 `baseline.json` 里没有它们的条目。`--judge --gate` 同传时权重和从 0.70 跳到 1.00，**所有 case 分数整体位移** → 与 no-judge 基线比对必然产生大量伪回归；且 LLM 结果在 temp=0.9 下不可复现，门禁变掷骰子。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_cli.py` 末尾：

```python
def test_judge_and_gate_are_mutually_exclusive(tmp_path, capsys):
    """--judge --gate 同传必须拒绝:LLM grader gating=True 会把权重和从 0.70 顶到 1.00,
    所有 case 分数整体位移,与 no-judge 基线比对必然伪回归。"""
    from evals.run_eval import main
    code = main(["--judge", "--gate", "--cases", str(tmp_path)])
    assert code == 2, "同传应判 infra(2),不是跑完再比"
    out = capsys.readouterr().out
    assert "--judge" in out and "--gate" in out
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_cli.py::test_judge_and_gate_are_mutually_exclusive -v
```

Expected: FAIL —— 现在会走到「没找到 case」返回 2，但**理由不对**；更可能是先尝试初始化后端再返回 2。断言 `out` 含两个 flag 名会失败。

- [ ] **Step 3: 实现**

`evals/run_eval.py`，在 `args = ap.parse_args(argv)` 之后、`backend = None` 之前插入：

```python
    if args.judge and args.gate:
        # LLM grader 成功路径 gating=True 且不在 baseline.json 里:同传会把权重和
        # 从 0.70 顶到 1.00,所有 case 分数整体位移 → 与 no-judge 基线比对必然伪回归;
        # 且 LLM 在 temperature=0.9 无 seed 下不可复现,门禁会变成掷骰子。
        print("✗ --judge 与 --gate 不能同传:LLM grader 会改变权重和(0.70→1.00),"
              "与基线口径不一致必然产生伪回归。要门禁就跑确定性的 --gate;"
              "要 LLM 复审就单独跑 --judge。")
        return 2   # infra:用法错误,不是质量回归
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_cli.py -v && python -m evals.run_eval --gate; echo "gate exit=$?"
```

Expected: 测试全绿；`gate exit=0`（单传 `--gate` 不受影响）。

- [ ] **Step 5: Commit**

```bash
git add evals/run_eval.py tests/test_eval_cli.py
git commit -m "$(cat <<'MSG'
fix(eval): --judge 与 --gate 互斥——挡住权重跳变导致的伪回归

两个 LLM grader 成功路径 gating=True 却不在 baseline.json 里。同传时
权重和 0.70→1.00,所有 case 分数整体位移,与基线比对必然伪回归;
且 temp=0.9 无 seed 不可复现,门禁会变掷骰子。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 4: evalapi 加棒级归因接缝

**Files:**
- Modify: `loom/agents.py:529-537`（`_scene_budget` 数值化）
- Modify: `loom/evalapi.py`
- Test: `tests/test_eval_generate.py`（追加接缝导出断言）

**Interfaces:**
- Consumes: 无
- Produces: `loom.evalapi` 新导出 —— `PIPELINE: list[str]`、`load_ledger(root, n) -> dict`、`ledger_path(root, n) -> Path`、`scene_range(chapter_target) -> tuple[int, int]`、`parse_scene_budgets(outline) -> list[int]`、`split_edit_note(text) -> tuple[str, str]`、`STEP_SHORT_BUDGETS: dict[str, int]`

**Why:** 棒级体检项要复用产品已有的判据（场次预算、留痕切分、工序表），spec 明令**别在 evals 里重写一套**，否则两边会漂。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`（放在 `_GEN_SEAM` 常量下方）：

```python
_STEP_SEAM = ("PIPELINE", "load_ledger", "ledger_path", "scene_range",
              "parse_scene_budgets", "split_edit_note", "STEP_SHORT_BUDGETS")


def test_evalapi_step_attribution_seam_exports():
    """棒级归因接缝:evals 复用产品判据必须走门面,不得在 evals 里重写一套(会漂)。"""
    for name in _STEP_SEAM:
        assert hasattr(evalapi, name), f"evalapi 缺棒级归因接缝导出:{name}"
        assert name in evalapi.__all__, f"{name} 未进 evalapi.__all__"


def test_scene_range_matches_scene_budget_string():
    """数值形态与字符串形态必须同源——否则 evals 与 prompt 会各说各话。"""
    from loom.agents import _scene_budget
    for target, expect in ((800, (2, 3)), (2000, (3, 4)), (5000, (4, 6))):
        lo, hi = evalapi.scene_range(target)
        assert (lo, hi) == expect
        assert _scene_budget(target) == f"拆 {lo}-{hi} 场"


def test_pipeline_seam_is_the_five_steps():
    assert evalapi.PIPELINE == ["设定师", "大纲师", "写手", "编辑", "润色师"]
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py -k "step_attribution or scene_range or pipeline_seam" -v
```

Expected: FAIL with `evalapi 缺棒级归因接缝导出:PIPELINE`。

- [ ] **Step 3a: `_scene_budget` 数值化（单一真相）**

`loom/agents.py`，把 `_scene_budget` 整个替换为：

```python
def _scene_range(chapter_target: int) -> tuple[int, int]:
    """章目标字数 →(最少场次, 最多场次)。场次预算的**单一真相**:
    _scene_budget 的字符串形态由它派生,evals 的棒级体检也读它——两边永不漂。"""
    if chapter_target <= 1500:
        return (2, 3)
    if chapter_target <= 3000:
        return (3, 4)
    return (4, 6)


def _scene_budget(chapter_target: int) -> str:
    """章目标字数 → 细纲场次预算(喂 prompt 的字符串形态)。超长的真根因:大纲师不知道
    章目标,按惯例拆 3-6 场,写手照多场细纲每场写透 → 2000 字目标干出 6000+。"""
    lo, hi = _scene_range(chapter_target)
    return f"拆 {lo}-{hi} 场"
```

- [ ] **Step 3b: 加 evalapi 导出**

`loom/evalapi.py`，在既有 Generation 接缝导入块之后追加：

```python
# ── 棒级归因接缝(2026-08)──纯再导出,零逻辑:evals 的棒级体检项要复用产品
#    已有的判据(工序表/场次预算/留痕切分/ledger 读取),别在 evals 里重写一套。
from .agents import PIPELINE, _SHORT as STEP_SHORT_BUDGETS
from .agents import _parse_scene_budgets as parse_scene_budgets
from .agents import _scene_range as scene_range
from .ledger import load_ledger
from .parse import split_edit_note
from .paths import ledger_path
```

再把七个名字加进 `__all__`（保持字母序不是硬要求，与既有风格一致即可）：

```python
    "PIPELINE",
    "STEP_SHORT_BUDGETS",
    "ledger_path",
    "load_ledger",
    "parse_scene_budgets",
    "scene_range",
    "split_edit_note",
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_generate.py -v && python -m pytest tests/ -q
```

Expected: 全绿。特别确认 `test_scene_range_matches_scene_budget_string` 过——它钉死两种形态同源。

- [ ] **Step 5: Commit**

```bash
git add loom/agents.py loom/evalapi.py tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): evalapi 加棒级归因接缝 + _scene_budget 数值化

棒级体检要复用产品已有判据(工序表/场次预算/留痕切分/ledger),
走门面再导出而不是在 evals 里重写一套——重写必漂。
_scene_range 成为场次预算的单一真相,_scene_budget 字符串由它派生。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 5: 收 ledger 五棒产物进 run_dir

**Files:**
- Modify: `evals/generate.py`（新增 `collect_steps`，接进 `generate_one`）
- Test: `tests/test_eval_generate.py`

**Interfaces:**
- Consumes: `evalapi.PIPELINE`、`evalapi.load_ledger`（Task 4）
- Produces: `collect_steps(project: Path, chapter_n: int, run_dir: Path) -> dict[str, str | None]` —— 返回 `{role: output_text}`；被旁路/跳过的棒值为 `None`。同时把每棒落成 `run_dir/steps/<role>.md`（`None` 的棒不落文件）。

**Why:** `run_pipeline` 对 `PIPELINE` 里每个 role 都调了 `ledger.record_step(..., output, ...)`，`output` 是该棒完整产物原文。`generate_one` 在 `line 145` 就持有临时项目根，跑完却只拷了终稿。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`：

```python
def test_generate_one_collects_five_step_outputs(tmp_path):
    """五棒产物必须落进 run_dir/steps/;被 WYSIWYG 旁路的大纲师记 skipped(不是 0 分)。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path)          # with_outline=True → 大纲师被旁路
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    steps_dir = run_dir / "steps"
    assert steps_dir.is_dir()
    assert (steps_dir / "设定师.md").read_text(encoding="utf-8") == _SETTER
    assert (steps_dir / "写手.md").read_text(encoding="utf-8") == _DRAFT
    assert (steps_dir / "润色师.md").is_file()
    # 大纲师被 overlay 细纲旁路 → 没有产物文件,且 steps.json 明确记 skipped
    assert not (steps_dir / "大纲师.md").exists()
    meta = json.loads((run_dir / "steps.json").read_text(encoding="utf-8"))
    assert meta["大纲师"] == "skipped", "旁路≠失败,必须记 skipped 不记 0 分"
    assert meta["设定师"] == "collected"


def test_collect_steps_without_outline_overlay_collects_outliner(tmp_path):
    """无 overlay 细纲时大纲师真跑,产物必须被收到。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path, with_outline=False)
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_8)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    assert (run_dir / "steps" / "大纲师.md").read_text(encoding="utf-8") == _OUTLINE
    meta = json.loads((run_dir / "steps.json").read_text(encoding="utf-8"))
    assert meta["大纲师"] == "collected"
```

同时在 `_GEN_RUN_7` 下方追加 8 调脚本（无 overlay 细纲时大纲师插在设定师之后）：

```python
# 8 调脚本(无 overlay 细纲 → 大纲师真跑):设定/大纲/写手/编辑/质检"通过"/润色/去AI味"通过"/标题。
_OUTLINE = ("场景一 · 当夜二更 · 废矿深处 · 沈砚独自一人 · 醒来验伤、确认重生 · 约80字\n"
            "场景二 · 同夜稍后 · 矿道岔口 · 沈砚与巡矿人 · 矿灯下照面、藏起异状 · 约70字\n"
            "场景三 · 拂晓前 · 矿口 · 沈砚 · 听见追兵、倒计时钩 · 约50字\n"
            "爆发点落在场景三。章首接上一章矿口火把。章末钩类型:〔危机迫近〕。")
_GEN_RUN_8 = [_SETTER, _OUTLINE, _DRAFT, _EDITED, "通过", _POLISHED, "通过", "矿灯"]
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py -k "collects_five_step or collect_steps_without" -v
```

Expected: FAIL with `assert steps_dir.is_dir()` —— 目录不存在。

- [ ] **Step 3: 实现**

`evals/generate.py`，把 `from loom.evalapi import (...)` 块扩成：

```python
from loom.evalapi import (
    PIPELINE,
    get_backend,
    load_config,
    load_ledger,
    save_config,
    scaffold_init,
    run_pipeline,
)
```

在 `_grade_candidate` 之前插入：

```python
def collect_steps(project: Path, chapter_n: int, run_dir: Path) -> dict[str, str | None]:
    """把 ledger 里五棒的完整产出收进 run_dir/steps/,并落一份 steps.json 记状态。

    run_pipeline 对 PIPELINE 里每个 role 都调了 ledger.record_step(role, output, …),
    output 就是该棒产物原文——机制本来就在,此前只是跑完没人收。

    某棒缺席有两种正当原因:①WYSIWYG 旁路(细纲文件已存在,大纲师不调模型)
    ②断点续跑跳过。两者都记 "skipped",**绝不记 0 分**——旁路不是失败。
    """
    steps_dir = run_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    led = load_ledger(project, chapter_n)
    recorded = led.get("steps", {}) or {}
    out: dict[str, str | None] = {}
    status: dict[str, str] = {}
    for role in PIPELINE:
        entry = recorded.get(role)
        text = (entry or {}).get("output") if isinstance(entry, dict) else None
        if text:
            (steps_dir / f"{role}.md").write_text(text, encoding="utf-8")
            out[role] = text
            status[role] = "collected"
        else:
            out[role] = None
            status[role] = "skipped"
    (run_dir / "steps.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
```

在 `generate_one` 里，把 `result = _grade_candidate(run_dir, case, final)` 那一行**之前**插入：

```python
    steps = collect_steps(project, case["chapter_n"], run_dir)
```

（`steps` 下一个 Task 才会被消费；本 Task 只负责收集与落盘。）

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_generate.py -v && python -m pytest tests/ -q
```

Expected: 全绿，含既有的 7 调契约测试（收 ledger 不改变调用数）。

- [ ] **Step 5: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): 收 ledger 五棒产物进 run_dir——棒级归因的地基

run_pipeline 早就把每一棒的完整产出写进 ledger(agents.py:707),
generate.py 跑完只拷终稿就扔了。收进 run_dir/steps/ + steps.json。
旁路(WYSIWYG)与续跑跳过都记 skipped,不记 0 分——旁路不是失败。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 6: stepgraders A —— 设定师 / 写手 / 润色师

**Files:**
- Create: `evals/stepgraders.py`
- Test: `tests/test_eval_stepgraders.py`

**Interfaces:**
- Consumes: `evals.graders.GraderResult`；`evalapi.detect_aitell`、`evalapi.STEP_SHORT_BUDGETS`
- Produces:
  - `grade_setter(anchor: str | None, hardfact_terms: list[str]) -> list[GraderResult]`
  - `grade_writer(draft: str | None, target_chars: int, must_include: list[str], anchors: list[str]) -> list[GraderResult]`
  - `grade_polisher(polished: str | None, edited: str | None, anchors: list[str]) -> list[GraderResult]`
  - `skipped(step: str, item: str) -> GraderResult` —— 统一的 skipped 形状（`score=0.0, passed=True, gating=False, detail="[skipped] …"`）

**Why:** 每项都是「上游有、这一棒输出里没了」的差分，命中就能定位到棒。全部确定性、零 LLM。

**skipped 的形状约定**：`passed=True` + `gating=False` + `score=0.0`。`passed=True` 是为了不让「这棒没跑」污染通过判定；`gating=False` 让它不参与门禁；聚合时按 `detail` 前缀 `[skipped]` 排除出分布（Task 10）。

- [ ] **Step 1: 写失败测试**

Create `tests/test_eval_stepgraders.py`：

```python
"""棒级体检项:每项都是「上游有、这一棒输出里没了」的差分。纯确定性,零 LLM。"""
from evals.stepgraders import (
    grade_polisher,
    grade_setter,
    grade_writer,
    skipped,
)


def _by_name(results, name):
    for r in results:
        if r.name == name:
            return r
    raise AssertionError(f"没有名为 {name} 的体检项:{[r.name for r in results]}")


# ── skipped 形状 ───────────────────────────────────────────────────────────
def test_skipped_shape_does_not_pollute_gating():
    g = skipped("大纲师", "细纲覆盖必含要素")
    assert g.passed is True, "这棒没跑不该判失败"
    assert g.gating is False
    assert g.detail.startswith("[skipped]")


# ── 设定师 ─────────────────────────────────────────────────────────────────
def test_setter_flags_missing_hardfact_term():
    res = grade_setter("本章设定锚点:主角在废矿。", ["逆息", "F~SSS"])
    g = _by_name(res, "设定师·硬设定专名")
    assert g.passed is False
    assert any("逆息" in e for e in g.evidence)
    assert any("F~SSS" in e for e in g.evidence)


def test_setter_passes_when_all_terms_present():
    res = grade_setter("锚点:逆息体质,力量体系 F~SSS。", ["逆息", "F~SSS"])
    assert _by_name(res, "设定师·硬设定专名").passed is True


def test_setter_flags_overlong_anchor():
    res = grade_setter("锚" * 400, [])
    g = _by_name(res, "设定师·锚点篇幅")
    assert g.passed is False
    assert "350" in g.detail


def test_setter_skipped_when_no_output():
    res = grade_setter(None, ["逆息"])
    assert all(g.gating is False and g.detail.startswith("[skipped]") for g in res)


# ── 写手 ───────────────────────────────────────────────────────────────────
def test_writer_flags_short_draft():
    res = grade_writer("短稿。", 600, [], [])
    g = _by_name(res, "写手·初稿篇幅")
    assert g.passed is False
    assert "600" in g.detail


def test_writer_flags_dropped_must_include():
    res = grade_writer("沈砚睁开眼。" * 60, 300, ["矿灯"], [])
    g = _by_name(res, "写手·必含要素")
    assert g.passed is False
    assert any("矿灯" in e for e in g.evidence)


def test_writer_counts_aitell_hits():
    res = grade_writer("他不是累，而是怕。" * 40, 300, [], [])
    g = _by_name(res, "写手·AI翻转句")
    assert g.detail.startswith("命中")


# ── 润色师 ─────────────────────────────────────────────────────────────────
def test_polisher_flags_aitell_not_reduced():
    edited = "他不是累，而是怕。" * 5
    polished = edited                      # 一处都没擦掉
    g = _by_name(grade_polisher(polished, edited, []), "润色师·AI味下降")
    assert g.passed is False
    assert "0" in g.detail


def test_polisher_passes_when_aitell_drops():
    edited = "他不是累，而是怕。" * 5
    polished = "他累，也怕。" * 5           # 翻转句被擦掉
    assert _by_name(grade_polisher(polished, edited, []), "润色师·AI味下降").passed is True


def test_polisher_flags_shrinkage():
    edited = "字" * 1000
    polished = "字" * 500                   # 越擦越短一半
    g = _by_name(grade_polisher(polished, edited, []), "润色师·篇幅保持")
    assert g.passed is False


def test_polisher_skipped_when_upstream_missing():
    res = grade_polisher("终稿", None, [])
    assert all(g.gating is False for g in res)
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_stepgraders.py -v
```

Expected: `ModuleNotFoundError: No module named 'evals.stepgraders'`。

- [ ] **Step 3: 实现**

Create `evals/stepgraders.py`：

```python
"""棒级体检项:给流水线每一棒的**中间产物**各挂一组确定性检查。

为什么要有它:章级总分只能告诉你「这章掉分了」,翻译不成「改哪一棒的 prompt」。
每一项都设计成「上游有、这一棒输出里没了」的**差分**,所以命中就能定位到棒。

红线:
- 全部确定性、零 LLM 调用——同一份文本跑两次结果必须逐字相同。
- 对 loom 的复用只走 loom.evalapi 门面,不 import 私有符号。
- 只活在 evals 里给开发者做回归归因,绝不进产品 UI/用户路径(ADR-0002)。
- 某棒缺席(WYSIWYG 旁路 / 断点续跑跳过)记 skipped,**不记 0 分**——旁路不是失败。
"""

from __future__ import annotations

import re

from loom.evalapi import STEP_SHORT_BUDGETS, detect_aitell, split_edit_note

from .graders import GraderResult

_WS = re.compile(r"\s+")


def _chars(text: str) -> int:
    """去空白字数。与 graders._body_len 同口径,但中间产物没有 H1 标题,不必剥。"""
    return len(_WS.sub("", text or ""))


def skipped(step: str, item: str) -> GraderResult:
    """这一棒没有产物时的统一形状。

    passed=True 是刻意的:「这棒没跑」不该污染通过判定;gating=False 让它不进门禁;
    聚合侧按 detail 的 [skipped] 前缀把它排除出分布(不拉低中位数)。
    """
    return GraderResult(f"{step}·{item}", 0.0, True, weight=0.0, gating=False,
                        detail=f"[skipped] {step} 这一棒没有产物(旁路或续跑跳过)")


# ─────────────────────────────── 设定师 ───────────────────────────────

def grade_setter(anchor: str | None, hardfact_terms: list[str]) -> list[GraderResult]:
    """设定师产出「本章设定锚点」(≤350 字的语义选择)。

    体检两项:
    - 硬设定专名:case 声明必须带上的境界/金手指/地名等专名,锚点里在不在。
      锚点丢了专名,下游大纲师/写手就只能靠 hardfacts 直送兜底,是设定漂移的上游根因。
    - 锚点篇幅:超过 STEP_SHORT_BUDGETS["设定师"](350)说明它在复述整份世界观,
      会稀释下游 prompt。
    """
    if not anchor:
        return [skipped("设定师", "硬设定专名"), skipped("设定师", "锚点篇幅")]

    terms = hardfact_terms or []
    missing = [t for t in terms if t not in anchor]
    total = len(terms)
    score = 1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total)
    term_result = GraderResult(
        "设定师·硬设定专名", round(score, 3), not missing, weight=0.30,
        detail=f"声明 {total} 个硬设定专名,锚点缺 {len(missing)} 个",
        evidence=[f"锚点里没有:「{m}」" for m in missing])

    budget = STEP_SHORT_BUDGETS.get("设定师", 350)
    n = _chars(anchor)
    over = max(0, n - budget)
    len_result = GraderResult(
        "设定师·锚点篇幅", round(max(0.0, 1.0 - over / max(1, budget)), 3), over == 0,
        weight=0.10, detail=f"{n} 字(预算 {budget} 字)")
    return [term_result, len_result]


# 大纲师 / 编辑 的体检项在 Task 7 加(它们依赖 evalapi 的 parse_scene_budgets /
# scene_range / split_edit_note 接缝,单独一轮红-绿)。


# ──────────────────────────────── 写手 ────────────────────────────────

def grade_writer(draft: str | None, target_chars: int,
                 must_include: list[str], anchors: list[str]) -> list[GraderResult]:
    """写手产出「本章初稿」。这是第一份完整正文,建立后两棒的比较基准。

    体检三项:初稿篇幅 vs 章目标、必含要素命中、AI 翻转句命中数(初稿基线,
    供润色师那棒算「降了多少」)。
    """
    if draft is None:
        return [skipped("写手", "初稿篇幅"), skipped("写手", "必含要素"),
                skipped("写手", "AI翻转句")]

    n = _chars(draft)
    # 初稿容差刻意比终稿宽:后面还有编辑/润色两棒会动篇幅。只挡「离谱」。
    lo, hi = target_chars * 0.5, target_chars * 1.5
    len_ok = lo <= n <= hi
    d = 0.0 if len_ok else (lo - n if n < lo else n - hi)
    length = GraderResult("写手·初稿篇幅",
                          round(max(0.0, 1.0 - d / max(1, target_chars)), 3), len_ok,
                          weight=0.20, detail=f"{n} 字(章目标 {target_chars} ±50%)")

    must = must_include or []
    missing = [k for k in must if k not in draft]
    total = len(must)
    inc = GraderResult("写手·必含要素",
                       round(1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total), 3),
                       not missing, weight=0.30,
                       detail=f"必含 {total} 项,初稿缺 {len(missing)} 项",
                       evidence=[f"初稿里没有:「{m}」" for m in missing])

    hits = detect_aitell(draft, anchors or [])
    ai = GraderResult("写手·AI翻转句", round(1.0 / (1.0 + len(hits)), 3), True,
                      weight=0.0, gating=False,
                      detail=f"命中 {len(hits)} 处(初稿基线,供润色师那棒算降幅)",
                      evidence=[h.evidence for h in hits])
    return [length, inc, ai]


# ─────────────────────────────── 润色师 ───────────────────────────────

def grade_polisher(polished: str | None, edited: str | None,
                   anchors: list[str]) -> list[GraderResult]:
    """润色师产出「本章终稿」,职责是擦掉通用机器味、保住写作指纹。

    体检两项(全是 终稿 vs 改稿 的差分):
    - AI味下降:改稿里的 aitell 命中数,终稿必须 ≤ 它。没降 = 这一棒白跑。
    - 篇幅保持:被明令「绝不扩写」,同时也不该越擦越短。低于改稿 80% 就是擦过头。

    注:改稿带《本章改动留痕》围栏,算 AI 味与篇幅前必须先剥掉——留痕不是正文。
    """
    if polished is None or edited is None:
        return [skipped("润色师", "AI味下降"), skipped("润色师", "篇幅保持")]

    edited_body, _ = split_edit_note(edited)
    before = len(detect_aitell(edited_body, anchors or []))
    after = len(detect_aitell(polished, anchors or []))
    dropped = before - after
    # 改稿本来就零命中 → 终稿保持零即算达标(没有可降的)
    ai_ok = after <= before if before > 0 else after == 0
    ai = GraderResult("润色师·AI味下降",
                      round(1.0 if before == 0 else max(0.0, dropped / before), 3), ai_ok,
                      weight=0.35,
                      detail=f"改稿 {before} 处 → 终稿 {after} 处(降 {dropped} 处)")

    n_edit, n_pol = _chars(edited_body), _chars(polished)
    ratio = n_pol / max(1, n_edit)
    size_ok = 0.8 <= ratio <= 1.2
    size = GraderResult("润色师·篇幅保持", round(min(1.0, 1.0 - abs(1.0 - ratio)), 3), size_ok,
                        weight=0.10,
                        detail=f"改稿 {n_edit} → 终稿 {n_pol} 字(×{ratio:.2f},应在 0.8~1.2)")
    return [ai, size]
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_stepgraders.py -v
```

Expected: 全部 passed。（本 Task 只测 A 组三个函数；`grade_outliner` / `grade_editor` 的测试在 Task 7。）

- [ ] **Step 5: Commit**

```bash
git add evals/stepgraders.py tests/test_eval_stepgraders.py
git commit -m "$(cat <<'MSG'
feat(eval): stepgraders 模块 + 设定师/写手/润色师三棒体检项

每项都是「上游有、这一棒输出里没了」的差分,所以命中就能定位到棒。
纯确定性零 LLM,同一文本两次跑结果逐字相同。
旁路/续跑跳过统一记 skipped(passed=True + gating=False),不记 0 分。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 7: stepgraders B —— 大纲师 / 编辑

**Files:**
- Modify: `evals/stepgraders.py`（追加 `grade_outliner` / `grade_editor`）
- Test: `tests/test_eval_stepgraders.py`（追加）

**Interfaces:**
- Consumes: `evalapi.parse_scene_budgets`、`evalapi.scene_range`（Task 4）；`evalapi.split_edit_note`、`skipped`、`_chars`、`GraderResult`（Task 6）
- Produces: `grade_outliner(outline, chapter_target, must_include) -> list[GraderResult]`；`grade_editor(edited, draft, must_include) -> list[GraderResult]`

**Why:** 这两棒的体检项依赖 Task 4 新加的场次预算接缝，且逻辑最容易写错（场次区间、围栏三态、「别赖错棒」），单独一轮红-绿值得独立的 review gate。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_stepgraders.py`：

```python
from evals.stepgraders import grade_editor, grade_outliner

_GOOD_OUTLINE = ("场景一 · 当夜 · 矿底 · 沈砚 · 醒来验伤 · 约80字\n"
                 "场景二 · 稍后 · 矿道 · 沈砚与巡矿人 · 矿灯照面 · 约70字\n"
                 "场景三 · 拂晓 · 矿口 · 沈砚 · 听见追兵 · 约50字")


# ── 大纲师 ─────────────────────────────────────────────────────────────────
def test_outliner_flags_must_include_dropped_at_outline_layer():
    g = _by_name(grade_outliner(_GOOD_OUTLINE, 200, ["矿灯", "师姐"]), "大纲师·必含要素")
    assert g.passed is False
    assert any("师姐" in e for e in g.evidence)
    assert not any("矿灯" in e for e in g.evidence)


def test_outliner_scene_count_uses_product_scene_range():
    # 200 字目标 → scene_range 给 (2,3);上面细纲正好 3 场 → 达标
    assert _by_name(grade_outliner(_GOOD_OUTLINE, 200, []), "大纲师·场次数").passed is True
    # 5000 字目标 → 应 4-6 场,3 场不够
    g = _by_name(grade_outliner(_GOOD_OUTLINE, 5000, []), "大纲师·场次数")
    assert g.passed is False
    assert "4-6 场" in g.detail


def test_outliner_flags_missing_scene_budget_annotations():
    bare = "场景一 醒来。\n场景二 遇人。\n场景三 追兵。"
    g = _by_name(grade_outliner(bare, 200, []), "大纲师·篇幅预算")
    assert g.passed is False
    assert "没标" in g.detail


def test_outliner_flags_budget_sum_far_from_chapter_target():
    # 各场合计 200,章目标 3000 → 偏差远超 30%
    g = _by_name(grade_outliner(_GOOD_OUTLINE, 3000, []), "大纲师·篇幅预算")
    assert g.passed is False


def test_outliner_skipped_when_bypassed():
    res = grade_outliner(None, 200, ["矿灯"])
    assert all(g.gating is False and g.detail.startswith("[skipped]") for g in res)


# ── 编辑 ───────────────────────────────────────────────────────────────────
_DRAFT_FIX = "沈砚睁开眼，矿灯昏黄。他记得三年后的那一刀。"
_EDITED_OK = (_DRAFT_FIX + "\n<LOOM:EDIT-NOTE>\n- 钩子更硬。\n</LOOM:EDIT-NOTE>")


def test_editor_fence_pair_ok():
    assert _by_name(grade_editor(_EDITED_OK, _DRAFT_FIX, []), "编辑·留痕围栏").passed is True


def test_editor_flags_unclosed_fence():
    bad = _DRAFT_FIX + "\n<LOOM:EDIT-NOTE>\n- 忘了收尾。"
    g = _by_name(grade_editor(bad, _DRAFT_FIX, []), "编辑·留痕围栏")
    assert g.passed is False
    assert "未闭合" in g.detail


def test_editor_flags_no_note_at_all():
    g = _by_name(grade_editor(_DRAFT_FIX, _DRAFT_FIX, []), "编辑·留痕围栏")
    assert g.passed is False


def test_editor_flags_must_include_dropped_by_editor():
    """初稿有、改稿没了 —— 这比「初稿本来就缺」严重得多,必须单独抓。"""
    edited = "沈砚睁开眼。他记得三年后的那一刀。\n<LOOM:EDIT-NOTE>\n- 删了。\n</LOOM:EDIT-NOTE>"
    g = _by_name(grade_editor(edited, _DRAFT_FIX, ["矿灯"]), "编辑·必含要素保持")
    assert g.passed is False
    assert any("矿灯" in e and "改丢" in e for e in g.evidence)


def test_editor_does_not_blame_editor_for_what_draft_never_had():
    """初稿本来就没有的必含项,不算编辑改丢的——归因必须指对棒。"""
    g = _by_name(grade_editor(_EDITED_OK, _DRAFT_FIX, ["师姐"]), "编辑·必含要素保持")
    assert g.passed is True


def test_editor_flags_expansion():
    edited = ("字" * 2000) + "\n<LOOM:EDIT-NOTE>\n- 扩写了。\n</LOOM:EDIT-NOTE>"
    g = _by_name(grade_editor(edited, "字" * 500, []), "编辑·篇幅变化")
    assert g.passed is False


def test_editor_note_body_excluded_from_length():
    """留痕不是正文:算篇幅必须先剥围栏,否则留痕越长越显得「扩写」。"""
    long_note = "\n<LOOM:EDIT-NOTE>\n" + ("留痕。" * 300) + "\n</LOOM:EDIT-NOTE>"
    g = _by_name(grade_editor(_DRAFT_FIX + long_note, _DRAFT_FIX, []), "编辑·篇幅变化")
    assert g.passed is True


def test_editor_skipped_when_upstream_missing():
    assert all(g.gating is False for g in grade_editor(None, _DRAFT_FIX, []))
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_stepgraders.py -k "outliner or editor" -v
```

Expected: `ImportError: cannot import name 'grade_editor' from 'evals.stepgraders'`。

- [ ] **Step 3: 实现**

`evals/stepgraders.py`，把顶部的 evalapi import 扩成：

```python
from loom.evalapi import (
    STEP_SHORT_BUDGETS,
    detect_aitell,
    parse_scene_budgets,
    scene_range,
    split_edit_note,
)
```

把 Task 6 留下的占位注释（`# 大纲师 / 编辑 的体检项在 Task 7 加…`）替换为 `grade_outliner`，并在 `grade_writer` 之后插入 `grade_editor`：

```python
# ─────────────────────────────── 大纲师 ───────────────────────────────

def grade_outliner(outline: str | None, chapter_target: int,
                   must_include: list[str]) -> list[GraderResult]:
    """大纲师产出「本章场景骨头(分镜细纲)」。

    体检三项(全部复用产品自己的判据,不另立一套——重写必漂):
    - 必含要素:case 的 must_include 有没有在细纲这层就丢掉(丢在这里 = 写手根本没机会写)。
    - 场次数:落在 scene_range(chapter_target) 声明的区间内(evalapi 接缝,与喂 prompt
      的 _scene_budget 同源)。
    - 篇幅预算标注:每场标了「约X字」且各场合计与章目标偏差 ≤30%(与产品
      _check_scene_budget 的 0.3 阈值同口径)。
    """
    if outline is None:
        return [skipped("大纲师", "必含要素"), skipped("大纲师", "场次数"),
                skipped("大纲师", "篇幅预算")]

    must = must_include or []
    missing = [k for k in must if k not in outline]
    total = len(must)
    inc_score = 1.0 if total == 0 else max(0.0, 1.0 - len(missing) / total)
    inc = GraderResult("大纲师·必含要素", round(inc_score, 3), not missing, weight=0.30,
                       detail=f"必含 {total} 项,细纲缺 {len(missing)} 项",
                       evidence=[f"细纲里没有:「{m}」" for m in missing])

    budgets = parse_scene_budgets(outline)
    lo, hi = scene_range(chapter_target)
    n_scenes = len(budgets)
    in_range = lo <= n_scenes <= hi
    cnt = GraderResult("大纲师·场次数", 1.0 if in_range else 0.0, in_range, weight=0.20,
                       detail=f"{n_scenes} 场(目标 {chapter_target} 字 → 应 {lo}-{hi} 场)")

    total_budget = sum(budgets)
    if not budgets:
        bud = GraderResult("大纲师·篇幅预算", 0.0, False, weight=0.15,
                           detail="各场都没标「约X字」,写手篇幅无锚")
    else:
        drift = abs(total_budget - chapter_target)
        ok = chapter_target <= 0 or drift <= chapter_target * 0.3
        bud = GraderResult("大纲师·篇幅预算",
                           round(max(0.0, 1.0 - drift / max(1, chapter_target)), 3), ok,
                           weight=0.15,
                           detail=f"各场合计约 {total_budget} 字(章目标 {chapter_target},容差 30%)")
    return [inc, cnt, bud]


# ──────────────────────────────── 编辑 ────────────────────────────────

def grade_editor(edited: str | None, draft: str | None,
                 must_include: list[str]) -> list[GraderResult]:
    """编辑产出「本章改稿」+ 成对围栏的《本章改动留痕》。

    体检三项(全是 改稿 vs 初稿 的差分):
    - 留痕围栏:<LOOM:EDIT-NOTE> 与 </LOOM:EDIT-NOTE> 必须成对(未闭合会让留痕混进正文)。
    - 必含要素保持:**初稿有、改稿没了**才算编辑改丢的。初稿本来就缺的不赖它——
      归因必须指对棒,否则闭环会把作者引到错的地方。
    - 篇幅变化:编辑被明令「篇幅保持原稿量级、绝不扩写」,超出 ±30% 就是没守。
      算篇幅前先剥留痕围栏,否则留痕越长越显得「扩写」。
    """
    if edited is None or draft is None:
        return [skipped("编辑", "留痕围栏"), skipped("编辑", "必含要素保持"),
                skipped("编辑", "篇幅变化")]

    body, note = split_edit_note(edited)
    unclosed = "围栏未闭合" in note
    fence_ok = bool(note.strip()) and not unclosed
    fence = GraderResult("编辑·留痕围栏", 1.0 if fence_ok else 0.0, fence_ok, weight=0.15,
                         detail=("留痕围栏成对" if fence_ok
                                 else ("围栏未闭合" if unclosed else "没有《本章改动留痕》")))

    must = must_include or []
    dropped = [k for k in must if k in draft and k not in body]
    keep = GraderResult("编辑·必含要素保持",
                        round(1.0 if not must else max(0.0, 1.0 - len(dropped) / len(must)), 3),
                        not dropped, weight=0.35,
                        detail=f"初稿有而改稿没了的必含项:{len(dropped)} 个",
                        evidence=[f"编辑把「{k}」改丢了" for k in dropped])

    n_draft, n_edit = _chars(draft), _chars(body)
    ratio = n_edit / max(1, n_draft)
    size_ok = 0.7 <= ratio <= 1.3
    size = GraderResult("编辑·篇幅变化", round(min(1.0, 1.0 - abs(1.0 - ratio)), 3), size_ok,
                        weight=0.10,
                        detail=f"初稿 {n_draft} → 改稿 {n_edit} 字(×{ratio:.2f},应在 0.7~1.3)")
    return [fence, keep, size]
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_stepgraders.py -v
```

Expected: 全绿。特别注意 `test_editor_note_body_excluded_from_length` —— 它钉死「算篇幅前先 `split_edit_note`」；失败说明用了 `edited` 原文而不是 `body`。

- [ ] **Step 5: 跑一次确定性自证**

棒级体检项的定位是纯函数、可复现。用两个不同进程跑同一份输入，断言输出逐字相同（防 `set` 遍历这类隐蔽的不确定性 —— `continuity.py` 就栽在这上面）：

```bash
for i in 1 2 3; do
  python -c "
from evals.stepgraders import grade_editor, grade_outliner
import json
o = grade_outliner('场景一 · 甲 · 约80字\n场景二 · 乙 · 约70字', 200, ['甲','丙'])
e = grade_editor('正文A\n<LOOM:EDIT-NOTE>\n- x\n</LOOM:EDIT-NOTE>', '正文A矿灯', ['矿灯'])
print(json.dumps([g.as_dict() for g in o + e], ensure_ascii=False, sort_keys=True))
"
done | sort -u | wc -l
```

Expected: `1` —— 三个独立进程输出完全一致。若 >1，说明有 hash 随机化依赖，必须修掉。

- [ ] **Step 6: 全量回归**

```bash
python -m pytest tests/ -q && python -m evals.run_eval --gate; echo "gate exit=$?"
```

Expected: 全绿；`gate exit=0`。

- [ ] **Step 7: Commit**

```bash
git add tests/test_eval_stepgraders.py evals/stepgraders.py
git commit -m "$(cat <<'MSG'
test(eval): 大纲师/编辑 棒级体检项——含「别赖错棒」与围栏三态

大纲师复用产品 scene_range/parse_scene_budgets(接缝),不另立判据。
编辑侧钉死两条归因纪律:①初稿有而改稿没了才算编辑改丢的
②算篇幅先剥留痕围栏,否则留痕越长越显得扩写。
另加跨进程确定性自证(防 set 遍历这类隐蔽不确定性)。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 8: 把棒级体检接进 generate_one，产出 step_report.json

**Files:**
- Modify: `evals/generate.py`
- Test: `tests/test_eval_generate.py`

**Interfaces:**
- Consumes: `collect_steps`（Task 5）、`evals.stepgraders` 五个 `grade_*`（Task 6/7）
- Produces: `grade_steps(steps: dict[str, str | None], case: dict) -> dict` —— 返回 `{"steps": {role: [grader_dict, ...]}, "weakest": str | None}`；落 `run_dir/step_report.json`

**`weakest` 的定义**：在所有 `gating=True` 且 `passed=False` 的体检项里，按 `weight` 降序取第一条所属的棒；全过则为 `None`。这就是「该改哪一棒」的直接答案。

**`hardfact_terms` 从哪来**：`case.json` 的 `expect.must_not_include`（禁止项就是写错的等级/地名）**不适合**当设定师的必含专名。新增可选字段 `expect.hardfact_terms`；缺省时回退到 `expect.must_include`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`：

```python
def test_step_report_written_and_names_weakest_step(tmp_path):
    """闭环的交付物:step_report.json 要能直接回答「该改哪一棒」。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path, with_outline=False)
    # 写手交的初稿里没有 must_include 的「矿灯」→ 写手·必含要素 应当失败并被点名
    draft_no_lamp = "寅时三刻，铜锣未响。\n\n沈砚睁开眼。\n\n他记得三年后的那一刀。"
    edited = draft_no_lamp + "\n" + EDIT_NOTE_OPEN + "\n- 钩子更硬。\n" + EDIT_NOTE_CLOSE
    be = ScriptedBackend([_SETTER, _OUTLINE, draft_no_lamp, edited,
                          "通过", draft_no_lamp, "通过", "标题"])
    run_dir = generate_one(case_dir, backend=be,
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    rep = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
    assert set(rep["steps"]) == {"设定师", "大纲师", "写手", "编辑", "润色师"}
    names = [g["name"] for g in rep["steps"]["写手"]]
    assert "写手·必含要素" in names
    failed = [g for g in rep["steps"]["写手"] if g["name"] == "写手·必含要素"][0]
    assert failed["passed"] is False
    assert rep["weakest"] in ("写手", "大纲师"), f"该点名丢要素的那一棒,实际 {rep['weakest']}"


def test_step_report_marks_bypassed_outliner_skipped_not_failed(tmp_path):
    """大纲师被 WYSIWYG 旁路时不得被点名成最弱棒——旁路不是失败。"""
    from evals.generate import generate_one
    case_dir = _write_gen_case(tmp_path)                 # with_outline=True → 旁路
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    rep = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
    assert all(g["gating"] is False for g in rep["steps"]["大纲师"])
    assert rep["weakest"] != "大纲师"
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py -k step_report -v
```

Expected: FAIL —— `step_report.json` 不存在。

- [ ] **Step 3: 实现**

`evals/generate.py`，加 import：

```python
from .stepgraders import (
    grade_editor,
    grade_outliner,
    grade_polisher,
    grade_setter,
    grade_writer,
)
```

在 `collect_steps` 之后插入：

```python
def grade_steps(steps: dict[str, str | None], case: dict) -> dict:
    """给五棒的中间产物各跑一组确定性体检,并点名最弱的一棒。

    weakest = 所有 gating 且未通过的体检项里 weight 最大的那条所属的棒——
    这就是「该改哪一棒的 prompt」的直接答案。全过则 None。
    skipped 项 gating=False,永远不会让一棒被点名(旁路不是失败)。
    """
    exp = case.get("expect", {}) or {}
    must = exp.get("must_include") or []
    # 设定师看的是「硬设定专名有没有进锚点」。禁止项(写错的等级/地名)不适合当必含,
    # 故用独立可选字段;缺省回退 must_include。
    hardfact_terms = exp.get("hardfact_terms") or must
    anchors = case.get("fingerprint_anchors", []) or []
    target = case.get("chapter_chars", 800)

    per_step = {
        "设定师": grade_setter(steps.get("设定师"), hardfact_terms),
        "大纲师": grade_outliner(steps.get("大纲师"), target, must),
        "写手": grade_writer(steps.get("写手"), target, must, anchors),
        "编辑": grade_editor(steps.get("编辑"), steps.get("写手"), must),
        "润色师": grade_polisher(steps.get("润色师"), steps.get("编辑"), anchors),
    }

    worst_weight, weakest = -1.0, None
    for role, results in per_step.items():
        for g in results:
            if g.gating and not g.passed and g.weight > worst_weight:
                worst_weight, weakest = g.weight, role

    return {"steps": {r: [g.as_dict() for g in gs] for r, gs in per_step.items()},
            "weakest": weakest}
```

在 `generate_one` 里，把 Task 5 加的那一行扩成：

```python
    steps = collect_steps(project, case["chapter_n"], run_dir)
    step_report = grade_steps(steps, case)
    (run_dir / "step_report.json").write_text(
        json.dumps(step_report, ensure_ascii=False, indent=2), encoding="utf-8")
```

顺带让 CLI 打出最弱棒。把 `main` 里的 print 行改成：

```python
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        sr = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
        flag = "✅" if report["passed"] else "❌"
        weak = f"  最弱棒={sr['weakest']}" if sr.get("weakest") else ""
        print(f"{flag} {report['case_id']}  score={report['score']}{weak}  → {run_dir}")
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_generate.py -v && python -m pytest tests/ -q
```

Expected: 全绿。

- [ ] **Step 5: 离线冒烟看一眼真实产物**

```bash
LOOM_DEMO=1 python -m evals.generate --case gen_01_mine_rebirth
```

Expected: 打印一行含 `最弱棒=`（demo 罐头文本几乎必然有棒不达标）。然后：

```bash
python -c "
import json, pathlib
d = sorted(pathlib.Path('evals/runs').iterdir())[-1]
r = json.loads((d / 'step_report.json').read_text(encoding='utf-8'))
print('最弱棒:', r['weakest'])
for role, gs in r['steps'].items():
    for g in gs:
        mark = '·' if not g['gating'] else ('✓' if g['passed'] else '✗')
        print(f\"  {mark} {g['name']:<20} {g['detail']}\")
"
```

Expected: 逐棒逐项可读；大纲师那几项显示 `·`（skipped，因 gen_01 的 overlay 旁路了它）。

- [ ] **Step 6: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): step_report.json——闭环第一次能直接回答「该改哪一棒」

grade_steps 给五棒中间产物各跑一组确定性体检,并按 weight 点名最弱棒。
skipped 项 gating=False,旁路的棒永远不会被误点名。
CLI 顺带打印「最弱棒=X」。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 9: 新增 gen_02 —— 让大纲师真跑

**Files:**
- Create: `evals/gen_cases/gen_02_mine_escape/case.json`
- Test: `tests/test_eval_generate.py`

**Interfaces:**
- Consumes: 无
- Produces: 一个**不带 overlay 细纲**的 gen case，使 `run_pipeline` 走满 8 调（设定/大纲/写手/编辑/质检/润色/去AI味/标题）

**Why:** `gen_01` 的 `overlay/正文/.细纲/第1章.md` 让细纲文件先存在，大纲师走 WYSIWYG 旁路不调模型（实测 `n_calls=7`）。**不加这个 case，大纲师这一棒永远评不到。**

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`：

```python
def test_gen_02_exists_and_has_no_outline_overlay():
    """gen_02 存在的唯一理由就是让大纲师真跑——它一旦带了 overlay 细纲就白设了。"""
    from evals.generate import GEN_CASES_DIR, load_gen_case
    d = GEN_CASES_DIR / "gen_02_mine_escape"
    assert (d / "case.json").is_file(), "缺 gen_02:大纲师这一棒没有任何 case 覆盖"
    case = load_gen_case(d)
    assert case["id"] == "gen_02_mine_escape"
    assert not (d / "overlay" / "正文" / ".细纲").exists(), \
        "gen_02 不得带 overlay 细纲,否则大纲师又被 WYSIWYG 旁路"
    assert case["expect"]["must_include"], "得有必含要素,否则大纲师的必含体检没内容可查"
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py::test_gen_02_exists_and_has_no_outline_overlay -v
```

Expected: FAIL with `缺 gen_02`。

- [ ] **Step 3: 建 case**

Create `evals/gen_cases/gen_02_mine_escape/case.json`：

```json
{
  "id": "gen_02_mine_escape",
  "title": "废矿逃生·首章(生成型·大纲师真跑)",
  "chapter_n": 1,
  "chapter_chars": 2000,
  "expect": {
    "must_include": ["沈砚", "矿"],
    "hardfact_terms": ["逆息"],
    "must_not_include": ["二中", "一阶0级"],
    "max_aitell_hits": 0,
    "len_tolerance": 0.6
  },
  "note": "与 gen_01 的唯一结构差异:【不带 overlay 细纲】,所以大纲师不走 WYSIWYG 旁路、真调模型(8 调而非 7 调)。gen_01 覆盖不到大纲师这一棒,这个 case 就是为它存在的。chapter_chars=2000 落在 scene_range 的 (3,4) 档,便于检验大纲师有没有按字数预算拆场。hardfact_terms 单列「逆息」:设定师的锚点里必须带上这个硬设定专名,丢了下游就只能靠 hardfacts 直送兜底。"
}
```

**注意**：这个目录下**不建** `overlay/`。scaffold 模板缺省值就是它的固定输入 —— 与 `gen_01` 一样是确定性输入，不是随机生成。

- [ ] **Step 4: 跑测试确认绿 + 离线冒烟**

```bash
python -m pytest tests/test_eval_generate.py -v
LOOM_DEMO=1 python -m evals.generate --case gen_02_mine_escape
```

Expected: 测试全绿；冒烟打印一行 `❌/✅ gen_02_mine_escape … 最弱棒=…`。然后确认大纲师**不再是 skipped**：

```bash
python -c "
import json, pathlib
d = sorted(p for p in pathlib.Path('evals/runs').iterdir() if 'gen_02' in p.name)[-1]
s = json.loads((d / 'steps.json').read_text(encoding='utf-8'))
print('steps.json:', s)
assert s['大纲师'] == 'collected', '大纲师仍被旁路,gen_02 白设了'
print('✓ 大纲师真跑了')
"
```

Expected: `✓ 大纲师真跑了`。

- [ ] **Step 5: Commit**

```bash
git add evals/gen_cases/gen_02_mine_escape/case.json tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): 加 gen_02——不带 overlay 细纲,让大纲师这一棒真跑

gen_01 的 overlay 细纲让大纲师走 WYSIWYG 旁路(实测 n_calls=7,没有大纲师),
所以五棒里它永远评不到。gen_02 唯一的结构差异就是不带细纲(8 调)。
chapter_chars=2000 落在 scene_range 的 (3,4) 档,便于检验按预算拆场。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 10: aggregate.py —— N 次运行取分布

**Files:**
- Create: `evals/aggregate.py`
- Test: `tests/test_eval_aggregate.py`

**Interfaces:**
- Consumes: 无（纯函数，吃 dict）
- Produces:
  - `Distribution` dataclass —— `median: float | None`、`lo: float | None`、`hi: float | None`、`n_valid: int`、`n_total: int`
  - `distribution(values: list[float | None]) -> Distribution`
  - `aggregate_runs(step_reports: list[dict | None]) -> dict` —— `{"n_total", "n_valid", "steps": {role: {item: Distribution-as-dict}}, "weakest": str | None}`
  - `overlaps(a: dict, b: dict) -> bool` —— 两个 Distribution-as-dict 的区间是否重叠

**Why:** temp=0.9 无 seed，单次分数差一律不作结论。区间重叠 = **不宣称有改进**。

**不造数纪律**：`n_valid < n_total` 时照实记两个数；`n_valid == 0` 时 `median/lo/hi` 全为 `None`（不是 0.0）。

- [ ] **Step 1: 写失败测试**

Create `tests/test_eval_aggregate.py`：

```python
"""N 次运行 → 分布。temp=0.9 无 seed,单次分数差一律不作结论。

红线:不造数——N 次里 M 次 infra 就照实记两个数,绝不用 M 次均值冒充 N 次。
"""
import pytest

from evals.aggregate import Distribution, aggregate_runs, distribution, overlaps


# ── distribution ───────────────────────────────────────────────────────────
def test_distribution_odd_count():
    d = distribution([0.2, 0.8, 0.5])
    assert d.median == 0.5 and d.lo == 0.2 and d.hi == 0.8
    assert d.n_valid == 3 and d.n_total == 3


def test_distribution_even_count_averages_middle_two():
    d = distribution([0.2, 0.4, 0.6, 0.8])
    assert d.median == pytest.approx(0.5)


def test_distribution_drops_none_and_reports_both_counts():
    """5 次里 2 次 infra:必须照实记 n_valid=3 / n_total=5,不得拿 3 次冒充 5 次。"""
    d = distribution([0.4, None, 0.6, None, 0.5])
    assert d.n_valid == 3 and d.n_total == 5
    assert d.median == 0.5


def test_distribution_all_infra_is_none_not_zero():
    d = distribution([None, None])
    assert d.median is None and d.lo is None and d.hi is None
    assert d.n_valid == 0 and d.n_total == 2


def test_distribution_empty():
    d = distribution([])
    assert d.n_valid == 0 and d.n_total == 0 and d.median is None


# ── overlaps ───────────────────────────────────────────────────────────────
def _dist(lo, hi):
    return {"lo": lo, "hi": hi, "median": (lo + hi) / 2, "n_valid": 3, "n_total": 3}


def test_overlaps_true_when_ranges_touch():
    assert overlaps(_dist(0.4, 0.7), _dist(0.6, 0.9)) is True


def test_overlaps_false_when_separated():
    assert overlaps(_dist(0.1, 0.3), _dist(0.6, 0.9)) is False


def test_overlaps_true_when_either_side_unmeasured():
    """一边没有有效数据 → 不能宣称分开,保守判重叠(不造结论)。"""
    assert overlaps(_dist(0.1, 0.3), {"lo": None, "hi": None,
                                      "median": None, "n_valid": 0, "n_total": 3}) is True


# ── aggregate_runs ─────────────────────────────────────────────────────────
def _report(setter_score, writer_score, *, writer_passed=True):
    return {
        "steps": {
            "设定师": [{"name": "设定师·硬设定专名", "score": setter_score, "passed": True,
                      "weight": 0.3, "gating": True, "detail": "", "evidence": []}],
            "写手": [{"name": "写手·必含要素", "score": writer_score, "passed": writer_passed,
                    "weight": 0.3, "gating": True, "detail": "", "evidence": []}],
        },
        "weakest": None if writer_passed else "写手",
    }


def test_aggregate_runs_builds_per_item_distributions():
    agg = aggregate_runs([_report(1.0, 0.5), _report(1.0, 0.7), _report(1.0, 0.6)])
    assert agg["n_total"] == 3 and agg["n_valid"] == 3
    w = agg["steps"]["写手"]["写手·必含要素"]
    assert w["median"] == 0.6 and w["lo"] == 0.5 and w["hi"] == 0.7


def test_aggregate_runs_counts_infra_runs_honestly():
    agg = aggregate_runs([_report(1.0, 0.5), None, _report(1.0, 0.7)])
    assert agg["n_total"] == 3 and agg["n_valid"] == 2
    assert agg["steps"]["写手"]["写手·必含要素"]["n_valid"] == 2


def test_aggregate_runs_all_infra_returns_no_numbers():
    agg = aggregate_runs([None, None])
    assert agg["n_valid"] == 0 and agg["steps"] == {} and agg["weakest"] is None


def test_aggregate_runs_weakest_is_majority_vote():
    """最弱棒按多数决,不被单次波动带偏。"""
    agg = aggregate_runs([_report(1.0, 0.2, writer_passed=False),
                          _report(1.0, 0.3, writer_passed=False),
                          _report(1.0, 0.9)])
    assert agg["weakest"] == "写手"


def test_aggregate_runs_no_weakest_when_mostly_clean():
    agg = aggregate_runs([_report(1.0, 0.9), _report(1.0, 0.9),
                          _report(1.0, 0.2, writer_passed=False)])
    assert agg["weakest"] is None
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_aggregate.py -v
```

Expected: `ModuleNotFoundError: No module named 'evals.aggregate'`。

- [ ] **Step 3: 实现**

Create `evals/aggregate.py`：

```python
"""N 次运行 → 分布。

为什么需要它:生成链路没有 seed 通道,OpenAICompatBackend.complete 写死
temperature=0.9(loom/backends.py:280,311),同一 case 跑两次不保证字符级甚至
语义级一致。所以「这次 prompt 改动到底有没有让生成变好」必须看**多次运行的
分数分布**,而不是拿单次结果定生死——evals/README.md 早就写下了这条方法论,
本模块把它从文档声明变成工具行为。

红线(不造数):N 次里 M 次 infra,就照实记 n_valid=M / n_total=N,
**绝不用 M 次的均值冒充 N 次**。全 infra 时各项统计量为 None,不是 0.0。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Distribution:
    median: float | None
    lo: float | None
    hi: float | None
    n_valid: int
    n_total: int

    def as_dict(self) -> dict:
        return asdict(self)


def distribution(values: list[float | None]) -> Distribution:
    """一串分数(None=该次 infra)→ 中位数 + 区间 + 有效/总次数。"""
    n_total = len(values)
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return Distribution(None, None, None, 0, n_total)
    mid = len(xs) // 2
    med = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    return Distribution(round(med, 4), xs[0], xs[-1], len(xs), n_total)


def overlaps(a: dict, b: dict) -> bool:
    """两个分布的区间是否重叠。重叠 = **不得宣称有改进**。

    任一边没有有效数据 → 保守判重叠:没数据不等于「分开了」,不造结论。
    """
    if not a or not b or a.get("lo") is None or b.get("lo") is None:
        return True
    return a["lo"] <= b["hi"] and b["lo"] <= a["hi"]


def aggregate_runs(step_reports: list[dict | None]) -> dict:
    """N 份 step_report(None=该次 run 整体 infra)→ 逐棒逐项的分布 + 最弱棒。

    weakest 用**多数决**:超过半数的有效 run 都点了同一棒,才认它——
    单次波动不该把归因带偏。
    """
    n_total = len(step_reports)
    valid = [r for r in step_reports if r]
    if not valid:
        return {"n_total": n_total, "n_valid": 0, "steps": {}, "weakest": None}

    # item_scores[role][item_name] = [score or None, ...],长度恒为 n_total
    item_scores: dict[str, dict[str, list[float | None]]] = defaultdict(lambda: defaultdict(list))
    for rep in step_reports:
        steps = (rep or {}).get("steps", {})
        for role, graders in steps.items():
            for g in graders:
                # skipped 项不进分布:旁路不是失败,记 0 会把中位数拉垮
                score = None if not g.get("gating", True) else g.get("score")
                item_scores[role][g["name"]].append(score)
        # 本次 run 整体 infra:给所有已知项补一个 None,保证长度对齐 n_total
        if not rep:
            for role, items in item_scores.items():
                for name in items:
                    items[name].append(None)

    steps_out = {
        role: {name: distribution(vals).as_dict() for name, vals in items.items()}
        for role, items in item_scores.items()
    }

    votes = Counter(r["weakest"] for r in valid if r.get("weakest"))
    weakest = None
    if votes:
        top, cnt = votes.most_common(1)[0]
        if cnt * 2 > len(valid):     # 严格多数
            weakest = top

    return {"n_total": n_total, "n_valid": len(valid),
            "steps": steps_out, "weakest": weakest}
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_aggregate.py -v && python -m pytest tests/ -q
```

Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add evals/aggregate.py tests/test_eval_aggregate.py
git commit -m "$(cat <<'MSG'
feat(eval): aggregate——N 次运行取分布,把「看分布不看单次」变成工具行为

temp=0.9 写死、无 seed,单次分数差不作结论。中位数+区间+有效次数;
区间重叠即不得宣称改进。最弱棒按严格多数决,不被单次波动带偏。
不造数:N 次里 M 次 infra 照实记两个数,全 infra 时统计量为 None 不是 0。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 11: `--repeat N` + batch 落盘 + summary.md

**Files:**
- Modify: `evals/generate.py`
- Test: `tests/test_eval_generate.py`

**Interfaces:**
- Consumes: `aggregate_runs`（Task 10）
- Produces:
  - `run_batch(case_dir, *, repeat, runs_dir, **kw) -> Path` —— 返回 batch 目录
  - batch 目录结构：`evals/runs/<batch_id>/{runs/<run_id>/…, summary.json, summary.md}`
  - CLI：`--repeat N`（默认 1）

**Why:** 闭环要的是分布，不是单次。单次 run 崩了记 infra 继续跑，不能因为第 3 次挂了就丢掉前 2 次。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`：

```python
def test_run_batch_produces_summary_with_distributions(tmp_path):
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    batch = run_batch(case_dir, repeat=3, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: ScriptedBackend(list(_GEN_RUN_7)),
                      workdir_root=tmp_path / "work")
    assert (batch / "summary.json").is_file() and (batch / "summary.md").is_file()
    assert len(list((batch / "runs").iterdir())) == 3
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_total"] == 3 and summ["n_valid"] == 3
    assert summ["case_id"] == "gen_test"
    w = summ["steps"]["写手"]["写手·必含要素"]
    assert w["median"] is not None and w["n_valid"] == 3


def test_run_batch_survives_a_crashed_run_and_reports_honestly(tmp_path):
    """第 2 次崩了不能丢掉第 1、3 次;而且必须照实写 3 次里 2 次有效。"""
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    seq = iter([ScriptedBackend(list(_GEN_RUN_7)),
                ScriptedBackend([]),                    # 空脚本 → 空响应 → 写盘闸抛错
                ScriptedBackend(list(_GEN_RUN_7))])
    batch = run_batch(case_dir, repeat=3, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: next(seq),
                      workdir_root=tmp_path / "work")
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_total"] == 3 and summ["n_valid"] == 2
    md = (batch / "summary.md").read_text(encoding="utf-8")
    assert "3 次里 2 次有效" in md, "必须照实披露掉数,不得拿 2 次冒充 3 次"


def test_run_batch_all_runs_crashed_is_infra(tmp_path):
    from evals.generate import run_batch
    case_dir = _write_gen_case(tmp_path)
    batch = run_batch(case_dir, repeat=2, runs_dir=tmp_path / "runs",
                      backend_factory=lambda: ScriptedBackend([]),
                      workdir_root=tmp_path / "work")
    summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summ["n_valid"] == 0 and summ["steps"] == {}


def test_cli_repeat_flag_returns_2_when_all_infra(tmp_path, monkeypatch):
    """全 infra → 退出码 2(沿用三态),不得当成质量结论。"""
    monkeypatch.setenv("LOOM_DEMO", "1")
    from evals.generate import main
    src = _write_gen_case(tmp_path)
    gc = tmp_path / "gc"; gc.mkdir()
    shutil.copytree(src, gc / "gen_test")
    # chapter_chars 设成天文数字,DemoBackend 罐头文本必然过不了终稿最短闸 → 每次都崩
    case_path = gc / "gen_test" / "case.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["chapter_chars"] = 900000
    case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    code = main(["--cases-dir", str(gc), "--runs-dir", str(tmp_path / "runs"), "--repeat", "2"])
    assert code == 2
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py -k "run_batch or repeat_flag" -v
```

Expected: `ImportError: cannot import name 'run_batch'`。

- [ ] **Step 3: 实现**

`evals/generate.py`，加 import：

```python
from .aggregate import aggregate_runs
```

先给 `generate_one` 加一个 `backend_factory` 友好的入口 —— 实际上直接在 `run_batch` 里调 `generate_one` 即可。在 `main` 之前插入：

```python
def _summary_md(case_id: str, agg: dict, batch_id: str) -> str:
    """人看的批次小结。禁止只报中位数:掉数与区间必须同屏可见。"""
    lines = [f"# 棒级归因批次小结 · {case_id}", "",
             f"- 批次:`{batch_id}`",
             f"- 运行:**{agg['n_total']} 次里 {agg['n_valid']} 次有效**"
             + ("" if agg["n_valid"] == agg["n_total"] else "(其余为 infra,未计入分布)"),
             f"- 最弱棒:**{agg['weakest'] or '(无——所有 gating 项都过了,或无严格多数)'}**", ""]
    if agg["n_valid"] == 0:
        lines += ["> 全部运行都 infra,没有任何可读的分数。**这不是质量结论。**", ""]
        return "\n".join(lines)
    lines += ["| 棒 | 体检项 | 中位数 | 区间 | 有效/总 |", "|---|---|---|---|---|"]
    for role, items in agg["steps"].items():
        for name, d in items.items():
            if d["n_valid"] == 0:
                lines.append(f"| {role} | {name} | — | — | 0/{d['n_total']}(全 skipped 或全 infra) |")
            else:
                lines.append(f"| {role} | {name} | {d['median']} | "
                             f"{d['lo']}~{d['hi']} | {d['n_valid']}/{d['n_total']} |")
    lines += ["", "> 判据纪律:两批比对时**区间重叠即不得宣称有改进**。",
              "> 生成链路无 seed、temperature=0.9 写死,单次分数差一律不作结论。"]
    return "\n".join(lines)


def run_batch(case_dir: Path, *, repeat: int = 1, runs_dir: Path | None = None,
              backend_factory=None, workdir_root: Path | None = None,
              backend_mode: str = "demo", provider: str | None = None,
              model: str | None = None) -> Path:
    """同一个 case 连跑 repeat 次,聚合成分布落 batch 目录。

    单次崩了记 infra 继续跑——不能因为第 3 次挂了就丢掉前 2 次。
    全崩则 summary 里 n_valid=0,由 CLI 翻成退出码 2(infra,不是质量结论)。
    """
    case = load_gen_case(case_dir)
    runs_dir = runs_dir or RUNS_DIR
    batch_id = f"{time.strftime('%Y%m%d-%H%M%S')}_batch_{case['id']}_x{repeat}"
    batch = runs_dir / batch_id
    (batch / "runs").mkdir(parents=True)

    reports: list[dict | None] = []
    for i in range(repeat):
        wd = (workdir_root / f"w{i}") if workdir_root else None
        if wd:
            wd.mkdir(parents=True, exist_ok=True)
        try:
            run_dir = generate_one(
                case_dir,
                backend=backend_factory() if backend_factory else None,
                backend_mode=backend_mode, provider=provider, model=model,
                runs_dir=batch / "runs", workdir=wd)
            reports.append(json.loads(
                (run_dir / "step_report.json").read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001 — 单次崩=infra,记下继续,绝不中断整批
            (batch / "runs" / f"infra_{i}.txt").write_text(
                f"第 {i + 1} 次运行 infra:{type(e).__name__} — {e}\n", encoding="utf-8")
            reports.append(None)

    agg = aggregate_runs(reports)
    agg["case_id"] = case["id"]
    agg["batch_id"] = batch_id
    (batch / "summary.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    (batch / "summary.md").write_text(
        _summary_md(case["id"], agg, batch_id), encoding="utf-8")
    return batch
```

再改 `main`：给 parser 加 `--repeat`，并把跑 case 的循环改成走 `run_batch`：

```python
    ap.add_argument("--repeat", type=int, default=1,
                    help="同一 case 连跑 N 次取分布(对抗 temp=0.9 无 seed 的噪声;N≥2 才有分布)")
```

把 `for d in case_dirs:` 那段整体替换为：

```python
    any_valid = False
    for d in case_dirs:
        if args.repeat > 1:
            batch = run_batch(d, repeat=args.repeat, runs_dir=args.runs_dir,
                              backend_mode=args.backend, provider=args.provider,
                              model=args.model)
            summ = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
            any_valid = any_valid or summ["n_valid"] > 0
            weak = summ["weakest"] or "(无)"
            print(f"{'✅' if summ['n_valid'] else '✗'} {summ['case_id']}  "
                  f"{summ['n_total']} 次里 {summ['n_valid']} 次有效  最弱棒={weak}  → {batch}")
        else:
            run_dir = generate_one(d, backend_mode=args.backend, provider=args.provider,
                                   model=args.model, runs_dir=args.runs_dir)
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            sr = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
            any_valid = True
            flag = "✅" if report["passed"] else "❌"
            weak = f"  最弱棒={sr['weakest']}" if sr.get("weakest") else ""
            print(f"{flag} {report['case_id']}  score={report['score']}{weak}  → {run_dir}")
    if not any_valid:
        print("✗ 所有运行都 infra,没有任何可读的分数——这不是质量结论。")
        return 2
    return 0
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_generate.py -v && python -m pytest tests/ -q
```

Expected: 全绿。

- [ ] **Step 5: 离线冒烟看 summary.md**

```bash
LOOM_DEMO=1 python -m evals.generate --case gen_02_mine_escape --repeat 3
python -c "
import pathlib
d = sorted(p for p in pathlib.Path('evals/runs').iterdir() if 'batch' in p.name)[-1]
print((d / 'summary.md').read_text(encoding='utf-8'))
"
```

Expected: 表格逐棒逐项列出中位数/区间/有效次数，且底部有「区间重叠即不得宣称有改进」的纪律行。

- [ ] **Step 6: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): --repeat N 批次运行 + summary.md 分布小结

单次崩记 infra 继续跑,不因第 3 次挂掉丢掉前 2 次;summary 照实写
「N 次里 M 次有效」,绝不拿 M 次冒充 N 次。全 infra → 退出码 2。
小结禁止只报中位数,掉数与区间同屏可见。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 12: `--compare` 两批比对

**Files:**
- Modify: `evals/generate.py`
- Test: `tests/test_eval_generate.py`

**Interfaces:**
- Consumes: `overlaps`（Task 10）
- Produces: `compare_batches(a: Path, b: Path) -> dict` —— `{"case_id", "items": [{"step","item","before","after","delta","verdict"}], "n_improved", "n_regressed"}`；`verdict ∈ {"改进","回归","分不出(区间重叠)","无数据"}`；CLI `--compare <batch_a> <batch_b>`

**Why:** 闭环的最后一环 —— 改完 prompt 要能回答「到底有没有变好」。**区间重叠即判「分不出」，不宣称改进。**

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`：

```python
def _fake_batch(tmp_path, name, *, median, lo, hi, n_valid=3):
    b = tmp_path / name
    b.mkdir(parents=True)
    (b / "summary.json").write_text(json.dumps({
        "case_id": "gen_test", "batch_id": name, "n_total": 3, "n_valid": n_valid,
        "weakest": None,
        "steps": {"写手": {"写手·必含要素": {"median": median, "lo": lo, "hi": hi,
                                          "n_valid": n_valid, "n_total": 3}}},
    }, ensure_ascii=False), encoding="utf-8")
    return b


def test_compare_declares_improvement_only_when_ranges_separate(tmp_path):
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.2, lo=0.1, hi=0.3)
    b = _fake_batch(tmp_path, "b", median=0.8, lo=0.7, hi=0.9)
    res = compare_batches(a, b)
    item = res["items"][0]
    assert item["verdict"] == "改进" and item["delta"] == pytest.approx(0.6)
    assert res["n_improved"] == 1 and res["n_regressed"] == 0


def test_compare_refuses_to_call_it_improvement_when_ranges_overlap(tmp_path):
    """中位数涨了但区间重叠 —— 必须判「分不出」,这是本工具最重要的一条纪律。"""
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.50, lo=0.30, hi=0.70)
    b = _fake_batch(tmp_path, "b", median=0.62, lo=0.40, hi=0.85)
    item = compare_batches(a, b)["items"][0]
    assert item["verdict"] == "分不出(区间重叠)"
    assert compare_batches(a, b)["n_improved"] == 0


def test_compare_flags_regression_when_ranges_separate_downward(tmp_path):
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.9, lo=0.85, hi=0.95)
    b = _fake_batch(tmp_path, "b", median=0.3, lo=0.2, hi=0.4)
    res = compare_batches(a, b)
    assert res["items"][0]["verdict"] == "回归" and res["n_regressed"] == 1


def test_compare_says_no_data_when_a_side_is_all_infra(tmp_path):
    from evals.generate import compare_batches
    a = _fake_batch(tmp_path, "a", median=0.5, lo=0.4, hi=0.6)
    b = _fake_batch(tmp_path, "b", median=None, lo=None, hi=None, n_valid=0)
    assert compare_batches(a, b)["items"][0]["verdict"] == "无数据"


def test_cli_compare_requires_two_batches(tmp_path):
    from evals.generate import main
    assert main(["--compare", str(tmp_path / "nope")]) == 2
```

在 `tests/test_eval_generate.py` 顶部确认已 `import pytest`（已有）。

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py -k compare -v
```

Expected: `ImportError: cannot import name 'compare_batches'`。

- [ ] **Step 3: 实现**

`evals/generate.py`，把 import 改成 `from .aggregate import aggregate_runs, overlaps`，在 `run_batch` 之后插入：

```python
def compare_batches(batch_a: Path, batch_b: Path) -> dict:
    """两批对比:a=改动前,b=改动后。

    **最重要的一条纪律:区间重叠就判「分不出」,不宣称改进。**
    生成链路 temperature=0.9 写死、无 seed,中位数涨了一点很可能只是这次运气好。
    """
    sa = json.loads((batch_a / "summary.json").read_text(encoding="utf-8"))
    sb = json.loads((batch_b / "summary.json").read_text(encoding="utf-8"))

    items, improved, regressed = [], 0, 0
    for role, a_items in sa.get("steps", {}).items():
        for name, da in a_items.items():
            db = sb.get("steps", {}).get(role, {}).get(name)
            if not db or da.get("median") is None or db.get("median") is None:
                verdict, delta = "无数据", None
            elif overlaps(da, db):
                verdict = "分不出(区间重叠)"
                delta = round(db["median"] - da["median"], 4)
            else:
                delta = round(db["median"] - da["median"], 4)
                verdict = "改进" if delta > 0 else "回归"
                improved += verdict == "改进"
                regressed += verdict == "回归"
            items.append({"step": role, "item": name, "before": da, "after": db,
                          "delta": delta, "verdict": verdict})
    return {"case_id": sa.get("case_id"), "items": items,
            "n_improved": improved, "n_regressed": regressed}
```

在 `main` 的 parser 里加：

```python
    ap.add_argument("--compare", nargs="+", metavar="BATCH",
                    help="对比两个批次目录(改动前 改动后):区间重叠即判「分不出」,不宣称改进")
```

并在 `if not args.cases_dir.is_dir():` **之前**插入 compare 分支：

```python
    if args.compare:
        if len(args.compare) != 2:
            print("✗ --compare 需要恰好两个批次目录:<改动前> <改动后>")
            return 2
        a, b = Path(args.compare[0]), Path(args.compare[1])
        if not (a / "summary.json").is_file() or not (b / "summary.json").is_file():
            print(f"✗ 批次目录缺 summary.json:{a} / {b}")
            return 2
        res = compare_batches(a, b)
        print(f"── {res['case_id']}:{a.name} → {b.name} ──")
        for it in res["items"]:
            d = "—" if it["delta"] is None else f"{it['delta']:+.4f}"
            print(f"  {it['verdict']:<16} {it['step']}·{it['item']:<24} Δ中位数 {d}")
        print(f"\n改进 {res['n_improved']} 项 · 回归 {res['n_regressed']} 项 · "
              f"其余分不出(区间重叠或无数据)")
        return 1 if res["n_regressed"] else 0
```

- [ ] **Step 4: 跑测试确认绿**

```bash
python -m pytest tests/test_eval_generate.py -v && python -m pytest tests/ -q
```

Expected: 全绿。

- [ ] **Step 5: 离线端到端演一遍闭环**

```bash
LOOM_DEMO=1 python -m evals.generate --case gen_02_mine_escape --repeat 3
LOOM_DEMO=1 python -m evals.generate --case gen_02_mine_escape --repeat 3
B=$(ls -dt evals/runs/*batch_gen_02* | head -2 | tail -1)
A=$(ls -dt evals/runs/*batch_gen_02* | head -1)
python -m evals.generate --compare "$B" "$A"; echo "exit=$?"
```

Expected: 逐项打印判词。因为两批用的是同一个罐头后端，**绝大多数项应判「分不出(区间重叠)」** —— 这正是工具在正确工作：没变的东西不该被宣称成改进。

- [ ] **Step 6: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): --compare 两批比对——区间重叠即判「分不出」,不宣称改进

闭环最后一环:改完 prompt 能回答「到底有没有变好」。
中位数涨了但区间重叠一律判「分不出」——temp=0.9 无 seed,
单次或小样本的中位数抬升很可能只是运气。有回归则退出码 1。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 13: 修 continuity 四个 bug

**Files:**
- Modify: `loom/continuity.py`（`detect_char_continuity`）
- Test: `tests/test_continuity.py`

**Interfaces:**
- Consumes: 无
- Produces: `detect_char_continuity(book, chapter_n, body, char_names)` 行为修正（签名不变）

**Why（四条，逐一验证过）:**

| bug | 现状 | 后果 |
|---|---|---|
| `char_names` 是死参数 | 函数体从头到尾没引用它 | 账本里任何 `[状态]` 行左半段（哪怕「阵法」「城主府」）都进别名匹配 |
| `prior` 用泄漏的循环变量 `m` | `for m in reversed(sorted(...))` 结束后 `m` 是**最小**章号 | 「双证据」永远指向最早那章，作者翻过去核对不上 |
| `state_line not in body[:500]` 恒真 | `state_line` 是账本行（如「沈砚:重伤」），几乎不可能是正文前 500 字的子串 | 有闭关/重伤角色，之后每章只要露面就固定刷一条 3 星报告 |
| 单姓别名 + `set` 遍历 | `aliases.append(name[0])`；`for alias in set(...)` 后 `break` | 单汉字必然撞词（苏醒/苏州）；set 遍历受 hash 随机化影响，同稿两次除虫证据不同 |

**现有测试为什么全绿**：`tests/test_continuity.py` 的账本恰好把特殊状态放在**第 1 章**，掩盖了 `m` 泄漏。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_continuity.py`：

```python
def test_char_continuity_prior_points_at_the_right_chapter():
    """双证据的价值全在指对地方:prior 必须指状态实际所在那一章,不是最早那章。"""
    from loom.continuity import detect_char_continuity
    book = {
        1: [("状态", "沈砚:健全|第1章")],
        5: [("状态", "沈砚:重伤|第5章")],
    }
    body = "沈砚推开门，屋里空无一人。" * 30
    out = detect_char_continuity(book, 7, body, {"沈砚"})
    assert out, "第5章重伤、第7章出场未交代 → 应当报"
    assert "第5章" in out[0].prior, f"prior 指错章:{out[0].prior}"


def test_char_continuity_respects_char_names_whitelist():
    """char_names 是白名单:账本里的非人物行(阵法/城主府)不该触发人设报警。"""
    from loom.continuity import detect_char_continuity
    book = {2: [("状态", "护山大阵:封印|第2章")]}
    body = "护山大阵嗡鸣了一声。" * 30
    assert detect_char_continuity(book, 4, body, {"沈砚"}) == []


def test_char_continuity_does_not_fire_when_status_change_is_narrated():
    """全名出现且正文交代了状态变化 → 不该报。旧判据 `state_line not in body[:500]`
    实质恒真,让这条分支变成噪声源。"""
    from loom.continuity import detect_char_continuity
    book = {3: [("状态", "沈砚:重伤|第3章")]}
    body = "沈砚的伤已经好了大半，他推门进来。" + "此后诸事顺遂。" * 30
    assert detect_char_continuity(book, 5, body, {"沈砚"}) == []


def test_char_continuity_still_fires_when_status_ignored():
    from loom.continuity import detect_char_continuity
    book = {3: [("状态", "沈砚:重伤|第3章")]}
    body = "沈砚一跃三丈，长剑出鞘，快得没人看清。" * 20
    out = detect_char_continuity(book, 5, body, {"沈砚"})
    assert out and "第3章" in out[0].prior


def test_char_continuity_single_surname_is_not_an_alias():
    """单汉字姓在中文里必然撞词(苏醒/苏州/复苏),不能当别名。"""
    from loom.continuity import detect_char_continuity
    book = {2: [("状态", "苏昭:闭关|第2章")]}
    body = "他从昏迷中苏醒过来，望向苏州方向。" * 20   # 有「苏」但没有苏昭
    assert detect_char_continuity(book, 4, body, {"苏昭"}) == []


def test_char_continuity_alias_evidence_is_deterministic():
    """纯函数必须可复现:同一份输入多次调用,证据逐字相同(旧代码 set 遍历会飘)。"""
    from loom.continuity import detect_char_continuity
    book = {2: [("状态", "沈砚:闭关|第2章")]}
    body = "砚公子与砚兄一同现身，砚某也在。" * 20
    outs = [detect_char_continuity(book, 4, body, {"沈砚"}) for _ in range(20)]
    evidences = {tuple(b.evidence for b in o) for o in outs}
    assert len(evidences) == 1, f"证据不稳定:{evidences}"
```

- [ ] **Step 2: 跑测试确认它们红**

```bash
python -m pytest tests/test_continuity.py -v 2>&1 | tail -30
```

Expected: 上面 6 条里至少 5 条 FAIL（`prior` 指错章、白名单无效、恒真判据、单姓撞词）。`test_char_continuity_alias_evidence_is_deterministic` 在单进程内可能碰巧稳定 —— 它主要防的是跨进程漂移，Step 4 会另测。

- [ ] **Step 3: 实现**

`loom/continuity.py`，把 `detect_char_continuity` 整个替换为：

```python
def detect_char_continuity(book: dict[int, list[tuple[str, str]]], chapter_n: int, body: str,
                           char_names: set[str]) -> list[BugItem]:
    """人物出场关联检测:状态账本 [状态] 行人物在前情有特殊状态(重伤/闭关/失踪/禁足等)
    且本章提到该人物时未交代状态变化 → 标记。

    char_names 来自人物目录文件名,是**白名单**:账本里的非人物行(护山大阵/城主府)
    不该触发人设报警。白名单为空时不做人物过滤(老书没有人物目录时的兜底)。
    """
    _SPECIAL_STATES = re.compile(
        r"(?:^|[^无未不])(?:重伤|闭关|失踪|禁足|昏迷|囚禁|封印|被俘|失忆|流放|除名|镇守|被控)")
    # 状态解除/变化的交代词:正文里出现任意一个,就算作者已经交代过了,不再报
    _RESOLVED = ("痊愈", "伤愈", "好了", "康复", "出关", "解禁", "解封", "醒来", "苏醒",
                 "归来", "现身", "获释", "脱身", "恢复", "复原", "伤势", "伤口", "养伤")
    out: list[BugItem] = []
    # char -> (state_line, 该状态实际所在章号)。倒序遍历,只保留最近一次。
    last_state: dict[str, tuple[str, int]] = {}
    for ch in reversed(sorted(k for k in book if k < chapter_n)):
        for kind, content in book[ch]:
            if kind != "状态":
                continue
            change = content.split("|")[0].strip()
            name = re.split(r"[:：]", change, 1)[0].strip()
            if name and name not in last_state:
                last_state[name] = (change, ch)

    for name, (state_line, prior_ch) in sorted(last_state.items()):
        if char_names and name not in char_names:
            continue                      # 白名单:非人物行不报
        if not _SPECIAL_STATES.search(state_line):
            continue
        if any(w in body for w in _RESOLVED):
            continue                      # 正文交代了状态变化 → 不报

        if name in body:
            out.append(BugItem(
                3, "人设",
                f"「{name}」前情处于{state_line},本章出现但未交代状态变化",
                evidence=name[:60],
                prior=f"第{prior_ch}章账本:{state_line}",
                fix=f"在文中交代{name}当前状态"))
            continue

        # 全名不在正文 → 看别名/简称。**不含单姓**(单汉字必然撞词:苏醒/苏州/复苏)。
        aliases: list[str] = []
        if len(name) >= 2:
            aliases.append(name[1:])                       # 去姓
            if name[0] in "慕容南宫欧阳西门上官端木独孤诸葛":
                aliases.append(name[2:])                   # 复姓去姓
        if "·" in name:
            aliases.append(name.split("·")[-1])
        surname = name[0]
        aliases += [surname + suf for suf in ("姑娘", "公子", "前辈", "兄", "老", "某")]
        # 去重但**保序**:list(dict.fromkeys(...)) 而不是 set——set 遍历受 hash
        # 随机化影响,会让同一份稿子两次除虫报出不同证据,破坏「纯函数可复现」定位。
        for alias in list(dict.fromkeys(a for a in aliases if len(a) >= 2)):
            if alias not in body:
                continue
            out.append(BugItem(
                3, "人设",
                f"「{name}」前情处于特殊状态:{state_line},本章仅以别名/简称出现",
                evidence=alias,
                prior=f"第{prior_ch}章账本:{state_line}",
                fix="补足全称并交代状态变化"))
            break
    return out
```

**注意三处**：① `_SPECIAL_STATES` 去掉了重复的「昏迷」；② 别名最小长度从 `>= 1` 改成 `>= 2`，配合不再加单姓；③ 遍历 `last_state` 时 `sorted(...)` 让输出顺序也确定。

- [ ] **Step 4: 跑测试 + 跨进程确定性自证**

```bash
python -m pytest tests/test_continuity.py -v
```

Expected: 全绿（含既有测试）。再跨进程验确定性：

```bash
for i in 1 2 3 4 5; do
  python -c "
from loom.continuity import detect_char_continuity
book = {2: [('状态', '沈砚:闭关|第2章')]}
body = '砚公子与砚兄一同现身，砚某也在。' * 20
print([(b.evidence, b.prior) for b in detect_char_continuity(book, 4, body, {'沈砚'})])
"
done | sort -u | wc -l
```

Expected: `1`。（注意这段 body 含「现身」，属 `_RESOLVED` → 预期输出为 `[]`，同样必须五次一致。若想测非空分支，把「现身」换成「站着」。）

- [ ] **Step 5: 全量回归**

```bash
python -m pytest tests/ -q && python -m evals.run_eval --gate; echo "gate exit=$?"
```

Expected: 全绿；`gate exit=0`。

- [ ] **Step 6: Commit**

```bash
git add loom/continuity.py tests/test_continuity.py
git commit -m "$(cat <<'MSG'
fix(除虫): detect_char_continuity 四个 bug——死参数/指错章/恒真判据/证据随机

① char_names 是死参数,函数体从没引用 → 账本里「护山大阵」也被当人物报
② prior 用了泄漏的循环变量 m,永远指最早那章 → 双证据指错地方
③ `state_line not in body[:500]` 实质恒真 → 有闭关角色就每章刷报告
④ 单姓当别名(苏醒/苏州撞词)+ set 遍历 → 同稿两次除虫证据不同

旧测试全绿是因为 fixture 恰好把状态放在第 1 章,掩盖了 ②。
新回归测试的状态一律放非第 1 章,并加跨进程确定性自证。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 14: 回写链可追溯 + LLM 侧失败不再被裸 except 吞掉

**Files:**
- Modify: `loom/continuity.py:430-431`（`scan_chapter` 内的裸 except）
- Modify: `loom/agents.py`（`_scan_continuity` 的外层裸 except）
- Test: `tests/test_continuity.py`

**Interfaces:**
- Consumes: 无
- Produces: LLM 侧失败/哑火时向 `progress` 发 `events.warn`；成功/失败都不阻断出稿（签名不变）

**Why:** 有**两处**裸 `except` 串联，任一处都能让失败彻底消音：

| 位置 | 现状 |
|---|---|
| `loom/continuity.py:430-431` | `except Exception: pass` —— LLM 调用/解析失败被吞 |
| `loom/agents.py` `_scan_continuity` | `except Exception: pass` —— 连 `scan_chapter` 整个炸掉也被吞 |

后果：「prompt 格式漂移 / 后端配额耗尽 / `parse_scan` 全不匹配」三种情况的表象与「本章无矛盾」**完全一样**，除虫的双引擎可能长期只剩单引擎而无人知。状态账本又是从**未经手改的 AI 终稿**蒸出、write-once、同时喂写手 prompt 与四个检测器，哑掉的代价被放大。

还有第三种哑火：`backend.complete` 成功返回但 `parse_scan(raw)` 两个列表都空（prompt 漂移导致格式不匹配）—— 不走 except，连异常都没有。也要报。

**不做什么**：不改回写链的设计（AI 终稿蒸设定是既有决策，what 维度上 ADR 0001 的铁律不适用），不加阻断。只让失败可见。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_continuity.py`：

```python
def test_scan_chapter_llm_failure_is_visible_not_silent(tmp_path):
    """LLM 侧挂掉时表象不得与「本章无矛盾」相同——否则双引擎哑一半没人知道。"""
    from loom.continuity import scan_chapter

    class _BoomBackend:
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            raise RuntimeError("配额耗尽")

    seen = []
    root = tmp_path / "book"
    (root / "正文").mkdir(parents=True)
    rep = scan_chapter(root, 2, "正文内容。" * 20, _BoomBackend(), progress=seen.append)
    msgs = " ".join(str(e) for e in seen)
    assert "配额耗尽" in msgs, f"失败原因必须可见:{seen}"
    assert rep["issues"] is not None, "确定性侧仍要照常出结果,不阻断"


def test_scan_chapter_reports_when_llm_returns_unparsable(tmp_path):
    """后端返回了、但 parse_scan 一条都没抓到 —— 这是 prompt 漂移的典型表象,
    不走 except、连异常都没有,同样必须报出来。"""
    from loom.continuity import scan_chapter

    class _GarbageBackend:
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            return "本章读下来没发现什么问题。"      # 非空但格式不合,parse_scan 抓 0 条

    seen = []
    root = tmp_path / "book"
    (root / "正文").mkdir(parents=True)
    scan_chapter(root, 2, "正文内容。" * 20, _GarbageBackend(), progress=seen.append)
    msgs = " ".join(str(e) for e in seen)
    assert "格式" in msgs or "没抓到" in msgs, f"哑火必须可见:{seen}"


def test_agents_scan_continuity_does_not_swallow_silently(tmp_path):
    """agents 侧的外层裸 except 会连 scan_chapter 整个炸掉都吞掉——也要留痕。"""
    from loom.agents import _scan_continuity
    from loom.config import Config

    class _BoomBackend:
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            raise RuntimeError("后端不可用")

    seen = []
    cfg = Config()
    cfg.continuity_scan = True
    _scan_continuity(tmp_path / "nonexistent", 2, "正文。" * 20, _BoomBackend(),
                     cfg, seen.append)
    msgs = " ".join(str(e) for e in seen)
    assert "除虫" in msgs, f"外层也不得静默吞掉:{seen}"
```

- [ ] **Step 2: 跑测试确认它们红**

```bash
python -m pytest tests/test_continuity.py -k "visible_not_silent or unparsable or swallow" -v
```

Expected: 三条全 FAIL —— 两处裸 `except` 把一切都吞了，`seen` 里没有任何失败痕迹。

- [ ] **Step 3a: 修 `loom/continuity.py:430-431`**

把这两行：

```python
    except Exception:
        pass   # LLM 侧任何失败都吞:确定性结果照出,附赠动作绝不拖累出稿
```

替换为：

```python
    except Exception as e:  # noqa: BLE001 — 不拖累出稿,但**必须留下痕迹**
        # 裸吞会让「prompt 漂移 / 配额耗尽 / parse 全不匹配」的表象与「本章无矛盾」
        # 完全一样,除虫的双引擎可能长期只剩单引擎而无人知(确定性侧仍照常出结果)。
        progress(events.warn(f"除虫的 LLM 侧这次没跑成({type(e).__name__}:{e});"
                             "确定性检测结果仍然有效,但这一章没有 LLM 侧的交叉验证。"))
    else:
        if not llm_items and not state_lines:
            # 后端返回了却一条都没抓到:典型的 prompt 格式漂移,不走 except、连异常都没有。
            progress(events.warn("除虫的 LLM 侧返回了内容但一条都没解析出来"
                                 "(格式可能已漂移);本章只有确定性检测的结果。"))
```

- [ ] **Step 3b: 修 `loom/agents.py` 的 `_scan_continuity`**

把：

```python
    except Exception:
        pass
```

替换为：

```python
    except Exception as e:  # noqa: BLE001 — 附赠动作绝不阻断出稿,但不静默
        progress(events.warn(f"除虫这次没跑成({type(e).__name__}:{e});不影响本章出稿。"))
```

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

```bash
python -m pytest tests/test_continuity.py -v && python -m pytest tests/ -q
```

Expected: 全绿。若 `test_agents_scan_continuity_does_not_swallow_silently` 因 `Config()` 构造参数不符而报错，按 `loom/config.py` 的实际字段调整测试里的构造方式（不要改产品代码去迁就测试）。

- [ ] **Step 6: Commit**

```bash
git add loom/continuity.py loom/agents.py tests/test_continuity.py
git commit -m "$(cat <<'MSG'
fix(除虫): 两处裸 except 不再静默吞掉失败——双引擎哑一半要看得见

continuity.scan_chapter 与 agents._scan_continuity 各有一处
`except Exception: pass`,串联起来让「prompt 漂移/配额耗尽/parse 全不
匹配」的表象与「本章无矛盾」完全一样。另加第三种哑火的检测:后端返回了
但一条都没解析出来(不走 except、连异常都没有)。

状态账本是从未经手改的 AI 终稿蒸出、write-once、同时喂写手 prompt 与
四个检测器,哑掉的代价被放大。改成发 warn 事件,仍不阻断出稿。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 15: eval 侧开出除虫口径

**Files:**
- Modify: `evals/generate.py:63`
- Test: `tests/test_eval_generate.py`

**Interfaces:**
- Consumes: 无
- Produces: gen case 可用 `"continuity_scan": true` 打开除虫；缺省仍为 `false`（省一次调用，与既有 golden 口径一致）

**Why:** `evals/generate.py:63` 硬编码 `cfg.continuity_scan = False`，所以**除虫在评测里从来没被跑过**。四个检测器里只有 `aitell` 进了 evalapi/evals，`fatigue`、`continuity` 的四个 `detect_*`、`sensitive` 全无 eval 侧回归。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_eval_generate.py`：

```python
def test_gen_case_can_opt_into_continuity_scan(tmp_path):
    """除虫此前被硬编码关死,评测里从没跑过。改成 case 可声明,缺省仍关。"""
    from evals.generate import load_gen_case, prepare_project
    d = tmp_path / "gc_scan"
    (d).mkdir(parents=True)
    (d / "case.json").write_text(json.dumps({
        "id": "scan_on", "chapter_n": 1, "chapter_chars": 200,
        "continuity_scan": True,
    }, ensure_ascii=False), encoding="utf-8")
    case = load_gen_case(d)
    work = tmp_path / "w"; work.mkdir()
    cfg = load_config(prepare_project(d, case, work))
    assert cfg.continuity_scan is True


def test_gen_case_continuity_scan_defaults_off(tmp_path):
    from evals.generate import load_gen_case, prepare_project
    case_dir = _write_gen_case(tmp_path)
    case = load_gen_case(case_dir)
    work = tmp_path / "w2"; work.mkdir()
    cfg = load_config(prepare_project(case_dir, case, work))
    assert cfg.continuity_scan is False, "缺省必须仍关——省一次调用,与既有 golden 同口径"
```

- [ ] **Step 2: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_generate.py -k continuity_scan -v
```

Expected: `test_gen_case_can_opt_into_continuity_scan` FAIL（恒为 False）。

- [ ] **Step 3: 实现**

`evals/generate.py`，把 `prepare_project` 里那一行改成：

```python
    # 附赠扫描是额外模型调用,评测缺省关(与既有 golden 同口径);case 可显式打开,
    # 好让除虫这条链也有 eval 覆盖——此前它被硬编码关死,评测里从来没跑过。
    cfg.continuity_scan = bool(case.get("continuity_scan", False))
```

- [ ] **Step 4: 跑测试确认绿 + 确认既有 7/8 调契约没被打破**

```bash
python -m pytest tests/test_eval_generate.py -v && python -m pytest tests/ -q
```

Expected: 全绿。特别确认 `test_generate_one_end_to_end_offline`（7 调）与 Task 5 的 8 调测试仍过 —— 缺省关，调用数不变。

- [ ] **Step 5: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'MSG'
feat(eval): gen case 可声明 continuity_scan——除虫此前在评测里从没跑过

generate.py:63 把它硬编码关死。四个确定性检测器里只有 aitell 进了
evalapi/evals,fatigue/continuity/sensitive 全无 eval 侧回归。
缺省仍关(省一次调用、与既有 golden 同口径),case 可显式打开。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 16: 收紧 len_tolerance（**阻塞于真机基线**）

**Files:**
- Modify: `evals/cases/case_01_clean/case.json`、`evals/cases/case_02_flawed/case.json`、`evals/gen_cases/gen_01_mine_rebirth/case.json`、`evals/gen_cases/gen_02_mine_escape/case.json`
- Modify: `evals/baseline.json`（重新固化）
- Test: `tests/test_eval_cli.py`（追加封顶护栏）

**Interfaces:**
- Consumes: 真机基线数据（§验收 6）
- Produces: 所有 case 的 `expect.len_tolerance ≤ 0.25`

**⚠️ 前置条件**：本 Task **不得在拿到真机基线前执行**。spec 明写「先量后定」，目的就是避免又一个拍脑袋阈值。若基线还没跑，跳过本 Task，先做「执行完成后」一节的真机基线步骤。

**Why:** 三个 case 全是 `len_tolerance: 0.6`（±60%），`harness` 缺省 0.5。字数是闭环要盯的核心指标，±60% 等于没牙齿 ——「目标 3000 字交 400 字」偏差 0.867，虽然 0.6 也能抓，但 ±60% 让「3000 字交 4800 字」这类真实的写手失控完全免检。

- [ ] **Step 1: 看真机基线的实际字数分布**

```bash
python -c "
import json, pathlib
for b in sorted(p for p in pathlib.Path('evals/runs').iterdir() if 'batch' in p.name):
    s = json.loads((b / 'summary.json').read_text(encoding='utf-8'))
    if s['n_valid'] == 0: continue
    for role, items in s['steps'].items():
        for name, d in items.items():
            if '篇幅' in name and d['median'] is not None:
                print(f\"{s['case_id']:<22} {role}·{name:<16} 中位 {d['median']}  区间 {d['lo']}~{d['hi']}\")
"
```

记下**终稿**字数相对目标的实际偏差幅度。

- [ ] **Step 2: 定值并写护栏测试**

选一个 ≤0.25 的值（记为 `T`），使真机基线里的正常运行不会被判失败。追加到 `tests/test_eval_cli.py`：

```python
def test_all_cases_len_tolerance_is_capped():
    """字数容差封顶 0.25:超过它这个 grader 事实上不设防,不如老实标 observe。
    值本身是「先量后定」的——看完真机基线的实际分布才定,git 历史即证据。"""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    bad = []
    for p in list((root / "evals" / "cases").glob("*/case.json")) + \
            list((root / "evals" / "gen_cases").glob("*/case.json")):
        tol = json.loads(p.read_text(encoding="utf-8")).get("expect", {}).get("len_tolerance")
        if tol is not None and tol > 0.25:
            bad.append(f"{p.parent.name}: {tol}")
    assert not bad, f"这些 case 的 len_tolerance 超过封顶 0.25:{bad}"
```

- [ ] **Step 3: 跑测试确认它红**

```bash
python -m pytest tests/test_eval_cli.py::test_all_cases_len_tolerance_is_capped -v
```

Expected: FAIL，列出四个 case 的 `0.6`。

- [ ] **Step 4: 改四个 case 的值**

把 `evals/cases/case_01_clean/case.json`、`evals/cases/case_02_flawed/case.json`、`evals/gen_cases/gen_01_mine_rebirth/case.json`、`evals/gen_cases/gen_02_mine_escape/case.json` 里的 `"len_tolerance": 0.6` 全部改成 `"len_tolerance": T`（Step 2 定的值）。

- [ ] **Step 5: 重新固化基线并确认契约没坏**

```bash
python -m pytest tests/test_eval_cli.py -v
python -m evals.run_eval --baseline
python -m evals.run_eval --gate; echo "gate exit=$?"
python -m pytest tests/ -q
```

Expected: 测试全绿；`gate exit=0`。

**必须额外确认** `case_02_flawed` 的契约仍成立：

```bash
python -c "
from pathlib import Path
from evals.harness import run_case
r = run_case(Path('evals/cases/case_02_flawed'))
print('case_type:', r.case_type, '| contract_ok:', r.contract_ok, '| passed:', r.passed)
assert r.contract_ok, '契约坏了:expect_fail_graders 里的 grader 不再命中缺陷'
print('✓ detector_contract 契约仍成立')
"
```

Expected: `✓ detector_contract 契约仍成立`。（已核对 `harness.py:75-82`：`contract_ok` 只看 `expect_fail_graders` 点名的两个 grader，长度达标不在其中，所以理论上不受影响 —— 这一步是把「理论上」变成「验过了」。）

- [ ] **Step 6: Commit**

```bash
git add evals/cases/*/case.json evals/gen_cases/*/case.json evals/baseline.json tests/test_eval_cli.py
git commit -m "$(cat <<'MSG'
fix(eval): 字数容差 0.6 → 收紧(先量后定)+ 封顶 0.25 护栏

±60% 等于没牙齿:「3000 字交 4800 字」这类写手失控完全免检。
值不是拍的——先跑真机基线看实际字数分布再定,git 历史即「非事后
倒推」的证据(同 targets.json 预注册纪律)。护栏测试钉死封顶 0.25。
基线随之重新固化;已验 case_02 的 detector_contract 契约不受影响。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## 执行完成后：真机基线（要花 API 费，择时跑）

这是 spec §12.6 的验收项，也是 Task 16 的前置。**不在自动化流程里，需要人拍板何时跑。**

```bash
# 1) 把 key 灌进进程环境(CI 里由 secret 经 env: 直接进环境)
set -a; . ~/.loom/.env; set +a

# 2) 两个 case 各跑 5 次取分布
python -m evals.generate --case gen_01_mine_rebirth --backend configured --repeat 5
python -m evals.generate --case gen_02_mine_escape  --backend configured --repeat 5

# 3) 读最弱棒
python -c "
import json, pathlib
for b in sorted(p for p in pathlib.Path('evals/runs').iterdir() if 'batch' in p.name)[-2:]:
    print((b / 'summary.md').read_text(encoding='utf-8'))
"
```

**拿到基线之后**：先做 Task 16，再按 `weakest` 指的那一棒改 prompt，改完用同一套 suite 复测：

```bash
python -m evals.generate --case gen_02_mine_escape --backend configured --repeat 5
python -m evals.generate --compare <改动前batch> <改动后batch>
```

**区间重叠就是「分不出」，不宣称改进** —— 这条纪律比任何单个数字都重要。

spec §10 已列出四个大概率被点名的结构性缺陷（编辑失明 / 设定师失明 / 续跑吃细纲 / 大纲师字数指令自相矛盾），但**以基线数据为准**，不要预先假定。

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 对应 Task |
|---|---|
| §3 架构（收 ledger、目录结构） | Task 4, 5 |
| §3 gen_02（大纲师真跑） | Task 9 |
| §4 棒级体检项（五棒） | Task 6, 7 |
| §4 复用纪律（evalapi 接缝） | Task 4 |
| §5 数据流（`--repeat`、batch、`--compare`） | Task 11, 12 |
| §5 判据纪律（区间重叠不宣称改进） | Task 10（`overlaps`）、Task 12 |
| §6 LLM grader fail-open | Task 2 |
| §6 `--judge`/`--gate` 互斥 | Task 3 |
| §6 `len_tolerance` | Task 16（阻塞于基线） |
| §6 pyyaml | Task 1 |
| §7 continuity 四个 bug | Task 13 |
| §7 回写链 LLM 失败不吞 | Task 14 |
| §7 eval 侧除虫口径 | Task 15 |
| §8 错误处理（infra 不冒充、skipped 不记 0、全 infra 码 2） | Task 6（`skipped`）、Task 10、Task 11 |
| §9 测试策略 | 每个 Task 的 Step 1 |
| §10 第一批 agent 修复目标 | 「执行完成后」一节（数据驱动，不预先假定） |
| §12 验收 | Task 各步 + 「执行完成后」 |

**§7 的「入账项可追溯到章号」**由 Task 13 的 `prior_ch` 修复覆盖（`prior=f"第{prior_ch}章账本:…"` 现在指对章了）。

**2. Placeholder scan** —— 无 TBD/TODO；每个改代码的 Step 都带完整代码块；Task 14 Step 1 要求先读现状再按实际行号调整，这是必要的，因为该分支的确切结构需现场确认，Step 2 也给了「函数名以实际为准」的处置说明。

**3. Type consistency**

- `collect_steps(project, chapter_n, run_dir) -> dict[str, str | None]`（Task 5）→ `grade_steps(steps, case)` 消费（Task 8）✓
- `skipped(step, item)` 的形状（`passed=True, gating=False, weight=0.0`）在 Task 6 定义，Task 10 的 `aggregate_runs` 按 `gating=False` 排除出分布 ✓
- `Distribution.as_dict()` 的键（`median/lo/hi/n_valid/n_total`）在 Task 10 定义，Task 11 的 `_summary_md`、Task 12 的 `overlaps`/`compare_batches` 都按这套键读 ✓
- `evalapi` 七个新导出名（Task 4）与 `stepgraders.py` 的 import（Task 6）逐一对应：`STEP_SHORT_BUDGETS`、`parse_scene_budgets`、`scene_range`、`split_edit_note` ✓（`PIPELINE`、`load_ledger` 在 `generate.py` 用，`ledger_path` 暂未被消费但属接缝完整性，保留）
- `_GEN_RUN_8` / `_OUTLINE` 在 Task 5 定义，Task 8 复用 ✓
- `run_batch` 的 `backend_factory` / `workdir_root` 参数（Task 11）与测试调用一致 ✓
