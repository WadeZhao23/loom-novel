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
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from loom.evalapi import (
    get_backend,
    load_config,
    save_config,
    scaffold_init,
    run_pipeline,
)

from .harness import run_case
from .metering import MeteringBackend

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
