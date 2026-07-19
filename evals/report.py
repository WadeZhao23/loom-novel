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
