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
import unicodedata
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

from .aggregate import aggregate_runs, overlaps
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
    # 附赠扫描是额外模型调用,评测缺省关(与既有 golden 同口径);case 可显式打开,
    # 好让除虫这条链也有 eval 覆盖——此前它被硬编码关死,评测里从来没跑过。
    cfg.continuity_scan = bool(case.get("continuity_scan", False))
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


def _cjk_ljust(s: str, width: int) -> str:
    """按「东亚宽字符占 2 列」估算的定宽左对齐。

    Python 的 f"{s:<N}" 按码点数补空格——CJK 字符在等宽终端里占 2 列,同一个 N 对
    中文文本和纯 ASCII 文本补出来的视觉宽度并不一样,混排时列对不齐。这里只做最
    小可用的宽度估算(西文/半角=1,中日韩全角=2),不追求 Unicode 断行等复杂规则。
    """
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)
    return s + " " * max(0, width - w)


def _display_item(role: str, name: str) -> str:
    """grader 名字自带角色前缀(如「设定师·硬设定专名」)。展示层若已单独有一列/一次
    印过角色(棒级归因小结的「棒」列、--compare 打印的角色前缀),就不该在体检项文本里
    再重复一遍——否则读出来是「设定师·设定师·硬设定专名」(Important-3)。
    """
    prefix = f"{role}·"
    return name[len(prefix):] if name.startswith(prefix) else name


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
            label = _display_item(role, name)
            if d["n_valid"] == 0:
                # d["n_valid"]==0 但走到这里说明 agg["n_valid"]>0(全 infra 已在上面早退)——
                # 精确可拆:agg["n_total"]-agg["n_valid"] 次是整体 infra(这一项那次跑
                # 根本没跑到评分),其余 agg["n_valid"] 次是有效跑但这一项本身
                # skipped/not-measurable。两种成因不同,不该继续含糊写「全 skipped 或全
                # infra」——那句话既没说是哪种,也暗示了"整体 infra"在这里可能发生
                # 100%(其实上面已经排除)。
                n_infra = agg["n_total"] - agg["n_valid"]
                n_unmeasured = agg["n_valid"]
                if n_infra == 0:
                    why = f"{n_unmeasured} 次有效运行里这项都 skipped/not-measurable"
                else:
                    why = (f"{n_infra} 次整体 infra + "
                           f"{n_unmeasured} 次有效运行里这项都 skipped/not-measurable")
                lines.append(f"| {role} | {label} | — | — | 0/{d['n_total']}({why}) |")
            else:
                lines.append(f"| {role} | {label} | {d['median']} | "
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
    # batch_id 撞车重试:与 generate_one 的 run_id(见上方 246-251 行)同款处理——
    # time.strftime 只到秒,近乎零延迟的 DemoBackend 完全可能让同 case 同 repeat
    # 的两次调用落进同一秒,不重试就是无预警的 FileExistsError,跳出退出码契约。
    base = f"{time.strftime('%Y%m%d-%H%M%S')}_batch_{case['id']}_x{repeat}"
    batch_id, n = base, 1
    while (runs_dir / batch_id).exists():
        n += 1
        batch_id = f"{base}-{n}"
    batch = runs_dir / batch_id
    (batch / "runs").mkdir(parents=True)

    reports: list[dict | None] = []
    for i in range(repeat):
        wd = (workdir_root / f"w{i}") if workdir_root else None
        try:
            if wd:
                wd.mkdir(parents=True, exist_ok=True)
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


def compare_batches(batch_a: Path, batch_b: Path) -> dict:
    """两批对比:a=改动前,b=改动后。

    **最重要的一条纪律:区间重叠就判「分不出」,不宣称改进。**
    生成链路 temperature=0.9 写死、无 seed,中位数涨了一点很可能只是这次运气好。

    遍历键集合取 a∪b 而非只取 a——只取 a 会把「b 独有的 (role, item)」静默丢掉
    (两批 case 不同、或某棒在其中一批被旁路时确会发生),那样改完 prompt 新增的
    体检项、或某一批完全没跑到的棒,会在报告里悄悄消失,与「不让人漏看变化」
    的宗旨相悖。b 独有项 before=None → 判「无数据」,不是当它不存在。
    """
    sa = json.loads((batch_a / "summary.json").read_text(encoding="utf-8"))
    sb = json.loads((batch_b / "summary.json").read_text(encoding="utf-8"))
    a_steps, b_steps = sa.get("steps", {}), sb.get("steps", {})

    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for role, items in a_steps.items():
        for name in items:
            key = (role, name)
            if key not in seen:
                seen.add(key)
                keys.append(key)
    for role, items in b_steps.items():
        for name in items:
            key = (role, name)
            if key not in seen:
                seen.add(key)
                keys.append(key)

    items_out, improved, regressed = [], 0, 0
    for role, name in keys:
        da = a_steps.get(role, {}).get(name)
        db = b_steps.get(role, {}).get(name)
        if not da or not db or da.get("median") is None or db.get("median") is None:
            verdict, delta = "无数据", None
        elif overlaps(da, db):
            delta = round(db["median"] - da["median"], 4)
            verdict = "分不出(区间重叠)"
        else:
            delta = round(db["median"] - da["median"], 4)
            verdict = "改进" if delta > 0 else "回归"
            if verdict == "改进":
                improved += 1
            else:
                regressed += 1
        items_out.append({
            "step": role, "item": name, "before": da, "after": db,
            "delta": delta, "verdict": verdict,
            # 有效/总次数直接摊平进 item——下游读者(含 CLI 打印)不该还要挖 before/after
            # 才看得出这条判据是几次跑撑出来的。任一边没数据(a∪b 独有项)则为 None。
            "n_valid_before": da.get("n_valid") if da else None,
            "n_total_before": da.get("n_total") if da else None,
            "n_valid_after": db.get("n_valid") if db else None,
            "n_total_after": db.get("n_total") if db else None,
        })
    return {"case_id": sa.get("case_id"), "items": items_out,
            "n_improved": improved, "n_regressed": regressed}


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
    ap.add_argument("--repeat", type=int, default=1,
                    help="同一 case 连跑 N 次取分布(对抗 temp=0.9 无 seed 的噪声;N≥2 才有分布)")
    ap.add_argument("--compare", nargs="+", metavar="BATCH",
                    help="对比两个批次目录(改动前 改动后):区间重叠即判「分不出」,不宣称改进")
    args = ap.parse_args(argv)

    if args.compare:
        if len(args.compare) != 2:
            print("✗ --compare 需要恰好两个批次目录:<改动前> <改动后>")
            return 2
        a, b = Path(args.compare[0]), Path(args.compare[1])
        if not (a / "summary.json").is_file() or not (b / "summary.json").is_file():
            print(f"✗ 批次目录缺 summary.json:{a} / {b}")
            return 2
        sa = json.loads((a / "summary.json").read_text(encoding="utf-8"))
        sb = json.loads((b / "summary.json").read_text(encoding="utf-8"))
        # 任一批 0 次有效运行 → 拒绝出结论,退出 2。不拦的话 compare_batches 会把每项
        # 都判成「无数据」,n_regressed==0 让 CLI 返回 0——脚本读到 0 就当"比对干净、
        # 没有回归",这是不造数红线要挡的假阴性(Important-2)。
        if sa.get("n_valid", 0) == 0 or sb.get("n_valid", 0) == 0:
            print(f"✗ 有批次 0 次有效运行,拒绝出结论:"
                  f"{a.name}(n_valid={sa.get('n_valid')}) / {b.name}(n_valid={sb.get('n_valid')})")
            return 2
        # 两批 case_id 不一致 → 拒绝比对。不拦的话会拿 a 的 case_id 当标题,继续对
        # 不同 case 的分布逐项算改进/回归——数字看着有意义,其实是拿苹果比橘子。
        if sa.get("case_id") != sb.get("case_id"):
            print(f"✗ 两批的 case_id 不一致,拒绝比对:"
                  f"{a.name}={sa.get('case_id')!r} / {b.name}={sb.get('case_id')!r}")
            return 2
        res = compare_batches(a, b)
        print(f"── {res['case_id']}:{a.name} → {b.name} ──")
        for it in res["items"]:
            d = "—" if it["delta"] is None else f"{it['delta']:+.4f}"
            # 样本数同屏可见:1-of-N 的零宽区间和 N-of-N 的实区间不能打印得一模一样,
            # 否则「区间重叠即分不出」这条纪律会被「区间本身就是假的」绕过去。
            nb = "?" if it["n_valid_before"] is None else f"{it['n_valid_before']}/{it['n_total_before']}"
            na = "?" if it["n_valid_after"] is None else f"{it['n_valid_after']}/{it['n_total_after']}"
            # it['item'] 已经是完整 grader 名、自带角色前缀(如「写手·必含要素」)——
            # 不再额外拼 it['step'],否则每行都印成「写手·写手·必含要素」(Important-3)。
            print(f"  {it['verdict']:<16} {_cjk_ljust(it['item'], 24)} "
                  f"Δ中位数 {d}  n={nb} → {na}")
        print(f"\n改进 {res['n_improved']} 项 · 回归 {res['n_regressed']} 项 · "
              f"其余分不出(区间重叠或无数据)")
        return 1 if res["n_regressed"] else 0

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


if __name__ == "__main__":
    import sys
    sys.exit(main())
