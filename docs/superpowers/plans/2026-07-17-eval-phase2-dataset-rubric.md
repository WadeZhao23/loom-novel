# Eval Phase 2:评测集 schema + rubric + 小型平衡数据集 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 为 LLM-Judge 校准(Phase 3)建地基:8 个 Judge 维度的操作化 rubric、机器可校验的标注 schema、小而平衡的 v1 数据集(构造性金标:每例注入已知缺陷,证据可机械核验)、dev/calibration/holdout 三分、第二人工标注者的完整工具与工作表。**真实的人-人一致性数字等真标注,本 Phase 只建工具与数据,不伪造任何标注结果。**

**Architecture:** 新增 `evals/dataset.py`(维度常量单一来源 + 载入/校验器)与 `evals/dataset/` 数据目录(rubric.md / cases/<id>/{case.json,chapter.md} / ANNOTATION_GUIDE.md / annotations/ 空白工作表)。校验器强制:维度全覆盖(每例 8 维齐全标注)、evidence 按类型机械核验(chapter=正文子串 / context=上下文子串 / absence=免引注但必须写 note)、split 合法。与 Fixture suite(evals/cases)、Generation suite(evals/gen_cases)三分并立,互不引用。

**Tech Stack:** Python 3.11 + pytest(现基线 580 绿)。零新依赖、零模型调用(纯数据+校验)。

**权威 spec:** `/Users/chambers/Desktop/loom-novel_eval补齐计划.md` §Phase 2 + 侦察档案 `.superpowers/sdd/recon-p14/judge.md`(维度名逐字取自 CRITIC prompt 原文)。

## Global Constraints

- **文件白名单**:新建 `evals/dataset.py`、`evals/dataset/**`(rubric.md、cases/、ANNOTATION_GUIDE.md、annotations/)、`tests/test_eval_dataset.py`;修改 `evals/README.md`(只加一节)。**loom/ 零改动(含 evalapi——本 Phase 不需要新接缝);不碰 evals/{cases,gen_cases,harness.py,graders.py,run_eval.py,generate.py,metering.py,baseline.json};不碰 .github/**。
- **维度名单一来源**:`evals/dataset.py` 的 `DIMENSIONS` 元组是 8 个维度键的唯一权威,rubric.md/所有 case 标注/后续 Phase 3 都以它为准。维度键(逐字,源自 CRITIC prompt):`人物OOC`、`设定漂移`、`断钩子`、`无爽点`、`信息边界`、`物品状态连续性`、`时间连续性`、`AI腔`。
- **金标诚实性**:所有 v1 case 的 `annotator` 必须写 `"构造注入(gold-by-construction)"`——这是「缺陷是造进去的所以标签为真」,**不是**人工标注共识;人-人一致性、Judge-人一致性都要等真人标注(Phase 3 计算,数字现在不存在,不许编)。数据集全部自造(`source.origin: "constructed"`),不含任何用户内容,无脱敏问题。
- **不打分红线延续**(ADR-0002/0006):标注 schema 用 `present: bool` + `severity: 高|中|低`,**没有任何数值分数字段**;rubric 不写「总体文学分」。
- 每个 case 的 `labels` 必须**恰好 8 条、维度不重不漏**(每维度显式 present true/false)——这是 Phase 3 算每维度混淆矩阵的前提。
- 既有测试断言禁改。零模型调用。提交信息 `type(scope): 中文摘要` + `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **并发提交纪律**:同分支有另一会话在提交。add+commit 必须单条 bash 原子执行且 commit 带 pathspec(`git add F... && git commit -m msg -- F...`),提交后 `git show --stat HEAD` 验证只含本任务文件。
- 环境 `.venv/bin/python`;测试 `.venv/bin/python -m pytest`。

## 现状锚点(侦察核实,别猜)

- CRITIC_质检 七维度原文在 `loom/gates.py:129-160`(①人物OOC ②设定漂移 ③断钩子 ④整章无爽点 ⑤信息边界(双向:知道不在场之事 / 越境认知无归因)⑥物品/状态连续性 ⑦时间连续性);质检明确**不挑** AI 腔——AI腔是独立的 CRITIC_去AI味(套话头尾/空洞万能词/过度连接词/直接点名情绪/黑名单词/句式过整齐,护栏:指纹特征豁免)。
- `Issue(kind, desc, evidence)`(gates.py:28-36),`as_dict()` 中文键——Phase 3 对齐时的参照,本 Phase 不消费。
- 现有三套数据互不相干:`evals/cases`(Fixture,grader 自测)、`evals/gen_cases`(Generation,固定输入)、本 Phase 新增 `evals/dataset`(Judge 校准标注集)。

---

### Task 1: `evals/dataset.py` — 维度常量 + 载入/校验器

**Files:**
- Create: `evals/dataset.py`
- Test: `tests/test_eval_dataset.py`(新建)

**Interfaces:**
- Produces:
  - `DIMENSIONS: tuple[str, ...]`(8 键,上文逐字)、`SPLITS = ("dev", "calibration", "holdout")`、`SEVERITIES = ("高", "中", "低")`、`EVIDENCE_TYPES = ("chapter", "context", "absence")`。
  - `load_case(case_dir: Path) -> dict`(读 case.json + chapter.md,校验失败抛 `DatasetError(ValueError)`,错误信息含 case id 与原因)。
  - `discover_cases(dataset_dir: Path) -> list[Path]`(cases/ 下含 case.json 的目录,排序)。
  - `validate_case(case: dict, chapter: str) -> None`(供 load_case 内部与测试直调)。
- Consumes: 无。

校验规则(全部硬性):
1. 必填:`id`(=目录名)、`split`∈SPLITS、`version`(int≥1)、`source`(dict 含 `origin`)、`context`(dict 含 `setting/characters/prev_hook/chapter_goal` 四键,均非空 str)、`labels`(list)。
2. `labels` 恰 8 条;`dimension` 集合 == set(DIMENSIONS)(不重不漏)。
3. 每条 label:`present: bool`、`annotator: str` 非空;present=True 时必有 `severity`∈SEVERITIES、`evidence_type`∈EVIDENCE_TYPES、`note` 非空,且:evidence_type=="chapter" → `evidence` 非空且是 chapter 的子串;=="context" → `evidence` 非空且是 `"\n".join(context.values())` 的子串;=="absence" → `evidence` 必须为空串(缺失型缺陷引不出原文,note 里说清缺了什么)。present=False 时不得有 severity/evidence(干净维度不携带缺陷字段)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_dataset.py`:

```python
"""Judge 校准数据集:schema 校验器。纯数据,零模型。"""
import json
from pathlib import Path

import pytest

from evals.dataset import (
    DIMENSIONS,
    DatasetError,
    SPLITS,
    discover_cases,
    load_case,
)


def _blank_labels(**overrides):
    """8 维全 present=False 的合法标注;overrides 按维度名替换单条。"""
    labels = [{"dimension": d, "present": False,
               "annotator": "构造注入(gold-by-construction)"} for d in DIMENSIONS]
    for dim, patch in overrides.items():
        for l in labels:
            if l["dimension"] == dim:
                l.update(patch)
    return labels


def _write_case(tmp_path, *, labels=None, split="dev", chapter="矿灯昏黄,沈砚验伤。他把旧矿牌收进怀里。"):
    d = tmp_path / "ds_x"; d.mkdir()
    case = {
        "id": "ds_x", "split": split, "version": 1,
        "source": {"origin": "constructed", "license": "self-authored", "deidentified": True},
        "context": {"setting": "灵气复苏,逆息体质忌讳外泄。", "characters": "沈砚:寡言,谋定后动。",
                    "prev_hook": "上一章末:矿道尽头传来提灯脚步声。", "chapter_goal": "接钩+验伤+埋矿牌线。"},
        "labels": labels if labels is not None else _blank_labels(),
    }
    (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "chapter.md").write_text(chapter, encoding="utf-8")
    return d


def test_dimensions_are_the_eight_judge_dims():
    assert DIMENSIONS == ("人物OOC", "设定漂移", "断钩子", "无爽点",
                          "信息边界", "物品状态连续性", "时间连续性", "AI腔")
    assert SPLITS == ("dev", "calibration", "holdout")


def test_clean_case_loads(tmp_path):
    case = load_case(_write_case(tmp_path))
    assert case["id"] == "ds_x" and len(case["labels"]) == 8


def test_missing_dimension_rejected(tmp_path):
    labels = _blank_labels()[:-1]                      # 只 7 条 → 维度不全
    with pytest.raises(DatasetError, match="维度"):
        load_case(_write_case(tmp_path, labels=labels))


def test_chapter_evidence_must_be_substring(tmp_path):
    labels = _blank_labels(设定漂移={"present": True, "severity": "高",
                                    "evidence_type": "chapter", "evidence": "正文里根本没有这句",
                                    "note": "注入:境界名写错"})
    with pytest.raises(DatasetError, match="子串"):
        load_case(_write_case(tmp_path, labels=labels))


def test_absence_evidence_must_be_empty(tmp_path):
    labels = _blank_labels(断钩子={"present": True, "severity": "高",
                                  "evidence_type": "absence", "evidence": "不该有引文",
                                  "note": "注入:通章不接提灯脚步声的钩"})
    with pytest.raises(DatasetError, match="absence"):
        load_case(_write_case(tmp_path, labels=labels))


def test_valid_positive_case_loads(tmp_path):
    labels = _blank_labels(设定漂移={"present": True, "severity": "高",
                                    "evidence_type": "chapter", "evidence": "旧矿牌",
                                    "note": "示例:以子串核验通过为准"})
    case = load_case(_write_case(tmp_path, labels=labels))
    hit = [l for l in case["labels"] if l["present"]]
    assert len(hit) == 1 and hit[0]["dimension"] == "设定漂移"


def test_bad_split_rejected(tmp_path):
    with pytest.raises(DatasetError, match="split"):
        load_case(_write_case(tmp_path, split="test"))


def test_clean_label_must_not_carry_severity(tmp_path):
    labels = _blank_labels(时间连续性={"present": False, "severity": "低",
                                      "annotator": "构造注入(gold-by-construction)"})
    with pytest.raises(DatasetError, match="present=False"):
        load_case(_write_case(tmp_path, labels=labels))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_dataset.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'evals.dataset'`。

- [ ] **Step 3: 实现**

新建 `evals/dataset.py`:

```python
"""Judge 校准数据集层:维度常量单一来源 + 标注 case 的载入/校验。

三套数据的第三套(与 evals/cases Fixture、evals/gen_cases Generation 并立):
每例 = case.json(上下文 + 8 维显式标注)+ chapter.md(含注入缺陷的正文)。
金标是**构造性**的(缺陷是造进去的,标签因此为真)——不是人工标注共识;
人-人/Judge-人一致性要等真人标注(Phase 3),数字在那之前不存在。

evidence 机械核验:chapter 型必须是正文子串、context 型必须是上下文子串、
absence 型(断钩子/无爽点这类「缺了东西」)不许有引文、note 里说清缺了什么。
无任何数值分数字段(ADR-0002/0006:不打分)。
"""

from __future__ import annotations

import json
from pathlib import Path

DIMENSIONS: tuple[str, ...] = ("人物OOC", "设定漂移", "断钩子", "无爽点",
                               "信息边界", "物品状态连续性", "时间连续性", "AI腔")
SPLITS = ("dev", "calibration", "holdout")
SEVERITIES = ("高", "中", "低")
EVIDENCE_TYPES = ("chapter", "context", "absence")

HERE = Path(__file__).resolve().parent
DATASET_DIR = HERE / "dataset"
CASES_DIR = DATASET_DIR / "cases"


class DatasetError(ValueError):
    pass


def discover_cases(dataset_dir: Path | None = None) -> list[Path]:
    root = (dataset_dir or DATASET_DIR) / "cases" if dataset_dir else CASES_DIR
    if not root.is_dir():
        return []
    return sorted(p.parent for p in root.glob("*/case.json"))


def load_case(case_dir: Path) -> dict:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    chapter = (case_dir / "chapter.md").read_text(encoding="utf-8")
    validate_case(case, chapter)
    if case["id"] != case_dir.name:
        raise DatasetError(f"{case_dir.name}: id 与目录名不符({case['id']})")
    case["chapter"] = chapter
    return case


def _fail(cid: str, msg: str) -> None:
    raise DatasetError(f"{cid}: {msg}")


def validate_case(case: dict, chapter: str) -> None:
    cid = case.get("id", "<无id>")
    if case.get("split") not in SPLITS:
        _fail(cid, f"split 非法:{case.get('split')}(须 {SPLITS} 之一)")
    if not isinstance(case.get("version"), int) or case["version"] < 1:
        _fail(cid, "version 须为 ≥1 的整数")
    if not isinstance(case.get("source"), dict) or not case["source"].get("origin"):
        _fail(cid, "source.origin 必填")
    ctx = case.get("context")
    if not isinstance(ctx, dict):
        _fail(cid, "context 必填")
    for key in ("setting", "characters", "prev_hook", "chapter_goal"):
        if not isinstance(ctx.get(key), str) or not ctx[key].strip():
            _fail(cid, f"context.{key} 必填非空")
    labels = case.get("labels")
    if not isinstance(labels, list):
        _fail(cid, "labels 必填")
    dims = [l.get("dimension") for l in labels]
    if sorted(dims) != sorted(DIMENSIONS):
        _fail(cid, f"labels 维度必须恰好覆盖 8 维不重不漏,现为:{dims}")
    ctx_blob = "\n".join(ctx.values())
    for l in labels:
        dim = l["dimension"]
        if not isinstance(l.get("present"), bool):
            _fail(cid, f"{dim}: present 须为 bool")
        if not l.get("annotator", "").strip():
            _fail(cid, f"{dim}: annotator 必填")
        if l["present"]:
            if l.get("severity") not in SEVERITIES:
                _fail(cid, f"{dim}: severity 须为 {SEVERITIES} 之一")
            et = l.get("evidence_type")
            if et not in EVIDENCE_TYPES:
                _fail(cid, f"{dim}: evidence_type 须为 {EVIDENCE_TYPES} 之一")
            if not l.get("note", "").strip():
                _fail(cid, f"{dim}: present=True 必须写 note(注入了什么)")
            ev = l.get("evidence", "")
            if et == "chapter" and (not ev or ev not in chapter):
                _fail(cid, f"{dim}: chapter 型 evidence 必须是正文子串,现引文核验失败")
            if et == "context" and (not ev or ev not in ctx_blob):
                _fail(cid, f"{dim}: context 型 evidence 必须是上下文子串")
            if et == "absence" and ev:
                _fail(cid, f"{dim}: absence 型不许携带引文(缺失型缺陷引不出原文)")
        else:
            if any(k in l for k in ("severity", "evidence", "evidence_type")):
                _fail(cid, f"{dim}: present=False 不得携带 severity/evidence 字段")
```

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_dataset.py -q`
Expected: 8 passed。全量 `-q` → 588。

- [ ] **Step 5: Commit(原子 + pathspec)**

```bash
git add evals/dataset.py tests/test_eval_dataset.py && git commit -m "$(cat <<'EOF'
feat(eval): Judge 校准数据集层——8维常量单一来源+构造性金标校验器

DIMENSIONS 逐字取自 CRITIC prompt(质检7维+AI腔);每例 8 维显式标注不重不漏;
evidence 机械核验(chapter=正文子串/context=上下文子串/absence=缺失型免引注但必须
note);present=False 不携带缺陷字段;无任何分数字段(ADR-0002/0006)。金标是构造
性的,人-人一致性等真人标注,不造数。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)" -- evals/dataset.py tests/test_eval_dataset.py
```

---

### Task 2: rubric.md 操作化 + 文档-代码一致性测试

**Files:**
- Create: `evals/dataset/rubric.md`
- Test: `tests/test_eval_dataset.py`(扩)

**Interfaces:**
- Consumes: Task 1 `DIMENSIONS`。
- Produces: rubric.md——Phase 3 Judge prompt 与人工标注的共同依据;`## <维度名>` 8 个二级标题与 DIMENSIONS 逐字对齐(测试钉死)。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_dataset.py` 追加:

```python
def test_rubric_covers_every_dimension_verbatim():
    # rubric.md 的 8 个「## 维度名」标题必须与 DIMENSIONS 逐字一致(文档-代码单一来源)
    rubric = Path("evals/dataset/rubric.md").read_text(encoding="utf-8")
    for dim in DIMENSIONS:
        assert f"## {dim}" in rubric, f"rubric.md 缺维度小节:{dim}"
    for banned in ("总体文学分", "综合评分", "打分"):
        assert banned not in rubric, f"rubric 不许出现「{banned}」(ADR-0002 不打分红线)"


def test_rubric_each_dimension_has_required_parts():
    rubric = Path("evals/dataset/rubric.md").read_text(encoding="utf-8")
    for dim in DIMENSIONS:
        section = rubric.split(f"## {dim}")[1].split("\n## ")[0]
        for part in ("定义", "该抓(正例)", "不该抓(反例)", "边界例", "严重度", "证据要求"):
            assert part in section, f"{dim} 小节缺「{part}」"
```

- [ ] **Step 2: 跑红**

Run: `.venv/bin/python -m pytest tests/test_eval_dataset.py -v -k rubric` → FAIL(文件不存在)。

- [ ] **Step 3: 写 rubric.md**

`evals/dataset/rubric.md`,结构(每维度六小节,内容要求如下;**定义/正反例措辞以 CRITIC prompt 原文为语义基准**——写作时打开 `loom/gates.py:129-160` 对照,禁止发明 prompt 里没有的判据):

```markdown
# Judge 维度操作化 Rubric(v1)

判读单位:一章正文 + 该例 context(setting/characters/prev_hook/chapter_goal)。
Judge 只准判本文件声明的 8 个维度,禁止给「总体文学分」一类的综合评价(ADR-0002)。
每个维度按「定义 → 该抓(正例) → 不该抓(反例) → 边界例 → 严重度 → 证据要求」六节操作化。

## 人物OOC
### 定义
(基于 CRITIC 原文①:违背性格/立场/已知信息/人物硬约束的底线身段…)
### 该抓(正例)
(一个具体可判的抓取示例…)
### 不该抓(反例)
(表面像 OOC 但有合理动机/铺垫的不抓…)
### 边界例
(至少一个「两可」情形 + 判法…)
### 严重度
高=…;中=…;低=…
### 证据要求
chapter 型:引违背处原文短引。
…(其余 7 维同构;断钩子/无爽点的证据要求写明是 absence 型:引不出「缺失」的原文,
证据栏留空、note 里写清上一章钩子是什么/为何判无爽点;AI腔一节必须写指纹豁免护栏。)
```

每维度实写要求(不是占位——实现者按下表逐维写全六节,每节 2-5 句,正反例/边界例必须是**具体情节示例**而非抽象复述):

| 维度 | 定义来源(gates.py 原文锚) | 证据类型 | 边界例要点 |
|---|---|---|---|
| 人物OOC | ①性格/立场/已知信息/硬约束底线 | chapter | 性格突变 vs 有铺垫的成长 |
| 设定漂移 | ②违反世界观/金手指/已埋伏笔 | chapter | 新设定扩写 vs 与已有设定冲突 |
| 断钩子 | ③没接住上一章末钩子 | absence | 延迟接钩(本章埋、下章接)算不算 |
| 无爽点 | ④整章无任何爽点/收获 | absence | 铺垫章的「暗爽」(信息增量)算不算收获 |
| 信息边界 | ⑤双向:知道不在场之事/越境认知无归因 | chapter | 有金手指归因句就不抓(b款) |
| 物品状态连续性 | ⑥已标消耗/失去的物品复现、状态与账本不符 | chapter | 同名不同物(两把同名刀)判法 |
| 时间连续性 | ⑦时间词与前情时刻粒度不符 | chapter | 模糊时间词(「不久前」)宽容度 |
| AI腔 | 去AI味 gate:套话头尾/空洞万能词/过度连接词/直接点名情绪/黑名单词/句式过整齐 | chapter | **指纹豁免**:作者签名句式不算(护栏原文) |

- [ ] **Step 4: 跑绿 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_dataset.py -q` → 全绿(10 条)。

- [ ] **Step 5: Commit(原子 + pathspec)**

```bash
git add evals/dataset/rubric.md tests/test_eval_dataset.py && git commit -m "$(cat <<'EOF'
docs(eval): Judge 8维操作化 rubric——定义/正反例/边界例/严重度/证据要求

语义基准逐字对齐 CRITIC prompt(gates.py:129-160),不发明新判据;断钩子/无爽点
定为 absence 型证据;AI腔写明指纹豁免护栏;全文无打分(测试钉死标题对齐+禁词)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)" -- evals/dataset/rubric.md tests/test_eval_dataset.py
```

---

### Task 3: 数据集 v1 · 前 4 个语义正例(人物OOC/设定漂移/断钩子/无爽点)

**Files:**
- Create: `evals/dataset/cases/ds_01_ooc/{case.json,chapter.md}`、`ds_02_drift/…`、`ds_03_hook/…`、`ds_04_payoff/…`
- Test: `tests/test_eval_dataset.py`(扩:全数据集校验测试,一次写好,后续任务的数据自动被它覆盖)

**Interfaces:**
- Consumes: Task 1 校验器、Task 2 rubric。
- Produces: 4 个 dev/calibration 正例,每例恰 1 维 present=True、其余 7 维 false。

**构造规范(每例都要满足,校验器机械把关)**:
- 章长 300-600 字,网文文风,与 rubric 对应维度的「该抓(正例)」情节一致;缺陷**只注入一处、只命中本维度**(其余 7 维必须干净——写作时对照 rubric 逐维自查)。
- context 四键写实(缺陷要能从 context 推出:如 OOC 例的 characters 里写明性格底线)。
- chapter 型证据 = 注入句的原文短引(子串核验);absence 型证据空 + note 说清。

**首例全文示范(ds_01_ooc,逐字可用)**:

`case.json`:
```json
{
  "id": "ds_01_ooc",
  "split": "dev",
  "version": 1,
  "source": {"origin": "constructed", "license": "self-authored", "deidentified": true},
  "context": {
    "setting": "灵气复苏第三年。逆息体质者吸灵反噬,身份一旦暴露会被宗门当炉鼎抓走——保密是活命底线。",
    "characters": "沈砚:逆息体质,寡言谨慎,底线=绝不向陌生人透露体质;周楠:矿场医师,与沈砚初识,立场未明。",
    "prev_hook": "上一章末:周楠隔着矿道问『你的伤,为什么灵气靠近反而加重?』",
    "chapter_goal": "接住追问钩;沈砚用旧伤搪塞过去,保住秘密,埋周楠起疑线。"
  },
  "labels": [
    {"dimension": "人物OOC", "present": true, "severity": "高", "evidence_type": "chapter",
     "evidence": "我是逆息体质,灵气进不了脉,只会撕经络。",
     "note": "注入:沈砚对初识、立场未明的周楠和盘托出体质——直接踩穿 characters 里写死的保密底线,违背性格与立场。",
     "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "设定漂移", "present": false, "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "断钩子", "present": false, "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "无爽点", "present": false, "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "信息边界", "present": false, "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "物品状态连续性", "present": false, "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "时间连续性", "present": false, "annotator": "构造注入(gold-by-construction)"},
    {"dimension": "AI腔", "present": false, "annotator": "构造注入(gold-by-construction)"}
  ]
}
```

`chapter.md`:
```markdown
# 第四章 矿道问答

周楠的声音贴着矿道壁传过来,不轻不重:"你的伤,为什么灵气靠近反而加重?"

沈砚捏着矿牌的手停了半息。药香越来越近,他能听见对方鞋底碾过碎矸石的声响。

"旧伤。"他说,"塌方那年被矿灯烫的,见热就疼。"

周楠蹲下来,指尖悬在他小臂上方一寸,没碰。"烫伤不忌灵气。"

矿灯的光晃了晃。沈砚抬起眼,忽然把袖口捋了上去:"我是逆息体质,灵气进不了脉,只会撕经络。"

周楠的手指僵在半空。

说完这句,沈砚自己也怔住——三年来他连梦话都不敢带出这四个字。可话已出口,像矿牌落进深井,连回声都收不回来。

周楠收回手,慢慢站起身,药箱扣上的声音在矿道里格外清楚。"我什么都没听见。"她说。

沈砚望着她的背影没入黑暗,把矿牌攥得死紧。
```

(注意:这一章**故意**让 OOC 缺陷可判——characters 写死「绝不向陌生人透露」,正文却和盘托出;同时其余 7 维干净:接住了钩子(正面回应追问)、有收获(周楠表态线)、无设定冲突、无越界认知、无物品/时间问题、无 AI 腔句式。后续 ds_02/03/04 照此规范各自构造,**缺陷情节自拟但必须与 rubric 对应维度的正例判据一致**。)

**ds_02_drift(设定漂移,split=dev)**:context.setting 写死一条硬设定(如「力量体系 F~SSS,不存在『一阶』说法」),正文注入一句违反它的表述(evidence=该句短引);其余 7 维干净。
**ds_03_hook(断钩子,split=calibration)**:context.prev_hook 写明确钩子,正文通章不接、另起炉灶;evidence_type=absence(证据空,note 写清哪个钩没接);其余干净——注意本例仍需有爽点(否则误伤无爽点维度)。
**ds_04_payoff(无爽点,split=dev)**:通章事务性流水(赶路/清点/重复对话),无任何收获/信息增量/情绪释放;evidence_type=absence;注意仍要接住 prev_hook(否则误伤断钩子)。

- [ ] **Step 1: 写全数据集校验测试(一次写好,覆盖本任务与后续所有数据)**

`tests/test_eval_dataset.py` 追加:

```python
def test_shipped_dataset_all_cases_validate():
    # 仓库里实际发货的每个 case 都必须过校验器(含证据子串机械核验)
    dirs = discover_cases()
    assert dirs, "evals/dataset/cases 下还没有任何 case"
    for d in dirs:
        case = load_case(d)                            # 校验失败会抛,即测试红
        positives = [l for l in case["labels"] if l["present"]]
        assert positives, f"{case['id']}: v1 正例集每例至少 1 维 present=True(clean 负例在 Task 5 加入后本断言调整)"
```

(Task 5 加入 clean 负例时,**允许且必须**把最后一条断言改为「正例数 ≥0 且整集平衡校验移交 balance 测试」——这是计划内的断言演进,届时按 Task 5 的 Step 指令改,不算违反「既有断言禁改」。)

- [ ] **Step 2: 跑红**(cases 目录为空)→ **Step 3: 写 4 例数据** → **Step 4: 跑绿 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_dataset.py -q` → 全绿;全量 → 绿。

- [ ] **Step 5: Commit(原子 + pathspec)**

```bash
git add evals/dataset/cases tests/test_eval_dataset.py && git commit -m "$(cat <<'EOF'
feat(eval): 数据集v1 前4语义正例——OOC/设定漂移/断钩子/无爽点(构造性金标)

每例单缺陷单维度命中、其余7维自查干净;chapter型证据过子串机械核验,断钩/无爽点
走absence型;context 四键写实可推缺陷。全集校验测试一次落位,后续数据自动被盖。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)" -- evals/dataset/cases tests/test_eval_dataset.py
```

---

### Task 4: 数据集 v1 · 后 4 个语义正例 + 1 个硬约束组合例

**Files:**
- Create: `evals/dataset/cases/ds_05_infoleak/…`、`ds_06_item/…`、`ds_07_time/…`、`ds_08_slop/…`、`ds_09_hardcap/…`(各 case.json+chapter.md)

**Interfaces:** Consumes Task 1-3(校验器/rubric/全集测试自动覆盖新数据)。

**构造规范**(同 Task 3,另加):
- **ds_05_infoleak(信息边界,split=calibration)**:走⑤a 款——角色说出他不在场、正文也无任何情报来源交代的事;evidence=该句短引。注意别给归因句(有归因就不成立)。
- **ds_06_item(物品状态连续性,split=dev)**:context.setting 或 prev_hook 写明某物品「已在上一章耗尽/失去」,正文注入复用它的句子;evidence=该句。
- **ds_07_time(时间连续性,split=calibration)**:context.prev_hook 锚定时刻(如「昨夜三更」),正文时间词粒度冲突(如说成「前日」);evidence=该句。
- **ds_08_slop(AI腔,split=dev)**:注入 2-3 处典型 AI 腔(直接点名情绪/句式过整齐/万能词),fingerprint 无豁免;evidence=最典型一处短引;**其余 7 维干净,尤其别顺手写出设定冲突**。
- **ds_09_hardcap(硬约束组合,split=holdout)**:正文同时含「必含缺失+禁止项出现+AI 翻转句」型硬缺陷(确定性 grader 的辖区,spec 要求平衡集含硬约束类);8 维 Judge 标注**如实**——若注入的翻转句同时构成 AI腔,AI腔标 present=True(evidence=翻转句),其余维度如实标;case.json 加一个自由字段 `detector_note`(str)写明硬约束缺陷清单与「此类缺陷由 Fixture suite 的确定性 grader 辖区覆盖,本集只为平衡性收录」——校验器对未知附加字段宽容(不校验也不报错),不用改 dataset.py。

- [ ] **Step 1-4: 写数据 → 全集测试自动覆盖 → 跑绿 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_dataset.py -q` → 全绿(9 个 case 全过校验)。

- [ ] **Step 5: Commit(原子 + pathspec)**

```bash
git add evals/dataset/cases && git commit -m "$(cat <<'EOF'
feat(eval): 数据集v1 后4语义正例+硬约束组合例——信息边界/物品/时间/AI腔/hardcap

信息边界走⑤a无归因款;物品/时间靠context锚定前情再注入冲突句;AI腔注入无豁免
腔句;ds_09 硬约束组合(必含缺失+禁词+翻转句)为平衡性收录,注明确定性grader辖区,
8维Judge标注如实(翻转句同时构成AI腔即如实标)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)" -- evals/dataset/cases
```

---

### Task 5: 2 个干净难负例 + 平衡性测试

**Files:**
- Create: `evals/dataset/cases/ds_10_clean_voice/…`、`ds_11_clean_setup/…`
- Test: `tests/test_eval_dataset.py`(扩平衡测试 + 按 Task 3 预告调整全集断言)

**Interfaces:** Consumes Task 1-4。

**构造规范**:
- **ds_10_clean_voice(split=holdout)**:压 AI腔误报——正文带作者式「不规整/口头禅」(context.setting 里写明「作者指纹:短句收尾、惯用『他没说话。』」),表面像可挑,按指纹豁免护栏**不该抓**;8 维全 present=False。
- **ds_11_clean_setup(split=calibration)**:压 OOC/断钩误报——角色行为表面反常但 context 有铺垫(伪装接近敌人),钩子延迟接(本章埋映衬线);8 维全 present=False,context.chapter_goal 写清铺垫意图。

- [ ] **Step 1: 扩测试(平衡性钉死 + 调整 Task 3 预告的断言)**

`tests/test_eval_dataset.py`:把 `test_shipped_dataset_all_cases_validate` 里「每例至少 1 维正例」断言按 Task 3 预告**替换**为集级平衡测试(这是计划内演进):

```python
def test_shipped_dataset_all_cases_validate():
    dirs = discover_cases()
    assert dirs, "evals/dataset/cases 下还没有任何 case"
    for d in dirs:
        load_case(d)                                   # 逐例过校验器(抛错即红)


def test_dataset_v1_balance():
    cases = [load_case(d) for d in discover_cases()]
    by_dim_pos = {dim: 0 for dim in DIMENSIONS}
    clean_cases = 0
    splits = set()
    for c in cases:
        splits.add(c["split"])
        pos = [l for l in c["labels"] if l["present"]]
        if not pos:
            clean_cases += 1
        for l in pos:
            by_dim_pos[l["dimension"]] += 1
    assert all(n >= 1 for n in by_dim_pos.values()), f"每个维度至少 1 个正例:{by_dim_pos}"
    assert clean_cases >= 2, "至少 2 个干净难负例(压误报)"
    assert splits == set(SPLITS), f"三个 split 都要非空:{splits}"
```

- [ ] **Step 2-4: 跑红(clean 例缺)→ 写 2 例 → 跑绿 + 全量**

- [ ] **Step 5: Commit(原子 + pathspec)**

```bash
git add evals/dataset/cases tests/test_eval_dataset.py && git commit -m "$(cat <<'EOF'
feat(eval): 2个干净难负例+集级平衡测试——指纹豁免/铺垫伪装压误报

ds_10 作者指纹口头禅表面像AI腔但护栏豁免;ds_11 伪装行为表面OOC但context有铺垫;
平衡测试钉死:每维≥1正例、clean负例≥2、三split全非空。全集断言按计划内演进调整。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)" -- evals/dataset/cases tests/test_eval_dataset.py
```

---

### Task 6: 标注指南 + 第二标注者空白工作表 + README 节

**Files:**
- Create: `evals/dataset/ANNOTATION_GUIDE.md`、`evals/dataset/annotations/README.md`、`evals/dataset/annotations/worksheet_template.json`
- Modify: `evals/README.md`(加「Judge 校准数据集(Phase 2)」一节)
- Test: `tests/test_eval_dataset.py`(扩:工作表模板结构测试)

**Interfaces:**
- Produces: 人工标注的落盘格式约定 `annotations/<case_id>.<annotator_id>.json`——Phase 3 的 kappa 计算按此读取。模板结构:`{"case_id": "", "annotator_id": "", "annotated_at": "", "labels": [8 条 {dimension, present, severity?, evidence?, note?}]}`(维度顺序与 DIMENSIONS 一致,present 留 null 由标注者填)。

- [ ] **Step 1: 写失败测试**

```python
def test_annotation_worksheet_template_structure():
    t = json.loads(Path("evals/dataset/annotations/worksheet_template.json").read_text(encoding="utf-8"))
    assert t["case_id"] == "" and t["annotator_id"] == ""
    assert [l["dimension"] for l in t["labels"]] == list(DIMENSIONS)
    assert all(l["present"] is None for l in t["labels"])      # 留给真人填,不预填
```

- [ ] **Step 2: 跑红 → Step 3: 写三个文件 + README 节**

`ANNOTATION_GUIDE.md` 要点(写全,面向不了解本仓库的第二标注者):标注单位与流程(读 context → 读 chapter → 按 rubric 逐维判 present/severity/evidence)、**只依据 rubric 不脑补**、每例独立标注不得对照他人结果、拿不准按 rubric 边界例判并在 note 记录、工作表命名 `<case_id>.<annotator_id>.json`、完成后放 annotations/ 目录。
`annotations/README.md`:目录现状如实——「目前无任何人工标注;v1 金标为构造性;人-人一致性(κ 目标 ≥0.70,预注册于 Phase 3)待两名标注者对 calibration split 独立标注后计算」。
`evals/README.md` 新节:三套数据的第三套、构造性金标的含义与局限、如何招募第二标注者开始标注(指向 ANNOTATION_GUIDE)。

- [ ] **Step 4: 跑绿 + 全量** → **Step 5: Commit(原子 + pathspec)**

```bash
git add evals/dataset/ANNOTATION_GUIDE.md evals/dataset/annotations evals/README.md tests/test_eval_dataset.py && git commit -m "$(cat <<'EOF'
docs(eval): 标注指南+第二标注者空白工作表+README 数据集节——人工环节工具先行

工作表 8 维 present=null 留真人填(测试钉结构);annotations/README 如实声明
「目前零人工标注、金标为构造性、κ 数字待真人标注后才存在」。不造数。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)" -- evals/dataset/ANNOTATION_GUIDE.md evals/dataset/annotations evals/README.md tests/test_eval_dataset.py
```

---

### Task 7: 控制者验收(无代码)

- [ ] 全量 pytest 绿(预计 ~592);`run_eval --gate` 码 0;`git status` 无 evals/dataset 外泄改动。
- [ ] 抽读 2 个正例 + 1 个负例:缺陷是否真的只命中声明维度(对照 rubric 逐维自查一遍)、文风是否网文化、context 是否足以推出判定。
- [ ] rubric 与 gates.py CRITIC 原文对照:无发明判据、AI腔豁免护栏在。
- [ ] 汇报 + ledger。

---

## Phase 3-4 预告(各自另立)

| 期 | 内容 | 前置 |
|---|---|---|
| Phase 3 | Judge 结构化 JSON verdict(evals 侧,不动产品 gates)+ kappa/PRF meta-eval 纯函数 + 预注册阈值 targets.json + 校准报告生成器(真实数字等真标注) | Phase 2 |
| Phase 4 | 分层 CI + JSON/MD 报告 artifact | Phase 3 |
