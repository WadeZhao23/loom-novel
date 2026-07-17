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
