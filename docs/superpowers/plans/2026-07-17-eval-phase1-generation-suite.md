# Eval Phase 1:Generation Suite(真调五 Agent 生成再评)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 把「评测器自测」(Fixture suite,已有)和「被测系统生成质量」(Generation suite,本计划新增)分开:对固定的 book context / 章纲 / 写作指纹,真调 loom 五 Agent 流水线生成候选正文,落 `evals/runs/<run_id>/`,复用既有 grader 评分,并写可追溯 manifest(git commit / provider / model / prompt+dataset hash / 时延;token/cost 诚实置 null)。

**Architecture:** 新增 `evals/generate.py`(独立 CLI 入口 `python -m evals.generate`,不动 run_eval 的 CI 契约)+ `evals/metering.py`(Backend 计量代理,唯一可行的注入点)。gen case = `evals/gen_cases/<id>/`(case.json + overlay/ 固定输入),运行时 scaffold 骨架 + 盖 overlay + 调 config → `run_pipeline` → 候选正文进 `evals/runs/<run_id>/`(gitignore)→ 复用 `harness.run_case` 评分。对 loom 的依赖仍只走 `loom.evalapi`(本计划给门面加 7 个**纯再导出**——这是门面 docstring 自己规定的扩展方式「改签名先改这里」)。

**Tech Stack:** Python 3.11 + pytest(现基线 562 绿)。零新依赖。测试零真实模型(ScriptedBackend / FakeBackend / DemoBackend 离线)。

**权威 spec:** `/Users/chambers/Desktop/loom-novel_eval补齐计划.md` §Phase 1 + 本会话侦察档案 `.superpowers/sdd/recon-p14/{pipeline,backends}.md`(真实坐标全部核对过)。

## Global Constraints

- **文件白名单**:新建 `evals/generate.py`、`evals/metering.py`、`evals/gen_cases/**`(数据)、`tests/test_eval_metering.py`、`tests/test_eval_generate.py`;修改 `loom/evalapi.py`(**唯一允许碰的 loom/ 文件,只准追加纯再导出,零逻辑、零签名改动**)、`.gitignore`(只加 `evals/runs/` 一行)、`evals/README.md`(Task 7)。**不碰** `evals/run_eval.py`/`harness.py`/`graders.py`(Fixture suite 已冻结,CI 契约)、`.github/workflows/`(Phase 4)、其余 `loom/**`、`evals/cases/**`、`evals/baseline.json`。
- **零真实模型进测试**:生成链路测试用 conftest `ScriptedBackend`(按序 pop)/`FakeBackend`;CLI 冒烟用 `LOOM_DEMO=1` 的 DemoBackend(离线罐头,测试里必须 `monkeypatch.setenv("LOOM_DEMO", "1")` 以免进程串染)。绝不初始化真网络后端。
- **CI 契约不动**:`python -m evals.run_eval --gate` 的行为/退出码零变化(本计划不碰它);全量 `.venv/bin/python -m pytest -q` 必须保持既有 562 绿 + 新增全绿;**golden 管线测试(tests/test_golden_pipeline.py)必须仍绿**——它钉死 run_pipeline 等价面,evalapi 只加再导出不会碰它,若它红了说明改错了地方。
- **不造数**:manifest 的 `tokens`/`cost` 置 `null` 并写明原因(Backend 协议不回传 usage,backends.py:293-296 丢弃 resp.usage;字符数是唯一代理指标);`retries: 0` 写明 run_pipeline 无内建重试;不承诺单次可复现(无 seed 通道),稳定性靠多次运行分布。demo 模式在文档里明说**不能**证明「prompt 变→输出变」(DemoBackend 按角色关键词吐罐头,与 user 内容无关)。
- **evalapi 红线延续**:evals 侧新代码只准 `from loom.evalapi import ...`;import 失败不降级不吞。
- 既有测试断言禁改。提交信息 `type(scope): 中文摘要` + 末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`;`git add` 只加本任务文件,绝不 `git add -A`。
- 环境 `.venv/bin/python`;测试 `.venv/bin/python -m pytest`。

## 现状锚点(实现者必读——侦察核实过的真实代码,别猜)

- `run_pipeline(project_root: Path, chapter_n: int, backend: Backend, config: Config, progress: Progress = _noop, *, slow: float = 0.0, resume: bool = True, critic_backend: Backend | None = None) -> tuple[Path, str]`(`loom/agents.py:596`)。返回 `(终稿路径, 终稿文本)`,终稿文本=H1 标题+正文。
- **调用数契约**(gate_rounds 默认、continuity_scan 关):首章全跑 = **8 次** `backend.complete`(设定师/大纲师/写手/编辑/质检复审/润色师/去AI味复审/起标题);**细纲已存在时大纲师被 WYSIWYG 旁路 = 7 次**(evals 固定章纲的切入点:跑前把细纲写到 `paths.outline_path(root, n)` = `正文/.细纲/第{n}章.md`)。范式:`tests/test_golden_pipeline.py:24-33` 的 `_FULL_RUN` 与场景 D。
- `Backend` 协议:`complete(self, system, user, *, max_chars=None, on_chunk=None, agent_mode=False) -> str`(`loom/backends.py:197`)。run_pipeline 不传 agent_mode(golden 的 RecordingBackend 无此参仍绿)。**协议不回传 token/耗时/成本**;run_pipeline 无重试(失败 raise LoomBackendError)。
- `scaffold_init("书名", parent=tmp)` 铺全套骨架(agents/*.md、外置大脑目录形态、loom.toml、中性指纹),conftest `project` fixture 就是它。
- `load_config(root)` / `save_config(root, cfg)`:golden 测试示范 `cfg.continuity_scan = False; save_config(...)` 可持久化;**chapter_chars 是否能走同路持久化需实现时验证**——若不行,退回 golden 的 toml 文本替换法(`'"章节字数" = 800'` → 目标值)。
- 终稿最短闸 = 目标字数×12%(地板 40 字);脚本产出 ≥40 字即可过闸(chapter_chars=200 时)。
- `loom/evalapi.py` 现导出 6 名(CRITIC_去AI味/CRITIC_质检/Issue/detect_aitell/parse_critic_verdict/segment_sentences),docstring 明言「改签名 = 改契约,先改这里再改 evals」。
- conftest:`FakeBackend(responder)`(`tests/conftest.py:23-35`)、`ScriptedBackend(replies)`(`:61-83`,按序 pop,耗尽返 `""` 不炸)、`project` fixture(`:18-20`)、autouse `_isolate_user_config` 已隔离 `LOOM_HOME`。
- `Config` 字段(config.py:20):provider/model/cheap_model/base_url/title/idea/chapter_chars/gate_rounds/foreshadow_distance/continuity_scan。**无 temperature/seed**。demo 模式下 `get_backend` 返回 DemoBackend,与 cfg.provider 字面无关——manifest 必须额外记 `backend_class` 以免撒谎。
- 编辑棒产出需含哨兵围栏:`from loom.parse import EDIT_NOTE_OPEN, EDIT_NOTE_CLOSE`(测试文件可用,golden 测试同款)。

---

### Task 1: evalapi 生成接缝(七个纯再导出)

**Files:**
- Modify: `loom/evalapi.py`(只追加 import + `__all__` 项)
- Test: `tests/test_eval_generate.py`(新建)

**Interfaces:**
- Produces: `loom.evalapi` 新增导出 `run_pipeline`、`scaffold_init`、`load_config`、`save_config`、`Config`、`get_backend`、`outline_path`——后续任务的 evals 侧代码只准从这里拿。
- Consumes: 无(第一个任务)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_generate.py`:

```python
"""Generation suite:evalapi 生成接缝 + 固定输入生成链路。零真实模型。"""
from loom import evalapi

_GEN_SEAM = ("run_pipeline", "scaffold_init", "load_config", "save_config",
             "Config", "get_backend", "outline_path")


def test_evalapi_generation_seam_exports():
    # Phase 1 生成接缝:七个再导出必须存在且进 __all__(evals 只准走门面)
    for name in _GEN_SEAM:
        assert hasattr(evalapi, name), f"evalapi 缺生成接缝导出:{name}"
        assert name in evalapi.__all__, f"{name} 未进 evalapi.__all__"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -v`
Expected: FAIL——`evalapi 缺生成接缝导出:run_pipeline`。

- [ ] **Step 3: 实现**

`loom/evalapi.py` 在现有 import 块后追加(并入 `__all__`,保持字母序不强求、分组注释要有):

```python
# ── Generation suite 接缝(Phase 1)──纯再导出,零逻辑:evals/generate.py 真调
#    五 Agent 流水线所需的最小集合。引擎侧改这些符号的签名 = 改契约,先改这里。
from .agents import run_pipeline
from .backends import get_backend
from .config import Config, load_config, save_config
from .paths import outline_path
from .scaffold import init as scaffold_init
```

`__all__` 追加:`"Config", "get_backend", "load_config", "outline_path", "run_pipeline", "save_config", "scaffold_init"`。

- [ ] **Step 4: 跑测试通过 + golden 不破**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py tests/test_golden_pipeline.py -q`
Expected: 全绿(再导出不碰 run_pipeline 本体,golden 必须仍绿)。
Run: `.venv/bin/python -m pytest -q`
Expected: 563 passed(562 + 1)。

- [ ] **Step 5: Commit**

```bash
git add loom/evalapi.py tests/test_eval_generate.py
git commit -m "$(cat <<'EOF'
feat(eval): evalapi 生成接缝——七个纯再导出,Generation suite 只走门面

run_pipeline/scaffold_init/load_config/save_config/Config/get_backend/outline_path
以公共稳定名进 evalapi(门面 docstring 规定的扩展方式)。零逻辑零签名改动,
golden 管线测试不受影响。evals 侧「只准 import evalapi」红线延续到生成链路。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: MeteringBackend 计量代理

**Files:**
- Create: `evals/metering.py`
- Test: `tests/test_eval_metering.py`(新建)

**Interfaces:**
- Produces: `MeteringBackend(inner)`——满足 Backend 协议的透明代理;`.records: list[CallRecord]`,`CallRecord(system_prompt: str, user_chars: int, output_chars: int, max_chars: int | None, elapsed_s: float)`。Task 4 用它包住真/假后端,Task 5 从 `.records` 取 prompt hash 与时延。
- Consumes: conftest `FakeBackend`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_eval_metering.py`:

```python
"""MeteringBackend:透明代理不改行为,只记账。零真实模型。"""
import pytest

from conftest import FakeBackend
from evals.metering import MeteringBackend


def test_metering_passthrough_and_records():
    fb = FakeBackend(lambda s, u: "产出文本")
    m = MeteringBackend(fb)
    out = m.complete("SYS", "USER输入", max_chars=600)
    assert out == "产出文本"
    assert fb.calls == [("SYS", "USER输入")]          # 透传不改行为
    r = m.records[0]
    assert r.system_prompt == "SYS"
    assert r.user_chars == len("USER输入")
    assert r.output_chars == len("产出文本")
    assert r.max_chars == 600
    assert r.elapsed_s >= 0


def test_metering_on_chunk_passthrough():
    got: list[str] = []
    m = MeteringBackend(FakeBackend(lambda s, u: "流式"))
    m.complete("S", "U", on_chunk=got.append)
    assert got == ["流式"]                             # FakeBackend 的 on_chunk 回放仍生效


def test_metering_propagates_backend_error_without_fake_record():
    def boom(s, u):
        raise RuntimeError("后端炸了")
    m = MeteringBackend(FakeBackend(boom))
    with pytest.raises(RuntimeError):
        m.complete("S", "U")
    assert m.records == []                             # 失败调用不记成功账
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_metering.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'evals.metering'`。

- [ ] **Step 3: 实现**

新建 `evals/metering.py`:

```python
"""计量代理:包住任意 Backend,记录每次 complete 的时延/输入输出字符数/system prompt。

Backend 协议(loom/backends.py:197)不回传 token 用量——OpenAI 兼容后端在
backends.py:293-296 丢弃 resp.usage,CLI 后端(claude/codex)只有文本 stdout。
所以 manifest 里 tokens/cost 诚实置 null,字符数是唯一可得的代理指标。
backend.complete 是五 Agent + 复审 + 起标题的唯一调用点,包代理即覆盖全部调用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CallRecord:
    system_prompt: str
    user_chars: int
    output_chars: int
    max_chars: int | None
    elapsed_s: float


class MeteringBackend:
    """透明代理:行为与被包 backend 完全一致,只多记账;失败调用原样抛、不记账。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.records: list[CallRecord] = []

    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None, **kw) -> str:
        t0 = time.perf_counter()
        out = self.inner.complete(system, user, max_chars=max_chars, on_chunk=on_chunk, **kw)
        self.records.append(CallRecord(
            system_prompt=system, user_chars=len(user), output_chars=len(out),
            max_chars=max_chars, elapsed_s=round(time.perf_counter() - t0, 4)))
        return out
```

(注:`**kw` 透传 `agent_mode` 等协议关键字;conftest 的 FakeBackend 无 agent_mode 形参、run_pipeline 也不传它,空 `**kw` 无害。`field` import 若未用到则删——以 linter/实际为准,别留死 import。)

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_metering.py -q`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add evals/metering.py tests/test_eval_metering.py
git commit -m "$(cat <<'EOF'
feat(eval): MeteringBackend 计量代理——时延/字符数记账,token 诚实置空

backend.complete 是流水线全部调用的唯一汇点,包透明代理即得全量计量。
协议不回传 usage(backends.py 丢弃 resp.usage),tokens/cost 不造数、
字符数作代理指标;失败调用原样抛不记假账。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: gen case 载入 + 项目搭建(scaffold + overlay + config)

**Files:**
- Create: `evals/generate.py`(本任务只到 prepare 层)
- Test: `tests/test_eval_generate.py`(扩)

**Interfaces:**
- Produces: `load_gen_case(case_dir: Path) -> dict`(校验必填 id/chapter_n/chapter_chars,缺则 ValueError);`prepare_project(case_dir: Path, case: dict, workdir: Path) -> Path`(scaffold 骨架 → 盖 overlay → chapter_chars/gate_rounds/continuity_scan 调 config → 返回项目根)。
- Consumes: Task 1 的 evalapi 生成接缝。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_generate.py` 追加(文件顶部补 import:`import json`、`from pathlib import Path`、`from evals.generate import load_gen_case, prepare_project`、`from loom.evalapi import load_config`):

```python
def _write_gen_case(tmp_path, *, with_outline=True):
    d = tmp_path / "gen_case_src"
    (d / "overlay" / "正文" / ".细纲").mkdir(parents=True)
    (d / "case.json").write_text(json.dumps({
        "id": "gen_test", "title": "生成测试例", "chapter_n": 1, "chapter_chars": 200,
        "expect": {"must_include": ["矿灯"], "must_not_include": ["二中"]},
    }, ensure_ascii=False), encoding="utf-8")
    if with_outline:
        (d / "overlay" / "正文" / ".细纲" / "第1章.md").write_text(
            "固定细纲:分镜一醒来验伤;分镜二矿灯下遇人;分镜三末场倒计时钩。\n", encoding="utf-8")
    return d


def test_load_gen_case_validates_required_fields(tmp_path):
    d = tmp_path / "bad"; d.mkdir()
    (d / "case.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="chapter_n"):
        load_gen_case(d)


def test_prepare_project_applies_overlay_and_config(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    case = load_gen_case(case_dir)
    work = tmp_path / "work"; work.mkdir()
    project = prepare_project(case_dir, case, work)
    assert (project / "agents" / "写手.md").is_file()               # scaffold 骨架就绪
    outline = (project / "正文" / ".细纲" / "第1章.md").read_text(encoding="utf-8")
    assert outline.startswith("固定细纲")                            # overlay 盖上了
    cfg = load_config(project)
    assert cfg.chapter_chars == 200                                  # case 的字数进了 config
    assert cfg.continuity_scan is False                              # 评测口径固定关(省一次调用)
```

(pytest import 放文件顶部,别嵌函数里——上面写在函数内只为示意断言,实现测试时提升到顶部。)

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -v -k "gen_case or prepare"`
Expected: FAIL——`ImportError: cannot import name 'load_gen_case' from 'evals.generate'`(模块不存在)。

- [ ] **Step 3: 实现**

新建 `evals/generate.py`:

```python
"""Generation suite:对固定输入真调 loom 五 Agent 流水线生成候选正文,再用既有 grader 评。

与 Fixture suite(evals/cases/ + run_eval)的二分:
- Fixture suite 用固定文本验证「评测器没坏」,零 key,进每次 PR CI;
- Generation suite 真调 run_pipeline 验证「被测系统的生成质量」,产物落
  evals/runs/<run_id>/,绝不覆盖数据集金标;手动/定时跑,不进 PR CI。

复用只走 loom.evalapi(生成接缝)。demo 模式(LOOM_DEMO=1 罐头后端)只能证明
链路通,不能证明「prompt 变→输出变」——真机验收用 --backend configured。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from loom.evalapi import (
    load_config,
    save_config,
    scaffold_init,
)

HERE = Path(__file__).resolve().parent
GEN_CASES_DIR = HERE / "gen_cases"
RUNS_DIR = HERE / "runs"

_REQUIRED = ("id", "chapter_n", "chapter_chars")


def load_gen_case(case_dir: Path) -> dict:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    for key in _REQUIRED:
        if key not in case:
            raise ValueError(f"gen case 缺必填字段 {key}:{case_dir}")
    return case


def prepare_project(case_dir: Path, case: dict, workdir: Path) -> Path:
    """铺 scaffold 骨架 → 盖 overlay 固定输入 → 按 case 调 config。返回项目根。"""
    project = scaffold_init(case["id"], parent=workdir)
    overlay = case_dir / "overlay"
    if overlay.is_dir():
        for src in sorted(overlay.rglob("*")):
            if src.is_dir():
                continue
            dst = project / src.relative_to(overlay)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    cfg = load_config(project)
    cfg.chapter_chars = case["chapter_chars"]
    cfg.gate_rounds = case.get("gate_rounds", cfg.gate_rounds)
    cfg.continuity_scan = False   # 附赠扫描是额外模型调用;评测口径固定为关(与 golden 同口径)
    save_config(project, cfg)
    return project
```

**实现时必验**:`save_config` 是否把 `chapter_chars` round-trip 进 `loom.toml`(golden 测试只示范过 continuity_scan 走 save_config、chapter_chars 走 toml 文本替换)。跑 Step 1 测试即验;若 `load_config` 读回不是 200,改用 golden 的文本替换法(`'"章节字数" = 800'` → `'"章节字数" = 200'`)并在代码注释里写明原因。**别改 loom/config.py。**

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -q`
Expected: 全绿(Task 1 的 1 条 + 本任务 2 条)。

- [ ] **Step 5: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'EOF'
feat(eval): gen case 载入+项目搭建——scaffold 骨架盖 overlay 固定输入

gen case = case.json(必填 id/chapter_n/chapter_chars)+ overlay/(相对项目根
的固定输入文件,细纲盖进 正文/.细纲/ 即触发大纲师 WYSIWYG 旁路)。config 按
case 调字数、固定关 continuity_scan(评测口径与 golden 一致)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: generate_one 主流程(真调流水线 → runs 落盘 → 复用 run_case 评分)

**Files:**
- Modify: `evals/generate.py`
- Test: `tests/test_eval_generate.py`(扩)

**Interfaces:**
- Consumes: Task 2 `MeteringBackend`、Task 3 `load_gen_case`/`prepare_project`、evalapi 接缝、`evals.harness.run_case`(Phase 0 已有,`run_case(case_dir) -> CaseResult`)。
- Produces: `generate_one(case_dir: Path, *, backend=None, backend_mode: str = "demo", provider: str | None = None, model: str | None = None, runs_dir: Path | None = None, workdir: Path | None = None) -> Path`(返回 run 目录;`backend` 显式给了就注入并把 mode 记为 `injected(测试)`);run 目录含 `chapter.md`、`case.json`(评分用副本)、`report.json`(CaseResult.as_dict)。Task 5 在此函数里加 manifest 调用。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_generate.py` 追加(顶部补:`from conftest import ScriptedBackend`、`from evals.generate import generate_one`、`from loom.parse import EDIT_NOTE_CLOSE, EDIT_NOTE_OPEN`):

```python
# 7 调脚本(细纲 overlay 旁路大纲师):设定/写手/编辑/质检"通过"/润色/去AI味"通过"/标题。
# 产出文本 ≥40 字过终稿最短闸(200×12%=24,地板40);避开翻转句与禁词,含"矿灯"喂 must_include。
_SETTER = "本章设定锚点:主角沈砚在废弃矿场;境界凡境;金手指为重生记忆。"
_DRAFT = "寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀。"
_EDITED = (_DRAFT + "\n" + EDIT_NOTE_OPEN + "\n《本章改动留痕》\n- 钩子更硬。\n" + EDIT_NOTE_CLOSE)
_POLISHED = "寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀,也记得递刀的人。"
_GEN_RUN_7 = [_SETTER, _DRAFT, _EDITED, "通过", _POLISHED, "通过", "矿灯"]


def test_generate_one_end_to_end_offline(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    be = ScriptedBackend(list(_GEN_RUN_7))
    run_dir = generate_one(case_dir, backend=be,
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    assert be.replies == []                                        # 恰好 7 调(调用数契约)
    text = (run_dir / "chapter.md").read_text(encoding="utf-8")
    assert "矿灯" in text and EDIT_NOTE_OPEN not in text           # 终稿落盘且无哨兵残留
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["case_id"] == "gen_test"
    assert any(g["name"] == "关键要素" for g in report["graders"])  # 复用既有 grader 真跑了
    assert not (case_dir / "chapter.md").exists()                  # 金标数据集目录零写入


def test_generate_one_runs_never_collide(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    kw = dict(runs_dir=tmp_path / "runs")
    r1 = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                      workdir=tmp_path / "w1", **kw)
    r2 = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                      workdir=tmp_path / "w2", **kw)
    assert r1 != r2 and r1.exists() and r2.exists()                # 两次运行两个目录,零覆盖
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -v -k "generate_one"`
Expected: FAIL——`ImportError: cannot import name 'generate_one'`。

- [ ] **Step 3: 实现**

`evals/generate.py` 顶部 import 扩为:

```python
import os
import subprocess
import tempfile
import time

from loom.evalapi import (
    get_backend,
    load_config,
    save_config,
    scaffold_init,
    run_pipeline,
)

from .harness import run_case
from .metering import MeteringBackend
```

追加实现:

```python
def _grade_candidate(run_dir: Path, case: dict, chapter_text: str):
    """候选正文落成 run 目录里的 quality case,完整复用 harness.run_case 评分(零重复逻辑)。"""
    (run_dir / "chapter.md").write_text(chapter_text, encoding="utf-8")
    grading_case = {
        "id": case["id"], "title": case.get("title", case["id"]),
        "chapter_chars": case["chapter_chars"], "fixture": "chapter.md",
        "fingerprint_anchors": case.get("fingerprint_anchors", []),
        "expect": case.get("expect", {}),
    }
    (run_dir / "case.json").write_text(
        json.dumps(grading_case, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_case(run_dir)


def _git_sha() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, cwd=HERE)
    return out.stdout.strip() or "nogit"


def generate_one(case_dir: Path, *, backend=None, backend_mode: str = "demo",
                 provider: str | None = None, model: str | None = None,
                 runs_dir: Path | None = None, workdir: Path | None = None) -> Path:
    """跑一个 gen case:固定输入 → 真调五 Agent → 候选落 runs/<run_id>/ → 评分。返回 run 目录。

    backend 显式给了就用它(测试注入 ScriptedBackend,mode 记为 injected);
    否则按 backend_mode:demo → LOOM_DEMO=1 占位后端(零 key 链路冒烟);
    configured → 项目配置后端(要 key,--provider/--model 可覆写)。
    """
    case = load_gen_case(case_dir)
    runs_dir = runs_dir or RUNS_DIR
    workdir = Path(tempfile.mkdtemp(prefix="loomgen_")) if workdir is None else workdir
    project = prepare_project(case_dir, case, workdir)
    cfg = load_config(project)
    if provider:
        cfg.provider = provider
    if model:
        cfg.model = model

    if backend is not None:
        backend_mode = "injected(测试)"
    else:
        if backend_mode == "demo":
            os.environ["LOOM_DEMO"] = "1"
        backend = get_backend(cfg)
    metered = MeteringBackend(backend)

    git_sha = _git_sha()
    base = f"{time.strftime('%Y%m%d-%H%M%S')}_{case['id']}_{git_sha}"
    run_id, n = base, 1
    while (runs_dir / run_id).exists():
        n += 1
        run_id = f"{base}-{n}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)

    t0 = time.perf_counter()
    _path, final = run_pipeline(project, case["chapter_n"], metered, cfg, resume=False)
    total_s = round(time.perf_counter() - t0, 3)

    result = _grade_candidate(run_dir, case, final)
    (run_dir / "report.json").write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    # manifest 由 Task 5 挂进来(write_manifest 调用点在此)
    _ = (backend_mode, metered, total_s, git_sha)   # Task 5 消费;先占住变量防 lint 误删
    return run_dir
```

(Task 5 会把最后那行占位替换成真正的 `write_manifest(...)` 调用——这是刻意的两步,评审按此对照。)

- [ ] **Step 4: 跑测试通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -q` → 全绿。
Run: `.venv/bin/python -m pytest -q` → 全绿(golden 不破)。

- [ ] **Step 5: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'EOF'
feat(eval): generate_one 真调五 Agent——固定输入生成→runs 落盘→复用 run_case 评分

细纲 overlay 触发大纲师旁路(7 调契约,ScriptedBackend 钉死);候选正文+评分
报告落 evals/runs/<run_id>/(时间戳+case+commit,碰撞自增),金标数据集零写入;
评分完整复用 harness.run_case,零重复 grader 逻辑。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: manifest(可追溯:commit / provider / model / hash / 时延;不造数)

**Files:**
- Modify: `evals/generate.py`
- Test: `tests/test_eval_generate.py`(扩)

**Interfaces:**
- Consumes: Task 2 `CallRecord`、Task 4 `generate_one` 里的占位调用点。
- Produces: `write_manifest(run_dir, case_dir, case, cfg, backend_mode, backend_class, metered, total_s, git_sha) -> None`,写 `run_dir/manifest.json`;`generate_one` 的占位行替换为对它的调用。manifest 键:`run_id/git_commit/backend_mode/backend_class/provider/model/prompt_hash/dataset_hash/params/calls/n_calls/total_elapsed_s/tokens/cost/retries/notes`。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_generate.py` 追加:

```python
def test_manifest_traceability_fields(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    run_dir = generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                           runs_dir=tmp_path / "runs", workdir=tmp_path / "work")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["run_id"] == run_dir.name
    assert m["git_commit"] and m["git_commit"] != "nogit"          # 本仓是 git 仓,必有 sha
    assert m["backend_mode"] == "injected(测试)"
    assert m["backend_class"] == "ScriptedBackend"                 # 实际后端类名,不撒谎
    assert m["n_calls"] == 7 and len(m["calls"]) == 7              # 7 调契约进档
    assert all(c["elapsed_s"] >= 0 and c["output_chars"] > 0 for c in m["calls"][:3])
    assert m["tokens"] is None and m["cost"] is None               # 不造数
    assert m["retries"] == 0
    assert "usage" in m["notes"] or "代理指标" in m["notes"]        # 置空原因写明


def test_manifest_hashes_stable_and_sensitive(tmp_path):
    case_dir = _write_gen_case(tmp_path)
    kw = dict(runs_dir=tmp_path / "runs")
    m1 = json.loads((generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                                  workdir=tmp_path / "w1", **kw) / "manifest.json").read_text(encoding="utf-8"))
    m2 = json.loads((generate_one(case_dir, backend=ScriptedBackend(list(_GEN_RUN_7)),
                                  workdir=tmp_path / "w2", **kw) / "manifest.json").read_text(encoding="utf-8"))
    assert m1["prompt_hash"] == m2["prompt_hash"]                  # 同输入同 prompt → hash 稳定
    assert m1["dataset_hash"] == m2["dataset_hash"]
    # 数据集变一个字 → dataset_hash 必变
    (case_dir / "overlay" / "正文" / ".细纲" / "第1章.md").write_text("改了的细纲\n", encoding="utf-8")
    m3 = json.loads((generate_one(case_dir, backend=ScriptedBackend(
        [_SETTER, _DRAFT, _EDITED, "通过", _POLISHED, "通过", "矿灯"]),
        workdir=tmp_path / "w3", **kw) / "manifest.json").read_text(encoding="utf-8"))
    assert m3["dataset_hash"] != m1["dataset_hash"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -v -k "manifest"`
Expected: FAIL——`manifest.json` 不存在(FileNotFoundError)。

- [ ] **Step 3: 实现**

`evals/generate.py` 顶部补 `import hashlib`。追加:

```python
def _hash_dir(d: Path) -> str:
    """目录内容指纹:相对路径+字节流一起进 hash,文件名序固定。"""
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(d).as_posix().encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def write_manifest(run_dir: Path, case_dir: Path, case: dict, cfg, backend_mode: str,
                   backend_class: str, metered: MeteringBackend, total_s: float,
                   git_sha: str) -> None:
    prompts = sorted({r.system_prompt for r in metered.records})
    manifest = {
        "run_id": run_dir.name,
        "git_commit": git_sha,
        "backend_mode": backend_mode,
        "backend_class": backend_class,   # 实际后端类名:demo 模式下 provider 字段是配置残影,以此为准
        "provider": cfg.provider,
        "model": cfg.model,
        "prompt_hash": hashlib.sha256("\n\x00".join(prompts).encode("utf-8")).hexdigest()[:16],
        "dataset_hash": _hash_dir(case_dir),
        "params": {"chapter_n": case["chapter_n"], "chapter_chars": case["chapter_chars"],
                   "gate_rounds": cfg.gate_rounds, "continuity_scan": cfg.continuity_scan},
        "calls": [{"system_sha": hashlib.sha256(r.system_prompt.encode("utf-8")).hexdigest()[:12],
                   "user_chars": r.user_chars, "output_chars": r.output_chars,
                   "max_chars": r.max_chars, "elapsed_s": r.elapsed_s}
                  for r in metered.records],
        "n_calls": len(metered.records),
        "total_elapsed_s": total_s,
        "tokens": None,
        "cost": None,
        "retries": 0,
        "notes": ("tokens/cost=null:Backend 协议不回传 usage(backends.py 丢弃 resp.usage),"
                  "字符数为唯一代理指标;retries=0:run_pipeline 无内建重试(失败即 raise),"
                  "断点续跑是跨进程机制;无 seed 通道,单次结果不承诺可复现,稳定性用多次运行分布观测。"),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
```

`generate_one` 里把占位行 `_ = (backend_mode, metered, total_s, git_sha)` 替换为:

```python
    write_manifest(run_dir, case_dir, case, cfg, backend_mode,
                   type(metered.inner).__name__, metered, total_s, git_sha)
```

- [ ] **Step 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -q` → 全绿。

- [ ] **Step 5: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py
git commit -m "$(cat <<'EOF'
feat(eval): 生成 manifest——commit/backend类/provider/model/prompt+dataset hash/时延,不造数

prompt_hash 取自运行时真发出的 system prompt 集合(git commit 之外的第二重锚);
dataset_hash 对 gen case 目录逐字节;backend_class 记实际后端类名(demo 下 provider
字段是配置残影,防撒谎)。tokens/cost=null+写明原因,retries=0+写明无内建重试。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: CLI 入口 `python -m evals.generate` + runs 目录 gitignore

**Files:**
- Modify: `evals/generate.py`(main + argparse)
- Modify: `.gitignore`(加 `evals/runs/` 一行)
- Test: `tests/test_eval_generate.py`(扩)

**Interfaces:**
- Consumes: Task 4/5 的 `generate_one`。
- Produces: `main(argv) -> int`:`--case <id>`(缺省跑全部)、`--backend {demo,configured}`(默认 demo)、`--provider/--model`(configured 覆写)、`--cases-dir/--runs-dir`(测试可指)。退出码:0=完成(评分结果只观测不拦截,门禁化属 Phase 4)/ 2=infra(无 gen case 目录/找不到指定 case)。

- [ ] **Step 1: 写失败测试**

`tests/test_eval_generate.py` 追加(顶部补 `from evals.generate import main`):

```python
def test_cli_unknown_case_is_infra_2(tmp_path):
    (tmp_path / "gc").mkdir()
    assert main(["--case", "不存在", "--cases-dir", str(tmp_path / "gc"),
                 "--runs-dir", str(tmp_path / "runs")]) == 2


def test_cli_empty_cases_dir_is_infra_2(tmp_path):
    (tmp_path / "gc").mkdir()
    assert main(["--cases-dir", str(tmp_path / "gc"), "--runs-dir", str(tmp_path / "runs")]) == 2


def test_cli_demo_mode_end_to_end(tmp_path, monkeypatch):
    # demo 模式离线冒烟:证明 CLI→generate_one→DemoBackend 链路通(不证明生成质量)。
    # monkeypatch 先设 LOOM_DEMO,保证 teardown 复原、不串染其它测试。
    monkeypatch.setenv("LOOM_DEMO", "1")
    src = _write_gen_case(tmp_path)
    gc = tmp_path / "gc"; gc.mkdir()
    shutil.copytree(src, gc / "gen_test")
    code = main(["--cases-dir", str(gc), "--runs-dir", str(tmp_path / "runs")])
    assert code == 0
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "manifest.json").is_file() and (runs[0] / "report.json").is_file()
    m = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert m["backend_class"] == "DemoBackend"        # 罐头后端如实入档
```

(顶部补 `import shutil`。)

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -v -k "cli"`
Expected: FAIL——`cannot import name 'main'`。

- [ ] **Step 3: 实现**

`evals/generate.py` 追加:

```python
def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys as _sys

    ap = argparse.ArgumentParser(description="loom Generation suite(真调五 Agent 生成再评;手动/定时跑,不进 PR CI)")
    ap.add_argument("--case", help="gen case id(gen_cases/ 下目录名);缺省跑全部")
    ap.add_argument("--backend", choices=["demo", "configured"], default="demo",
                    help="demo=占位后端零 key 链路冒烟(不能证明 prompt 变化);configured=项目配置后端(要 key)")
    ap.add_argument("--provider", help="configured 模式覆写 provider")
    ap.add_argument("--model", help="configured 模式覆写 model")
    ap.add_argument("--cases-dir", type=Path, default=GEN_CASES_DIR)
    ap.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = ap.parse_args(argv)

    if not args.cases_dir.is_dir():
        print(f"✗ 没有 gen case 目录:{args.cases_dir}")
        return 2
    if args.case:
        target = args.cases_dir / args.case
        if not (target / "case.json").is_file():
            print(f"✗ 找不到 gen case:{args.case}(于 {args.cases_dir})")
            return 2
        case_dirs = [target]
    else:
        case_dirs = sorted(p.parent for p in args.cases_dir.glob("*/case.json"))
        if not case_dirs:
            print(f"✗ {args.cases_dir} 下没有任何 gen case(需要 <case>/case.json)")
            return 2

    for d in case_dirs:
        run_dir = generate_one(d, backend_mode=args.backend, provider=args.provider,
                               model=args.model, runs_dir=args.runs_dir)
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        flag = "✅" if report["passed"] else "❌"
        print(f"{flag} {report['case_id']}  score={report['score']}  → {run_dir}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

`.gitignore` 追加一行(先看现有格式照抄风格):

```
evals/runs/
```

- [ ] **Step 4: 跑测试通过 + gitignore 生效验证**

Run: `.venv/bin/python -m pytest tests/test_eval_generate.py -q` → 全绿。
Run: `git check-ignore -v evals/runs/x 2>/dev/null || echo "未忽略"` → 应输出 .gitignore 规则行(不是「未忽略」)。

- [ ] **Step 5: Commit**

```bash
git add evals/generate.py tests/test_eval_generate.py .gitignore
git commit -m "$(cat <<'EOF'
feat(eval): evals.generate CLI——demo/configured 双模+退出码 0/2,runs 目录入 gitignore

python -m evals.generate [--case id] [--backend demo|configured] [--provider/--model]。
0=完成(评分只观测,门禁化属 Phase 4)/2=infra。demo 冒烟证链路通、DemoBackend
如实入档;真机验收走 configured。evals/runs/ 是运行产物,不进版本库。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 首个 gen case 数据 + evals/README.md 重写(Fixture/Generation 二分)

**Files:**
- Create: `evals/gen_cases/gen_01_mine_rebirth/case.json`、`evals/gen_cases/gen_01_mine_rebirth/overlay/正文/.细纲/第1章.md`
- Modify: `evals/README.md`
- Test: 无新增(数据+文档任务;既有测试保障格式——`load_gen_case` 校验必填字段)

**Interfaces:**
- Consumes: Task 3 的 gen case 格式、Task 6 的 CLI。
- Produces: 可跑的第一个 gen case;README 反映 Phase 0+1 真实现状。

- [ ] **Step 1: 写 gen case 数据**

`evals/gen_cases/gen_01_mine_rebirth/case.json`:

```json
{
  "id": "gen_01_mine_rebirth",
  "title": "废矿重生·首章(生成型)",
  "chapter_n": 1,
  "chapter_chars": 600,
  "expect": {
    "must_include": ["沈砚", "矿"],
    "must_not_include": ["二中", "一阶0级"],
    "max_aitell_hits": 0,
    "len_tolerance": 0.6
  },
  "note": "Generation suite 首例:固定细纲(overlay)旁路大纲师,其余上下文用 scaffold 模板缺省(同样是固定输入)。expect 断言细纲要素落进正文(沈砚/矿)+ 禁设定漂移词。demo 模式跑它只证链路,报告可能 ❌(罐头文本不含细纲要素)——这不是坏,是 demo 的诚实边界;真机(--backend configured)才评生成质量。"
}
```

`evals/gen_cases/gen_01_mine_rebirth/overlay/正文/.细纲/第1章.md`:

```markdown
分镜一:沈砚在废弃矿场深处醒来,验伤,发现逆息体质的旧患未愈。
分镜二:矿灯昏黄,沈砚凭重生记忆避开塌方区,拾到半块旧矿牌。
分镜三:章末钩——矿道尽头传来脚步声,来人提灯,灯是三年后他见过的那盏。
```

- [ ] **Step 2: 验证 case 可载入 + demo 端到端跑通**

Run: `.venv/bin/python -c "from pathlib import Path; from evals.generate import load_gen_case; print(load_gen_case(Path('evals/gen_cases/gen_01_mine_rebirth'))['id'])"`
Expected: `gen_01_mine_rebirth`。
Run: `LOOM_DEMO=1 .venv/bin/python -m evals.generate --case gen_01_mine_rebirth; echo "码=$?"`
Expected: 跑完打一行 ✅/❌(❌ 属正常,见 note)+ `码=0`;`evals/runs/` 出现一个 run 目录且 `git status` 不显示它(gitignore 生效)。

- [ ] **Step 3: 重写 evals/README.md**

保留现有结构,必改四处(先读现文件,按其风格改):
1. **Fixture/Generation 二分**:开头加一节说明两套 suite 的分工(Fixture=评测器自测/零 key/进 PR CI;Generation=生成质量/要 key 或 demo 冒烟/手动跑/产物进 evals/runs/ 不进版本库)。
2. **case_02 过时描述修正**(现 README:95 附近「应当 FAIL」):改为 detector_contract 契约语义(命中缺陷=契约成立=判绿,检测器漏抓才红)。
3. **退出码三态**:run_eval 的 0/1/2(通过/回归/infra)与 generate 的 0/2。
4. **Generation suite 用法**:demo 冒烟命令、真机命令(`python -m evals.generate --case gen_01_mine_rebirth --backend configured`,key 走 `~/.loom/.env` 或项目 `.env`,provider/model 可 `--provider/--model` 覆写)、manifest 字段含义(尤其 tokens/cost=null 的原因、backend_class 与 provider 字段的关系)、「无 seed 不承诺单次可复现,稳定性看多次运行分布」。

- [ ] **Step 4: 全量回归**

Run: `.venv/bin/python -m pytest -q` → 全绿。
Run: `.venv/bin/python -m evals.run_eval --gate; echo "码=$?"` → `✅ 无回归` + `码=0`(Fixture suite 纹丝不动)。

- [ ] **Step 5: Commit**

```bash
git add evals/gen_cases/gen_01_mine_rebirth evals/README.md
git commit -m "$(cat <<'EOF'
feat(eval): 首个 gen case(废矿重生·固定细纲)+ README 重写 Fixture/Generation 二分

gen_01:细纲 overlay 固定章纲,expect 断言细纲要素落正文+禁漂移词;note 写明
demo 只证链路、真机才评质量的诚实边界。README 修 case_02 过时描述(契约语义)、
补退出码三态与 Generation 用法/manifest 字段/不可复现声明。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 控制者验收(无代码改动)

**Files:** 无;只验证。

- [ ] **Step 1: 全量 + 双 suite 自跑**

Run: `.venv/bin/python -m pytest -q` → 全绿(562 基线 + Phase 1 新增,预计 ~575)。
Run: `.venv/bin/python -m evals.run_eval --gate; echo $?` → 0(CI 契约无恙)。
Run: `LOOM_DEMO=1 .venv/bin/python -m evals.generate; echo $?` → 0,runs 目录新增一条,`git status --short` 不含 evals/runs/。

- [ ] **Step 2: 隔离与可追溯抽查**

- `evals/gen_cases/` 在 demo 跑后 `git status` 零改动(金标不被写)。
- 打开最新 `evals/runs/<id>/manifest.json`:git_commit=当前 HEAD 短 sha、backend_class=DemoBackend、n_calls 与调用数契约一致(7,细纲旁路)、tokens/cost=null 且 notes 写明原因。
- `report.json` 的 graders 里有「关键要素/长度达标/去AI味·确定性」(复用而非另写)。

- [ ] **Step 3: 真机验收路径确认(不自动跑)**

确认 README 里真机命令可照抄;向用户报告:真机验收(改一条真实 prompt → Generation 输出可观察变化)需要花真实 API 费用,命令已备好,等用户择时跑或授权跑。

- [ ] **Step 4: 汇报 + 更新 ledger**

---

## Phase 2-4 预告(各自另立计划)

| 期 | 内容 | 前置 |
|---|---|---|
| Phase 2 | 评测集 schema/rubric + 小型平衡数据集(dev/calibration/holdout);**第二人工标注者是人工环节,工具先行、数字留位** | Phase 1 |
| Phase 3 | Judge 结构化 JSON verdict + kappa/PRF meta-eval(合成夹具 TDD)+ 预注册阈值进 config | Phase 2 |
| Phase 4 | 分层 CI(PR=fixture 零 key;手动/定时=generation+真 Judge,workflow_dispatch+schedule,fork 无 secrets)+ JSON/MD 报告 artifact | Phase 3 |
