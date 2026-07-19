# Eval Phase 3:LLM-Judge 校准链 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 把 Judge 从「自由文本 + `_parse_verdict`」升级成结构化 JSON verdict,建立 Cohen's κ + 每维 P/R/F1 的 meta-eval 与预注册阈值,产出可追溯校准报告——真实的人-人 / Judge-人一致性数字**留空位等真标注**,绝不造数。

**Architecture:** 新增 `evals/judge.py`(结构化 Judge:prompt 判据单源自 evalapi 的 CRITIC + rubric.md,只换输出格式为 JSON;后端/解析失败→infra_error)、`evals/calibration.py`(κ/PRF 纯函数 + 报告生成器)、`evals/calibration/targets.json`(预注册阈值)、`evals/export_packets.py`(无剧透标注包)。全部住 `evals/` 侧,产品 `gates.py`/`parse.py`/UI 零改动。零真实模型进测试(FakeBackend/ScriptedBackend + 合成夹具)。

**Tech Stack:** Python 3.11 + pytest(现基线 618 绿)。零新依赖(κ/PRF 手写,不引 sklearn)。

**权威 spec:** `/Users/chambers/Desktop/loom-novel_eval补齐计划.md` §Phase 3 + 路线图 `docs/superpowers/plans/2026-07-17-eval-roadmap-phase3-5.md` + 侦察档案 `.superpowers/sdd/recon-p14/judge.md`。

## Global Constraints

- **文件白名单**:新建 `evals/judge.py`、`evals/calibration.py`、`evals/calibration/targets.json`、`evals/export_packets.py`、`tests/test_eval_judge_structured.py`、`tests/test_eval_calibration.py`、`tests/test_eval_export_packets.py`;修改 `loom/evalapi.py`(**唯一允许碰的 loom/ 文件,只准追加纯再导出**)、`evals/dataset.py`(仅 Task 7 的 dimension 类型防御一处)、`evals/dataset/ANNOTATION_GUIDE.md`(仅 Task 7 的 jq 命令 backlog 修补)、`evals/README.md`(Task 7)。**不碰** `evals/run_eval.py`/`harness.py`/`graders.py`/`generate.py`/`metering.py`(前序 suite 已冻结)、`evals/dataset/rubric.md`(Phase 2 已定稿)、`evals/dataset/cases/**`(金标不动)、`.github/workflows/`(Phase 4)、其余 `loom/**`。
- **产品红线(ADR-0002 / ADR-0006)**:结构化 verdict **不得引入数值 score 字段**;severity 只用类别 {高,中,低,null}(对齐 rubric 与 `dataset.SEVERITIES`)。κ/PRF/阈值判定只在 `evals/calibration.py`,**绝不 import 进任何产品模块**。`loom/gates.py`/`parse.py` 的自由文本 critic 与中文-key `Issue` 结构一个字不动(`events.py`/前端在消费它)。
- **判据单源(spec「不复制另一套 prompt」)**:Judge system prompt 的维度判据 = `evalapi.CRITIC_质检` + `evalapi.CRITIC_去AI味`(引擎权威,经门面导入)+ `rubric.md`(操作化细节)。Phase 3 只替换「输出格式指令」为 JSON,**不重写维度判据**。
- **evalapi 红线**:evals 侧新代码只准 `from loom.evalapi import ...`;import 失败不降级不吞。改 evalapi 只加不改(纯再导出)。
- **不造数(spec §5)**:报告里凡需真人标注或真机才有的数字(κ人人、Judge-金标 κ、真机 token/成本),一律如实标 `待标注`/`待真机` + `N=0`,**绝不用 targets.json 的阈值冒充结果**。targets.json 里的阈值注明「待验收标准,非当前事实」。
- **零真实模型进测试**:Judge 测试用 conftest `FakeBackend(responder)`(`responder(system,user)->str`)/`ScriptedBackend(replies)`;κ/PRF 用合成标注夹具。绝不初始化真后端。
- 既有测试断言禁改。提交信息 `type(scope): 中文摘要` + 末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件,绝不 `git add -A`。
- 环境 `.venv/bin/python`;测试 `.venv/bin/python -m pytest`。

## 现状锚点(实现者必读——侦察核实过的真实代码,别猜)

- `evals/dataset.py`:`DIMENSIONS: tuple = ("人物OOC","设定漂移","断钩子","无爽点","信息边界","物品状态连续性","时间连续性","AI腔")`(8 维,单一来源);`SEVERITIES = ("高","中","低")`;`SPLITS = ("dev","calibration","holdout")`;`load_case(case_dir)->dict`(返回含 `context` 四键 + `chapter` 正文 + `labels` 金标);`discover_cases(dataset_dir=None)->list[Path]`。
- `loom/evalapi.py` 现导出 13 名(Phase 0 的 6 个 + Phase 1 加的 7 个生成接缝)。`CRITIC_质检`/`CRITIC_去AI味`/`Issue`/`parse_critic_verdict` 已在其中。
- `CRITIC_质检`(`gates.py:129`)覆盖 ①人物OOC ②设定漂移 ③断钩子 ④无爽点 ⑤信息边界 ⑥物品状态连续性 ⑦时间连续性,输出格式指令是「无硬伤只回一行「通过」;有则每条一行 `- 类别|问题|证据:"原文短引"`」。`CRITIC_去AI味`(`gates.py:148`)覆盖 AI腔(套话头尾/空洞万能词/过度连接词/直接点名情绪/黑名单词/句式过整齐 + 写作指纹豁免护栏)。两者合计恰好 8 维 = `DIMENSIONS`。
- `evals/dataset/rubric.md`:8 个 `## <维度名>` 小节,每维六节(定义/该抓正例/不该抓反例/边界例/严重度/证据要求)。Judge prompt 要嵌入它的操作化细节。
- conftest:`FakeBackend(responder)`(`complete(system,user,*,max_chars=None,on_chunk=None)`,responder 内 `raise` 即测后端失败路径)、`ScriptedBackend(replies)`(按序 pop,耗尽返 `""`)。
- `evals/metering.py`:`MeteringBackend(inner)`(Phase 1),`.records: list[CallRecord]`(含 `elapsed_s`/`output_chars`)——Judge 若要记时延可复用。
- `evals/dataset.py:77-78`:`dims = [l.get("dimension") for l in labels]; if sorted(dims) != sorted(DIMENSIONS)`——dimension 非 str(如 int/None)时 `sorted(dims)` 裸 TypeError(P2.T1 审查残留,Task 7 修)。

---

### Task 1: 结构化 verdict schema + 严格 JSON 解析器

**Files:**
- Create: `evals/judge.py`(本任务只到 schema+parser 层)
- Test: `tests/test_eval_judge_structured.py`(新建)

**Interfaces:**
- Produces:
  - `DimensionVerdict(dimension: str, present: bool, severity: str | None, evidence: str, reason: str)`(dataclass,`as_dict()` 返回同名键)。
  - `JudgeParseError(ValueError)`。
  - `parse_judge_verdict(raw: str) -> list[DimensionVerdict]`:严格解析 JSON 数组,必须恰好覆盖 `DIMENSIONS` 8 维(不重不漏不越界);severity ∈ `SEVERITIES ∪ {None}`,present=False 时 severity 必须为 None;非法 JSON / 缺维 / 越界维 / 非法 severity / present-severity 矛盾 → `JudgeParseError`。返回按 `DIMENSIONS` 顺序排列。容忍 ```json 代码围栏。
- Consumes: `evals.dataset.DIMENSIONS`、`evals.dataset.SEVERITIES`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_judge_structured.py`:

```python
"""结构化 Judge:schema/严格解析/prompt/infra 三态。零真实模型。"""
import json

import pytest

from evals.dataset import DIMENSIONS
from evals.judge import DimensionVerdict, JudgeParseError, parse_judge_verdict


def _full_verdict(**overrides):
    """8 维全 present=False 的合法 verdict JSON(可覆写个别维)。"""
    items = []
    for d in DIMENSIONS:
        item = {"dimension": d, "present": False, "severity": None, "evidence": "", "reason": "无"}
        if d in overrides:
            item.update(overrides[d])
        items.append(item)
    return json.dumps(items, ensure_ascii=False)


def test_parse_clean_verdict_all_absent():
    vs = parse_judge_verdict(_full_verdict())
    assert len(vs) == 8
    assert [v.dimension for v in vs] == list(DIMENSIONS)   # 按 DIMENSIONS 顺序
    assert all(v.present is False and v.severity is None for v in vs)


def test_parse_present_dimension():
    raw = _full_verdict(设定漂移={"present": True, "severity": "高",
                                  "evidence": "御空长剑", "reason": "违反无飞行铁律"})
    vs = {v.dimension: v for v in parse_judge_verdict(raw)}
    assert vs["设定漂移"].present is True and vs["设定漂移"].severity == "高"


def test_parse_tolerates_code_fence():
    raw = "```json\n" + _full_verdict() + "\n```"
    assert len(parse_judge_verdict(raw)) == 8       # 模型爱包围栏,得容忍


def test_malformed_json_raises():
    with pytest.raises(JudgeParseError):
        parse_judge_verdict("这不是 JSON,是自由文本「通过」")


def test_missing_dimension_raises():
    items = json.loads(_full_verdict())[:-1]        # 少一维
    with pytest.raises(JudgeParseError, match="缺"):
        parse_judge_verdict(json.dumps(items, ensure_ascii=False))


def test_unknown_dimension_raises():
    items = json.loads(_full_verdict())
    items[0]["dimension"] = "文学性"                # 越界维(rubric 外)
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(json.dumps(items, ensure_ascii=False))


def test_illegal_severity_raises():
    raw = _full_verdict(AI腔={"present": True, "severity": "致命", "evidence": "x", "reason": "y"})
    with pytest.raises(JudgeParseError, match="severity"):
        parse_judge_verdict(raw)


def test_present_false_with_severity_raises():
    raw = _full_verdict(断钩子={"present": False, "severity": "高"})
    with pytest.raises(JudgeParseError):
        parse_judge_verdict(raw)


def test_dimension_verdict_as_dict_roundtrip():
    v = DimensionVerdict("AI腔", True, "低", "翻转句", "命中")
    assert v.as_dict() == {"dimension": "AI腔", "present": True, "severity": "低",
                           "evidence": "翻转句", "reason": "命中"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'evals.judge'`。

- [ ] **Step 3: 实现**

新建 `evals/judge.py`:

```python
"""结构化 LLM-Judge(eval 侧,产品永不 import):跑 8 维 rubric,吐严格 JSON verdict。

与产品 gates.py 的自由文本 critic 分离:判据单源自 evalapi 的 CRITIC + rubric.md,
本模块只把「输出格式」从自由文本换成 JSON,好逐维对账算 κ/PRF。severity 只用类别
{高,中,低,null},绝不引数值分(ADR-0002)。后端/解析失败 → infra_error,不假通过(P0-C)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .dataset import DIMENSIONS, SEVERITIES

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class JudgeParseError(ValueError):
    """Judge 输出不是合法的 8 维 JSON verdict(非法 JSON/缺维/越界/非法 severity)。"""


@dataclass
class DimensionVerdict:
    dimension: str
    present: bool
    severity: str | None
    evidence: str
    reason: str

    def as_dict(self) -> dict:
        return {"dimension": self.dimension, "present": self.present,
                "severity": self.severity, "evidence": self.evidence, "reason": self.reason}


def parse_judge_verdict(raw: str) -> list[DimensionVerdict]:
    """严格解析 Judge 输出为 8 维 verdict;任何不合规 → JudgeParseError(交上层判 infra)。"""
    cleaned = _FENCE_RE.sub("", raw).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        raise JudgeParseError(f"非法 JSON:{e}") from e
    if not isinstance(data, list):
        raise JudgeParseError(f"verdict 顶层须为数组,现为 {type(data).__name__}")

    by_dim: dict[str, DimensionVerdict] = {}
    for item in data:
        if not isinstance(item, dict):
            raise JudgeParseError(f"verdict 项须为对象,现为 {type(item).__name__}")
        dim = item.get("dimension")
        if dim not in DIMENSIONS:
            raise JudgeParseError(f"越界/缺失维度:{dim!r}(须 ∈ {DIMENSIONS})")
        if dim in by_dim:
            raise JudgeParseError(f"维度重复:{dim}")
        present = item.get("present")
        if not isinstance(present, bool):
            raise JudgeParseError(f"{dim}: present 须为 bool")
        severity = item.get("severity")
        if present:
            if severity not in SEVERITIES:
                raise JudgeParseError(f"{dim}: present=True 的 severity 须 ∈ {SEVERITIES}")
        else:
            if severity is not None:
                raise JudgeParseError(f"{dim}: present=False 的 severity 须为 null")
        by_dim[dim] = DimensionVerdict(
            dimension=dim, present=present, severity=severity,
            evidence=str(item.get("evidence", "")), reason=str(item.get("reason", "")))

    missing = [d for d in DIMENSIONS if d not in by_dim]
    if missing:
        raise JudgeParseError(f"缺维度:{missing}")
    return [by_dim[d] for d in DIMENSIONS]
```

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -q`
Expected: 9 passed。

- [ ] **Step 5: Commit**

```bash
git add evals/judge.py tests/test_eval_judge_structured.py
git commit -m "$(cat <<'EOF'
feat(eval): 结构化 Judge verdict schema + 严格 JSON 解析器(Phase 3)

DimensionVerdict{dimension,present,severity∈{高,中,低,null},evidence,reason}——
无数值分(ADR-0002)。parse_judge_verdict 严格核验恰好覆盖 8 维不重不漏不越界、
severity 合法、present-severity 自洽;任何不合规 → JudgeParseError(上层判 infra,
不假通过)。容忍 ```json 围栏。判据单源留给 Task 2 的 prompt。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Judge prompt 构造(判据单源自 evalapi CRITIC + rubric)

**Files:**
- Modify: `evals/judge.py`(加 prompt 构造)
- Modify: `loom/evalapi.py`(若需——本任务从 evalapi 拿 CRITIC 常量,它们已在导出里,**大概率无需改**;实现者先验证)
- Test: `tests/test_eval_judge_structured.py`(扩)

**Interfaces:**
- Consumes: `evalapi.CRITIC_质检`、`evalapi.CRITIC_去AI味`、`evals.dataset.DIMENSIONS`、`rubric.md` 文本。
- Produces: `RUBRIC_PATH: Path`;`load_rubric() -> str`;`build_judge_prompt(context: dict, chapter: str, rubric_text: str) -> tuple[str, str]`(返回 `(system, user)`)。system 含两个 CRITIC 全文 + rubric + 严格 JSON 输出指令(枚举 8 维、severity 类别、示例骨架);user 含 context 四键 + chapter。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_judge_structured.py` 追加(顶部补 `from evals.judge import build_judge_prompt, load_rubric`):

```python
def test_build_prompt_names_all_dimensions():
    ctx = {"setting": "无飞行铁律", "characters": "沈砚:寡言",
           "prev_hook": "提灯人喊破真名", "chapter_goal": "过磅"}
    system, user = build_judge_prompt(ctx, "正文内容", load_rubric())
    for d in DIMENSIONS:
        assert d in system                      # 8 维判据都在 system
    assert "JSON" in system or "json" in system  # 明确要求 JSON 输出
    assert "沈砚:寡言" in user and "正文内容" in user  # context+chapter 进 user


def test_build_prompt_carries_engine_critic_criteria():
    from loom.evalapi import CRITIC_质检, CRITIC_去AI味
    system, _ = build_judge_prompt({"setting": "s", "characters": "c",
                                    "prev_hook": "p", "chapter_goal": "g"}, "x", load_rubric())
    # 判据单源:引擎 CRITIC 原文必须嵌进 Judge system(不是另写一套)
    assert "信息边界" in CRITIC_质检 and "信息边界" in system
    assert "写作指纹" in CRITIC_去AI味 and "写作指纹" in system


def test_build_prompt_no_numeric_score_language():
    system, _ = build_judge_prompt({"setting": "s", "characters": "c",
                                    "prev_hook": "p", "chapter_goal": "g"}, "x", load_rubric())
    # ADR-0002:不许诱导模型打「总体分」
    for banned in ("总体文学分", "综合评分", "打分", "评分(0", "score"):
        assert banned not in system
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -v -k "prompt"`
Expected: FAIL——`cannot import name 'build_judge_prompt'`。

- [ ] **Step 3: 实现**

`evals/judge.py` 顶部 import 补 `from pathlib import Path` + `from loom.evalapi import CRITIC_质检, CRITIC_去AI味`。追加:

```python
RUBRIC_PATH = Path(__file__).resolve().parent / "dataset" / "rubric.md"

_JSON_INSTRUCTION = (
    "## 输出格式(严格 JSON,不要任何解释、不要正文、不要代码围栏外的字)\n"
    "输出一个 JSON 数组,**恰好 8 个对象**,每个维度一个,dimension 逐字取自:\n"
    f"{list(DIMENSIONS)}\n"
    "每个对象字段:\n"
    '  - "dimension": 维度名(上面 8 个之一)\n'
    '  - "present": true/false(该维度缺陷是否命中)\n'
    '  - "severity": present=true 时为 "高"/"中"/"低"(按 rubric 严重度分级);present=false 时为 null\n'
    '  - "evidence": 命中处的原文短引(absence 型维度如断钩子/无爽点留空字符串 "")\n'
    '  - "reason": 一句话判据(为何命中/为何干净)\n'
    "只判上面 8 个维度,不要给总体评价、不要任何数值分。宁缺毋滥:没把握按 rubric 边界例判、"
    "在 reason 里说明。"
)


def load_rubric() -> str:
    return RUBRIC_PATH.read_text(encoding="utf-8")


def build_judge_prompt(context: dict, chapter: str, rubric_text: str) -> tuple[str, str]:
    """判据单源:引擎 CRITIC(权威维度定义)+ rubric(操作化)+ JSON 输出指令。"""
    system = (
        "你是**独立评审**,只诊断、不改写。按下面的判据逐维审这一章,输出结构化 JSON。\n\n"
        "## 引擎判据(权威维度定义)\n"
        f"### 质检维度\n{CRITIC_质检}\n\n### 去AI味维度\n{CRITIC_去AI味}\n\n"
        "## 操作化细则(rubric:每维的正例/反例/边界例/严重度/证据要求)\n"
        f"{rubric_text}\n\n"
        f"{_JSON_INSTRUCTION}"
    )
    user = (
        "## 本章上下文\n"
        f"- 世界观设定:{context.get('setting', '')}\n"
        f"- 人物卡:{context.get('characters', '')}\n"
        f"- 上一章钩子:{context.get('prev_hook', '')}\n"
        f"- 本章目标:{context.get('chapter_goal', '')}\n\n"
        f"## 待评的本章正文\n{chapter}\n\n"
        "## 你的任务\n按上面 8 维判据逐维评,严格输出 JSON 数组(8 个对象)。"
    )
    return system, user
```

**实现时必验**:`from loom.evalapi import CRITIC_质检, CRITIC_去AI味` 能否 import(它们应已在 evalapi `__all__`)。若 import 报错,**才**需在 `loom/evalapi.py` 补导出——但侦察确认它们已在,预期无需改 evalapi。若 rubric 里恰好含 `_JSON_INSTRUCTION` 检查的禁词(如「打分」),那是 rubric 内容问题不该由本任务改——实测 `test_..._no_numeric_score_language`,若因 rubric 文本触发,停下报告(Phase 2 rubric 测试已保证 rubric 无这些词,预期不会)。

- [ ] **Step 4: 跑测试通过 + evalapi/golden 不破**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -q`
Expected: 12 passed。
Run: `.venv/bin/python -m pytest tests/test_golden_pipeline.py tests/test_eval_dataset.py -q`
Expected: 全绿(未碰产品/数据集)。

- [ ] **Step 5: Commit**

```bash
git add evals/judge.py tests/test_eval_judge_structured.py
git commit -m "$(cat <<'EOF'
feat(eval): Judge prompt 判据单源——evalapi CRITIC+rubric,只换输出为 JSON

build_judge_prompt 的 system = 引擎 CRITIC_质检+CRITIC_去AI味(经门面,权威维度定义)
+ rubric.md 操作化细则 + 严格 JSON 输出指令(枚举 8 维/severity 类别);不复制判据、
不诱导总体分(ADR-0002)。user = context 四键 + 正文。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: judge_case 运行器 + infra 三态 + Judge CLI

**Files:**
- Modify: `evals/judge.py`(judge_case + JudgeResult + main)
- Test: `tests/test_eval_judge_structured.py`(扩)

**Interfaces:**
- Consumes: Task 1/2、`evals.metering.MeteringBackend`、`evals.dataset.load_case`/`discover_cases`、conftest FakeBackend/ScriptedBackend。
- Produces:
  - `JudgeResult(case_id: str, verdicts: list[DimensionVerdict], infra_error: bool, error: str, elapsed_s: float)`,`as_dict()`。
  - `judge_case(case: dict, backend, *, rubric_text=None) -> JudgeResult`:build→complete→parse;后端异常 OR JudgeParseError → `infra_error=True`(verdicts=[],error 带 `[infra]` 前缀),**绝不假通过**。
  - `main(argv) -> int`:`--case <id>`/全部、`--backend {demo,configured}`、`--out <path>`(verdicts.jsonl);退出码 0=完成 / 2=infra(无 case 目录 / 找不到 case)。demo 只证链路。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_judge_structured.py` 追加(顶部补 `from conftest import FakeBackend, ScriptedBackend`、`from evals.judge import judge_case, JudgeResult`):

```python
def _case_stub():
    return {"id": "t", "context": {"setting": "s", "characters": "c",
            "prev_hook": "p", "chapter_goal": "g"}, "chapter": "正文"}


def test_judge_case_clean_all_absent():
    be = FakeBackend(lambda s, u: _full_verdict())
    r = judge_case(_case_stub(), be)
    assert r.infra_error is False
    assert len(r.verdicts) == 8 and all(not v.present for v in r.verdicts)


def test_judge_case_backend_failure_is_infra_not_fake_pass():
    def boom(s, u):
        raise RuntimeError("后端炸了")
    r = judge_case(_case_stub(), FakeBackend(boom))
    assert r.infra_error is True                 # 后端挂了绝不假通过(P0-C)
    assert "[infra]" in r.error
    assert r.verdicts == []


def test_judge_case_malformed_output_is_infra():
    r = judge_case(_case_stub(), FakeBackend(lambda s, u: "通过"))  # 自由文本非 JSON
    assert r.infra_error is True and "[infra]" in r.error


def test_judge_result_as_dict_shape():
    r = judge_case(_case_stub(), FakeBackend(lambda s, u: _full_verdict()))
    d = r.as_dict()
    assert d["case_id"] == "t" and d["infra_error"] is False
    assert len(d["verdicts"]) == 8 and d["verdicts"][0]["dimension"] == DIMENSIONS[0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -v -k "judge_case or judge_result"`
Expected: FAIL——`cannot import name 'judge_case'`。

- [ ] **Step 3: 实现**

`evals/judge.py` 顶部 import 补 `import time`、`from dataclasses import dataclass, field`、`from .metering import MeteringBackend`。追加:

```python
@dataclass
class JudgeResult:
    case_id: str
    verdicts: list[DimensionVerdict] = field(default_factory=list)
    infra_error: bool = False
    error: str = ""
    elapsed_s: float = 0.0

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "infra_error": self.infra_error, "error": self.error,
                "elapsed_s": self.elapsed_s, "verdicts": [v.as_dict() for v in self.verdicts]}


def judge_case(case: dict, backend, *, rubric_text: str | None = None) -> JudgeResult:
    """跑一例结构化 Judge。后端异常 OR 解析失败 → infra_error(不假通过 P0-C)。"""
    rubric_text = load_rubric() if rubric_text is None else rubric_text
    system, user = build_judge_prompt(case.get("context", {}), case.get("chapter", ""), rubric_text)
    metered = MeteringBackend(backend)
    t0 = time.perf_counter()
    try:
        raw = metered.complete(system, user, max_chars=1500)
    except Exception as e:  # noqa: BLE001 — 后端报错=infra,绝不假通过
        return JudgeResult(case.get("id", "?"), [], True, f"[infra] 后端调用失败 — {e}",
                           round(time.perf_counter() - t0, 3))
    try:
        verdicts = parse_judge_verdict(raw)
    except JudgeParseError as e:
        return JudgeResult(case.get("id", "?"), [], True, f"[infra] verdict 解析失败 — {e}",
                           round(time.perf_counter() - t0, 3))
    return JudgeResult(case.get("id", "?"), verdicts, False, "", round(time.perf_counter() - t0, 3))
```

CLI(追加,`main` 复用 dataset 的 discover/load + generate 的 backend 选择法):

```python
def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    from .dataset import discover_cases, load_case

    ap = argparse.ArgumentParser(description="loom 结构化 Judge(手动/定时跑,不进 PR CI)")
    ap.add_argument("--case", help="case id;缺省跑全部数据集")
    ap.add_argument("--backend", choices=["demo", "configured"], default="demo",
                    help="demo=占位后端(只证链路,demo 不吐合法 JSON→会 infra,属预期);configured=真后端(要 key)")
    ap.add_argument("--dataset-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="verdicts.jsonl 落盘路径")
    args = ap.parse_args(argv)

    cases = discover_cases(args.dataset_dir)
    if not cases:
        print("✗ 没有校准数据集 case(evals/dataset/cases/<id>/case.json)")
        return 2
    if args.case:
        cases = [c for c in cases if c.name == args.case]
        if not cases:
            print(f"✗ 找不到 case:{args.case}")
            return 2

    backend = None
    if args.backend == "demo":
        os.environ["LOOM_DEMO"] = "1"
    from loom.evalapi import get_backend, Config
    backend = get_backend(Config())

    results = []
    for cdir in cases:
        r = judge_case(load_case(cdir), backend)
        results.append(r)
        flag = "⚠infra" if r.infra_error else "✓"
        hits = sum(1 for v in r.verdicts if v.present)
        print(f"{flag} {r.case_id}  命中 {hits}/8 维  {r.error}")
    if args.out:
        args.out.write_text("\n".join(json.dumps(r.as_dict(), ensure_ascii=False) for r in results),
                            encoding="utf-8")
        print(f"→ 写入 {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: 跑测试通过 + demo 冒烟**

Run: `.venv/bin/python -m pytest tests/test_eval_judge_structured.py -q`
Expected: 16 passed。
Run: `.venv/bin/python -m evals.judge --case ds_01_ooc --backend demo; echo "码=$?"`
Expected: 打一行 `⚠infra ds_01_ooc ...`(demo 后端吐罐头非 JSON → infra,**这是预期**:demo 只证 CLI 链路通)+ `码=0`。

- [ ] **Step 5: Commit**

```bash
git add evals/judge.py tests/test_eval_judge_structured.py
git commit -m "$(cat <<'EOF'
feat(eval): judge_case 运行器 + infra 三态 + Judge CLI

judge_case:build→complete→parse,后端异常/解析失败→infra_error(verdicts=[]+
[infra],绝不假通过 P0-C);复用 MeteringBackend 记时延。CLI python -m evals.judge
[--case][--backend demo|configured][--out],0=完成/2=infra;demo 只证链路(吐罐头
非 JSON 会 infra,属预期)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Cohen's κ + 每维 P/R/F1 纯函数

**Files:**
- Create: `evals/calibration.py`(本任务只到 metrics 层)
- Test: `tests/test_eval_calibration.py`(新建)

**Interfaces:**
- Produces:
  - `cohen_kappa(a: list, b: list) -> float`:两个等长标签序列的 Cohen's κ;完全一致→1.0;`len` 不等→ValueError;单一类别(pe=1)→1.0 当且仅当完全一致否则 0.0。
  - `PRF`(dataclass:`tp,fp,fn: int`,`precision,recall,f1: float | None`,`as_dict()`);`prf_for_dimension(gold: list[bool], pred: list[bool]) -> PRF`(等长,分母 0 时对应指标 None)。
- Consumes: 无。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_calibration.py`:

```python
"""κ / P·R·F1 纯函数:手算小样本对拍。零真实模型、零外部依赖。"""
import math

import pytest

from evals.calibration import PRF, cohen_kappa, prf_for_dimension


def test_kappa_perfect_agreement():
    assert cohen_kappa([True, False, True], [True, False, True]) == 1.0


def test_kappa_chance_level_near_zero():
    # 对角与反对角各半,po=0.5;两方各 50% 正例 → pe=0.5 → κ=0
    a = [True, True, False, False]
    b = [True, False, True, False]
    assert abs(cohen_kappa(a, b) - 0.0) < 1e-9


def test_kappa_known_value():
    # 教科书例:po=0.7, pe=0.5 → κ=(0.7-0.5)/(1-0.5)=0.4
    a = [True]*5 + [False]*5
    b = [True]*3 + [False]*2 + [True]*2 + [False]*3   # a∩b 一致 7/10
    assert abs(cohen_kappa(a, b) - 0.4) < 1e-9


def test_kappa_length_mismatch_raises():
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False])


def test_kappa_single_category_all_false():
    assert cohen_kappa([False, False], [False, False]) == 1.0   # 都判 absent 且一致


def test_prf_perfect():
    p = prf_for_dimension([True, False, True], [True, False, True])
    assert p.tp == 2 and p.fp == 0 and p.fn == 0
    assert p.precision == 1.0 and p.recall == 1.0 and p.f1 == 1.0


def test_prf_with_errors():
    # gold: 1,1,0 ; pred: 1,0,1 → tp=1 fp=1 fn=1 → P=R=0.5 F1=0.5
    p = prf_for_dimension([True, True, False], [True, False, True])
    assert (p.tp, p.fp, p.fn) == (1, 1, 1)
    assert p.precision == 0.5 and p.recall == 0.5 and p.f1 == 0.5


def test_prf_no_predictions_precision_none():
    # 无任何 pred 正例 → precision 未定义(None),recall=0
    p = prf_for_dimension([True, False], [False, False])
    assert p.tp == 0 and p.precision is None and p.recall == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'evals.calibration'`。

- [ ] **Step 3: 实现**

新建 `evals/calibration.py`:

```python
"""校准 meta-eval 纯函数:Cohen's κ + 每维 P/R/F1。零依赖手写(不引 sklearn)。

只算一致性/查全查准,不产任何「总体分」。11 例数据集每维正例仅 1-2 个,总体准确率
会被大量 absent 格灌水,故用 κ(扣偶然一致)+ 分维 recall(高代价维单独看)。
"""

from __future__ import annotations

from dataclasses import dataclass


def cohen_kappa(a: list, b: list) -> float:
    """两个等长标签序列的 Cohen's κ。完全一致→1.0;单一类别且一致→1.0。"""
    if len(a) != len(b):
        raise ValueError(f"κ 两序列须等长:{len(a)} != {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("κ 空序列无定义")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe >= 1.0:                       # 单一类别:两方都恒判同一类
        return 1.0 if po == 1.0 else 0.0
    return round((po - pe) / (1 - pe), 4)


@dataclass
class PRF:
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None

    def as_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": self.precision, "recall": self.recall, "f1": self.f1}


def prf_for_dimension(gold: list[bool], pred: list[bool]) -> PRF:
    """单维度跨 case 的 P/R/F1。分母为 0 的指标记 None(未定义,不伪造 0/1)。"""
    if len(gold) != len(pred):
        raise ValueError(f"P/R/F1 两序列须等长:{len(gold)} != {len(pred)}")
    tp = sum(1 for g, p in zip(gold, pred) if g and p)
    fp = sum(1 for g, p in zip(gold, pred) if (not g) and p)
    fn = sum(1 for g, p in zip(gold, pred) if g and (not p))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    precision = round(precision, 4) if precision is not None else None
    recall = round(recall, 4) if recall is not None else None
    return PRF(tp, fp, fn, precision, recall, f1)
```

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -q`
Expected: 8 passed。

- [ ] **Step 5: Commit**

```bash
git add evals/calibration.py tests/test_eval_calibration.py
git commit -m "$(cat <<'EOF'
feat(eval): Cohen's κ + 每维 P/R/F1 纯函数(手写零依赖)

cohen_kappa 扣偶然一致(单一类别/等长守卫);prf_for_dimension 分母为 0 的指标记
None 不伪造。手算小样本对拍(κ=0.4 教科书例/P=R=0.5)。只算一致性查全查准,不产
总体分——为 Judge-金标校准铺路。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 预注册阈值 targets.json + 达标比较器

**Files:**
- Create: `evals/calibration/targets.json`
- Modify: `evals/calibration.py`(load_targets + evaluate_against_targets)
- Test: `tests/test_eval_calibration.py`(扩)

**Interfaces:**
- Consumes: Task 4。
- Produces:
  - `evals/calibration/targets.json`:预注册阈值 + `preregistered/note`(注明待验收标准非事实)。
  - `load_targets() -> dict`;`evaluate_against_targets(metric_value: float | None, target: float) -> dict`(返回 `{target, value, met}`;value=None→met=None「无数据」)。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_calibration.py` 追加(顶部补 `from evals.calibration import load_targets, evaluate_against_targets`):

```python
def test_targets_preregistered_values():
    t = load_targets()
    assert t["kappa_human_human"] == 0.70
    assert t["kappa_judge_gold"] == 0.60
    assert t["high_cost_recall"] == 0.85
    assert isinstance(t["high_cost_dimensions"], list) and t["high_cost_dimensions"]
    assert "待验收标准" in t["note"] or "非当前事实" in t["note"]   # 诚实性:不冒充结果


def test_evaluate_meets_target():
    r = evaluate_against_targets(0.72, 0.70)
    assert r["met"] is True and r["value"] == 0.72 and r["target"] == 0.70


def test_evaluate_below_target():
    assert evaluate_against_targets(0.55, 0.60)["met"] is False


def test_evaluate_no_data_is_none_not_fail():
    r = evaluate_against_targets(None, 0.70)
    assert r["met"] is None       # 无数据 ≠ 未达标,是「待测」
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -v -k "target"`
Expected: FAIL——`cannot import name 'load_targets'`。

- [ ] **Step 3: 实现**

新建 `evals/calibration/targets.json`:

```json
{
  "preregistered": "2026-07-17",
  "note": "以下为待验收标准,非当前事实。先于任何真实校准结果提交进版本库,用 git 历史证明未看完分数倒推阈值(spec §Phase3)。达标才可将对应维度晋级为硬门禁(Phase 4)。",
  "kappa_human_human": 0.70,
  "kappa_judge_gold": 0.60,
  "high_cost_recall": 0.85,
  "high_cost_dimensions": ["信息边界", "设定漂移"]
}
```

`evals/calibration.py` 顶部补 `import json` + `from pathlib import Path`,追加:

```python
TARGETS_PATH = Path(__file__).resolve().parent / "calibration" / "targets.json"


def load_targets() -> dict:
    return json.loads(TARGETS_PATH.read_text(encoding="utf-8"))


def evaluate_against_targets(metric_value: float | None, target: float) -> dict:
    """指标 vs 预注册阈值的纯比较。value=None(无数据)→ met=None(待测,非未达标)。"""
    met = None if metric_value is None else (metric_value >= target)
    return {"target": target, "value": metric_value, "met": met}
```

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -q`
Expected: 12 passed。

- [ ] **Step 5: Commit**

```bash
git add evals/calibration/targets.json evals/calibration.py tests/test_eval_calibration.py
git commit -m "$(cat <<'EOF'
feat(eval): 预注册校准阈值 targets.json + 达标比较器

κ人人≥0.70/κJudge≥0.60/高代价维 recall≥0.85 先提交进库(git 历史=没事后倒推阈值),
note 明注「待验收标准非事实」。evaluate_against_targets:无数据→met=None(待测,不
当未达标)。达标才晋级硬门禁留给 Phase 4。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 校准报告生成器(JSON + MD,诚实留空位)

**Files:**
- Modify: `evals/calibration.py`(build_calibration_report + reshape 辅助 + write_report)
- Test: `tests/test_eval_calibration.py`(扩)

**Interfaces:**
- Consumes: Task 4/5、`evals.judge.JudgeResult`、`evals.dataset.DIMENSIONS`/`load_case`。
- Produces:
  - `present_matrix(cases_labels: list[dict]) -> dict[str, list[bool]]`:把「每 case 的金标 labels」重塑成 `{dimension: [present per case]}`。
  - `verdict_matrix(judge_results: list[JudgeResult]) -> dict[str, list[bool]]`:同形状,来自 Judge verdicts(仅非 infra 的 case)。
  - `build_calibration_report(gold: dict, judge: dict | None, human_pairs: list | None) -> dict`:算 Judge-金标每维 P/R/F1 + κ;human 标注为空→人-人 κ 记 `待标注 N=0`;judge 为空→Judge 段记 `待真机`。
  - `write_report(report: dict, out_dir: Path) -> tuple[Path, Path]`:写 `report.json` + `report.md`。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_calibration.py` 追加(顶部补相应 import + `from evals.dataset import DIMENSIONS`):

```python
def _gold_two_cases():
    # 两个 case 的金标:case1 只 AI腔命中;case2 只 设定漂移命中
    return {d: [d == "AI腔", d == "设定漂移"] for d in DIMENSIONS}


def test_present_matrix_shape():
    from evals.calibration import present_matrix
    labels_c1 = [{"dimension": d, "present": (d == "AI腔")} for d in DIMENSIONS]
    labels_c2 = [{"dimension": d, "present": (d == "设定漂移")} for d in DIMENSIONS]
    m = present_matrix([{"labels": labels_c1}, {"labels": labels_c2}])
    assert m["AI腔"] == [True, False] and m["设定漂移"] == [False, True]


def test_report_judge_vs_gold_perfect():
    from evals.calibration import build_calibration_report
    gold = _gold_two_cases()
    judge = _gold_two_cases()                     # Judge 与金标完全一致
    rep = build_calibration_report(gold, judge, human_pairs=None)
    assert rep["judge_vs_gold"]["AI腔"]["f1"] == 1.0
    assert rep["judge_vs_gold"]["设定漂移"]["recall"] == 1.0


def test_report_human_kappa_is_pending_when_no_annotations():
    from evals.calibration import build_calibration_report
    rep = build_calibration_report(_gold_two_cases(), None, human_pairs=None)
    assert rep["human_human_kappa"]["status"] == "待标注"      # 不造数
    assert rep["human_human_kappa"]["n"] == 0
    assert rep["judge_vs_gold_status"] == "待真机"              # 无 judge 数据


def test_write_report_emits_json_and_md(tmp_path):
    from evals.calibration import build_calibration_report, write_report
    rep = build_calibration_report(_gold_two_cases(), _gold_two_cases(), None)
    j, m = write_report(rep, tmp_path)
    assert j.is_file() and m.is_file()
    import json as _j
    assert _j.loads(j.read_text(encoding="utf-8"))["judge_vs_gold"]["AI腔"]["f1"] == 1.0
    assert "待标注" in m.read_text(encoding="utf-8")            # MD 也如实标空位
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -v -k "matrix or report"`
Expected: FAIL——`cannot import name 'present_matrix'`。

- [ ] **Step 3: 实现**

`evals/calibration.py` 追加:

```python
from .dataset import DIMENSIONS   # 顶部 import 区


def present_matrix(cases_labels: list[dict]) -> dict:
    """[{labels:[{dimension,present}...]}...] → {dimension: [present per case]}。"""
    out = {d: [] for d in DIMENSIONS}
    for case in cases_labels:
        by_dim = {l["dimension"]: bool(l["present"]) for l in case["labels"]}
        for d in DIMENSIONS:
            out[d].append(by_dim.get(d, False))
    return out


def verdict_matrix(judge_results: list) -> dict:
    """[JudgeResult(非 infra)] → {dimension: [present per case]}。infra 的 case 需调用方先滤掉。"""
    out = {d: [] for d in DIMENSIONS}
    for r in judge_results:
        by_dim = {v.dimension: v.present for v in r.verdicts}
        for d in DIMENSIONS:
            out[d].append(by_dim.get(d, False))
    return out


def build_calibration_report(gold: dict, judge: dict | None, human_pairs: list | None) -> dict:
    """校准报告。judge/human 缺 → 对应段如实留空位(待真机/待标注),绝不造数。"""
    report: dict = {
        "dimensions": list(DIMENSIONS),
        "targets": load_targets(),
        "judge_vs_gold": {},
        "judge_vs_gold_status": "待真机" if not judge else "已计算",
        "human_human_kappa": {"status": "待标注", "n": 0, "value": None,
                              "note": "人-人一致性需两名标注者对 calibration split 独立标注后计算"},
    }
    if judge:
        for d in DIMENSIONS:
            report["judge_vs_gold"][d] = prf_for_dimension(gold[d], judge[d]).as_dict()
        flat_gold = [x for d in DIMENSIONS for x in gold[d]]
        flat_judge = [x for d in DIMENSIONS for x in judge[d]]
        report["judge_vs_gold_kappa"] = cohen_kappa(flat_gold, flat_judge)
    if human_pairs:
        a = [x for pair in human_pairs for x in pair[0]]
        b = [x for pair in human_pairs for x in pair[1]]
        report["human_human_kappa"] = {"status": "已计算", "n": len(a),
                                       "value": cohen_kappa(a, b), "note": ""}
    return report


def _md_report(report: dict) -> str:
    lines = ["# LLM-Judge 校准报告", "",
             f"预注册阈值:{report['targets']['note']}", "",
             "## 人-人一致性",
             f"- 状态:{report['human_human_kappa']['status']}(N={report['human_human_kappa']['n']})",
             f"- κ:{report['human_human_kappa']['value']}", "",
             f"## Judge vs 金标(状态:{report['judge_vs_gold_status']})", ""]
    if report["judge_vs_gold"]:
        lines.append("| 维度 | tp | fp | fn | precision | recall | f1 |")
        lines.append("|---|---|---|---|---|---|---|")
        for d in report["dimensions"]:
            m = report["judge_vs_gold"][d]
            lines.append(f"| {d} | {m['tp']} | {m['fp']} | {m['fn']} | "
                         f"{m['precision']} | {m['recall']} | {m['f1']} |")
        lines.append("")
        lines.append(f"整体 Judge-金标 κ:{report.get('judge_vs_gold_kappa')}")
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "report.json"
    m = out_dir / "report.md"
    j.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    m.write_text(_md_report(report), encoding="utf-8")
    return j, m
```

- [ ] **Step 4: 跑测试通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_calibration.py -q` → 全绿。
Run: `.venv/bin/python -m pytest -q` → 全绿。

- [ ] **Step 5: Commit**

```bash
git add evals/calibration.py tests/test_eval_calibration.py
git commit -m "$(cat <<'EOF'
feat(eval): 校准报告生成器——Judge-金标每维P/R/F1+κ,人-人诚实留空位

present_matrix/verdict_matrix 重塑标签为每维序列;build_calibration_report 算
Judge-金标 P/R/F1+κ,human 标注为空→人-人 κ 记「待标注 N=0」、judge 空→「待真机」,
绝不造数。JSON+MD 双格式(MD 也如实标空位)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 无剧透标注包导出 + dimension 类型防御 + 三挂账修补 + 终审验收

**Files:**
- Create: `evals/export_packets.py`
- Modify: `evals/dataset.py`(dimension 类型防御一处)、`evals/dataset/ANNOTATION_GUIDE.md`(jq 命令 backlog)、`evals/README.md`(Phase 3 节)
- Test: `tests/test_eval_export_packets.py`(新建)

**Interfaces:**
- Consumes: `evals.dataset.discover_cases`/`load_case`。
- Produces:
  - `export_packet(case_dir: Path, out_dir: Path) -> Path`:只写 `context.json`(四键)+ `chapter.md`,**零剧透字段**(无 labels/construction_note/detector_note/severity/annotator)。
  - `main(argv) -> int`:批量导出到目标目录。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_export_packets.py`:

```python
"""标注包导出:结构上杜绝金标剧透(T6 审查发现)。"""
import json

from evals.dataset import discover_cases
from evals.export_packets import export_packet

_SPOILER = ("labels", "construction_note", "detector_note", "present", "severity", "annotator")


def test_export_packet_has_only_context_and_chapter(tmp_path):
    case_dir = discover_cases()[0]        # 用真实数据集第一个 case
    out = export_packet(case_dir, tmp_path)
    files = sorted(p.name for p in out.iterdir())
    assert files == ["chapter.md", "context.json"]
    ctx = json.loads((out / "context.json").read_text(encoding="utf-8"))
    assert set(ctx.keys()) == {"setting", "characters", "prev_hook", "chapter_goal"}


def test_export_packet_no_spoiler_anywhere(tmp_path):
    # 对所有 case 导出,逐字节扫描无任何剧透字段名
    for case_dir in discover_cases():
        out = export_packet(case_dir, tmp_path / case_dir.name)
        blob = (out / "context.json").read_text(encoding="utf-8")
        for word in _SPOILER:
            assert word not in blob, f"{case_dir.name} 导出包泄露字段 {word}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_export_packets.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'evals.export_packets'`。

- [ ] **Step 3: 实现三件**

(a) 新建 `evals/export_packets.py`:

```python
"""无剧透标注包导出:给第二标注者只吐 context 四键 + chapter,结构上杜绝金标泄露。

case.json 里 labels/construction_note/detector_note 是金标剧透(T6 审查发现);靠标注者
自律「别看」不如给的包里根本没有。这是把 ANNOTATION_GUIDE 的「最稳做法」工具化。
"""

from __future__ import annotations

import json
from pathlib import Path

from .dataset import load_case

_CTX_KEYS = ("setting", "characters", "prev_hook", "chapter_goal")


def export_packet(case_dir: Path, out_dir: Path) -> Path:
    """导出一个 case 的无剧透标注包:context.json(四键)+ chapter.md。返回导出目录。"""
    case = load_case(case_dir)          # load_case 已校验;拿到 context+chapter
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = {k: case["context"][k] for k in _CTX_KEYS}
    (out_dir / "context.json").write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "chapter.md").write_text(case["chapter"], encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .dataset import discover_cases

    ap = argparse.ArgumentParser(description="导出无剧透标注包(给第二标注者)")
    ap.add_argument("--out", type=Path, required=True, help="导出根目录")
    ap.add_argument("--split", help="只导某 split(dev/calibration/holdout);缺省全部")
    args = ap.parse_args(argv)

    n = 0
    for case_dir in discover_cases():
        case = load_case(case_dir)
        if args.split and case.get("split") != args.split:
            continue
        export_packet(case_dir, args.out / case_dir.name)
        n += 1
    print(f"✓ 导出 {n} 个无剧透标注包 → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

(b) `evals/dataset.py` 的 dimension 类型防御(P2.T1 残留):在 `dims = [l.get("dimension") for l in labels]` 之后、`sorted(dims)` 之前插入类型守卫。把:

```python
    dims = [l.get("dimension") for l in labels]
    if sorted(dims) != sorted(DIMENSIONS):
```

改为:

```python
    dims = [l.get("dimension") for l in labels]
    if not all(isinstance(d, str) for d in dims):
        _fail(cid, f"labels 每项 dimension 须为字符串,现为:{dims}")
    if sorted(dims) != sorted(DIMENSIONS):
```

(c) `evals/dataset/ANNOTATION_GUIDE.md` 的 jq/导出 backlog 修补(T6 复审 Minor b):找到导出命令示例段,①jq 版补 `mkdir -p` 前置;②补一句「chapter.md 需一并拷贝:`cp <case>/chapter.md <out>/`」;③指明现在有 `python -m evals.export_packets --out <dir>` 一键导出全部无剧透包(替代手写 jq)。**只增不删,别动其它段落。**

(d) `evals/README.md` 追加 Phase 3 节:结构化 Judge(`python -m evals.judge`)、校准 meta-eval(κ/PRF/targets.json 预注册)、标注包导出(`python -m evals.export_packets`)、诚实边界(真实 κ 待真人标注 + 真机 Judge,报告留空位)。

- [ ] **Step 4: 跑测试通过 + dimension 防御回归 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_export_packets.py tests/test_eval_dataset.py -q`
Expected: 全绿(dimension 守卫不破既有 21 条)。
补一条 dimension 防御的失败样本快速验证(实现者临时跑,不留):
Run: `.venv/bin/python -c "from evals.dataset import validate_case; validate_case({'id':'x','split':'dev','version':1,'source':{'origin':'t'},'context':{'setting':'s','characters':'c','prev_hook':'p','chapter_goal':'g'},'labels':[{'dimension':123}]}, 'ch')"`
Expected: `DatasetError: x: labels 每项 dimension 须为字符串`(不是裸 TypeError)。
Run: `.venv/bin/python -m pytest -q`
Expected: 全绿(618 基线 + Phase 3 新增,预计 ~660)。

- [ ] **Step 5: Commit**

```bash
git add evals/export_packets.py evals/dataset.py evals/dataset/ANNOTATION_GUIDE.md evals/README.md tests/test_eval_export_packets.py
git commit -m "$(cat <<'EOF'
feat(eval): 无剧透标注包导出 + dimension 类型防御 + Phase3 文档/backlog 收口

export_packets:只吐 context 四键+chapter,结构上杜绝金标泄露(T6 审查工具化);
dataset dimension 非 str 从裸 TypeError 改 DatasetError(P2.T1 残留);ANNOTATION_GUIDE
补 mkdir/chapter 拷贝/一键导出;README 补 Phase3 节(Judge/校准/诚实边界)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 控制者终审验收(无代码改动)

**Files:** 无;只验证。

- [ ] **Step 1: 全量 + 三 suite 自跑**

Run: `.venv/bin/python -m pytest -q` → 全绿。
Run: `.venv/bin/python -m evals.run_eval --gate; echo $?` → 0(Fixture suite 无恙)。
Run: `.venv/bin/python -m evals.judge --case ds_01_ooc --backend demo; echo $?` → `⚠infra`(demo 非 JSON,预期)+ 0。
Run: `.venv/bin/python -m evals.export_packets --out /tmp/loom_packets_check; echo $?` → 导出 11 包 + 0;抽查一个包只有 context.json+chapter.md、无剧透。

- [ ] **Step 2: 诚实性抽查(spec §5 红线)**

- `targets.json` 里阈值有 `note` 明注「待验收标准非事实」。
- 用合成数据跑一次报告生成(实现者临时脚本):human_pairs=None → `report.md` 含「待标注 N=0」;judge=None → 「待真机」。**确认没有任何地方把 0.70/0.60/0.85 当成已实现结果打印。**
- Judge 后端失败/解析失败路径返回 infra(不假通过),单测已覆盖。

- [ ] **Step 3: 产品红线抽查(ADR-0002/0006)**

- `git diff main..HEAD -- loom/` 只有 `loom/evalapi.py`(且只加再导出,若 Task 2 未改则 evalapi 零改动);`gates.py`/`parse.py` 零改动。
- `evals/judge.py`/`calibration.py` 全文无数值 score 字段(severity 只类别)。
- `grep -rn "import.*calibration\|import.*evals.judge" loom/` → 零命中(校准从不进产品)。

- [ ] **Step 4: 汇报 + 更新 ledger**

向用户报:Phase 3 新增测试计数、三 suite 自跑、诚实空位证据、产品红线抽查结果;真机 Judge 校准命令(`python -m evals.judge --case <id> --backend configured --out <path>` 后手工把 verdicts 喂 calibration)已备好,等用户择时/授权跑真数。不合并——等验收。

---

## Phase 4 预告(另立计划)

分层 CI(PR=fixture 零 key;`eval-real.yml` 走 workflow_dispatch+schedule 跑 generation+真 Judge,repo secret 取 key,fork 不暴露)+ `evals/report.py` 三源 JSON/MD 报告 + artifact 上传 + `gating.json`(维度→observe/soft/hard,初始全 observe,校准达标才晋级)。前置:Phase 3 校准链就绪。
