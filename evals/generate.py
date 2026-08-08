"""Generation suite:对固定输入真调 loom 五 Agent 流水线生成候选正文,再用既有 grader 评。

与 Fixture suite(evals/cases/ + run_eval)的二分:
- Fixture suite 用固定文本验证「评测器没坏」,零 key,进每次 PR CI;
- Generation suite 真调 run_pipeline 验证「被测系统的生成质量」,产物落
  evals/runs/<run_id>/,绝不覆盖数据集金标;手动/定时跑,不进 PR CI。

复用只走 loom.evalapi(生成接缝)。demo 模式(LOOM_DEMO=1 罐头后端)只能证明
链路通,不能证明「prompt 变→输出变」——真机验收用 --backend configured。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from loom.evalapi import (
    PIPELINE,
    get_backend,
    load_config,
    load_ledger,
    outline_path,
    save_config,
    scaffold_init,
    run_pipeline,
)

from .harness import run_case
from .metering import MeteringBackend
from .stepgraders import (
    grade_editor,
    grade_outliner,
    grade_polisher,
    grade_setter,
    grade_writer,
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


def collect_steps(project: Path, chapter_n: int, run_dir: Path,
                  *, bypassed: frozenset[str] = frozenset()) -> dict[str, str | None]:
    """把 ledger 里五棒的完整产出收进 run_dir/steps/,并落一份 steps.json 记状态。

    run_pipeline 对 PIPELINE 里每个 role 都调了 ledger.record_step(role, output, …),
    output 就是该棒产物原文——机制本来就在,此前只是跑完没人收。

    某棒缺席/该被当缺席看待有两种正当原因:
    ①WYSIWYG 旁路——细纲文件本来就存在,大纲师不调模型,直接读文件当产出;
      但 run_pipeline 对旁路棒**同样**无条件 ledger.record_step(agents.py:714,
      不看是走了模型分支还是 WYSIWYG 分支),实测验证过:ledger 里照样有大纲师的
      条目、output 就是那份沿用的细纲。所以"ledger 缺席"本身并不能识别旁路——
      真正的信号是"这一跑开始前细纲文件是否已经存在",调用方(generate_one)在
      跑 pipeline 之前探测好,通过 bypassed 参数告诉这里:这些角色即使 ledger
      有条目也不算"这一跑收集到的产出",照样记 skipped。
    ②断点续跑跳过——resume=True 时半途中断、未处理到的角色,ledger 里是真缺席,
      走下面的兜底分支。
    两种都记 "skipped",**绝不记 0 分**——旁路/跳过不是失败。
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
        if text and role not in bypassed:
            (steps_dir / f"{role}.md").write_text(text, encoding="utf-8")
            out[role] = text
            status[role] = "collected"
        else:
            out[role] = None
            status[role] = "skipped"
    (run_dir / "steps.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


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
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, cwd=HERE)
    except (OSError, subprocess.SubprocessError):
        return "nogit"
    return out.stdout.strip() or "nogit"


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

    # 大纲师 WYSIWYG 旁路探测:必须在 run_pipeline 之前看细纲文件是否已存在——
    # run_pipeline 对旁路棒同样无条件 ledger.record_step(agents.py:714),旁路后
    # 细纲文件依旧非空,事后（跑完再看）分不出"沿用的旧细纲"和"这一跑现生成的细纲"。
    # 探测口径与 agents.py:664 的旁路判据逐字同款:文件存在且非空即旁路。
    outline_file = outline_path(project, case["chapter_n"])
    bypassed = frozenset({"大纲师"}) if (
        outline_file.is_file() and outline_file.read_text(encoding="utf-8").strip()
    ) else frozenset()

    t0 = time.perf_counter()
    _path, final = run_pipeline(project, case["chapter_n"], metered, cfg, resume=False)
    total_s = round(time.perf_counter() - t0, 3)

    steps = collect_steps(project, case["chapter_n"], run_dir, bypassed=bypassed)
    step_report = grade_steps(steps, case)
    (run_dir / "step_report.json").write_text(
        json.dumps(step_report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = _grade_candidate(run_dir, case, final)
    (run_dir / "report.json").write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    write_manifest(run_dir, case_dir, case, cfg, backend_mode,
                   type(metered.inner).__name__, metered, total_s, git_sha)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    import argparse

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
        sr = json.loads((run_dir / "step_report.json").read_text(encoding="utf-8"))
        flag = "✅" if report["passed"] else "❌"
        weak = f"  最弱棒={sr['weakest']}" if sr.get("weakest") else ""
        print(f"{flag} {report['case_id']}  score={report['score']}{weak}  → {run_dir}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
