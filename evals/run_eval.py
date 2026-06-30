"""eval 命令行入口。

    python -m evals.run_eval                  # 离线跑确定性 grader,打印评分表
    python -m evals.run_eval --judge          # 额外跑 LLM 复审(离线默认走 DemoBackend 占位)
    python -m evals.run_eval --baseline        # 把本次结果存成基线 baseline.json
    python -m evals.run_eval --gate            # 和基线比对,有回归则退出码 1(给 CI 用)

退出码:0=无回归 / 1=有回归(--gate)或加载基线失败。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .harness import (
    aggregate,
    compare_to_baseline,
    load_baseline,
    run_suite,
    save_baseline,
)

HERE = Path(__file__).resolve().parent


def _bar(score: float, width: int = 10) -> str:
    fill = int(round(score * width))
    return "█" * fill + "·" * (width - fill)


def _print_table(results) -> None:
    print(f"\n{'CASE':<26} {'分数':>6}  {'判定':<6} 各 grader")
    print("─" * 78)
    for r in results:
        flag = "✅PASS" if r.passed else "❌FAIL"
        print(f"{r.title[:24]:<26} {r.score:>6.3f}  {flag:<6} {_bar(r.score)}")
        for g in r.graders:
            mark = "✓" if g.passed else ("·" if not g.gating else "✗")
            line = f"      {mark} {g.name:<14} {g.score:>5.3f}  {g.detail}"
            print(line)
            for ev in g.evidence[:4]:
                print(f"          ⤷ {ev}")
    print("─" * 78)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="loom eval harness(开发期/CI 回归评测)")
    ap.add_argument("--cases", type=Path, default=HERE / "cases", help="数据集目录")
    ap.add_argument("--baseline", action="store_true", help="把本次结果存成基线")
    ap.add_argument("--gate", action="store_true", help="和基线比对,有回归则退出码 1(CI 用)")
    ap.add_argument("--judge", action="store_true", help="额外跑 LLM 复审 grader")
    ap.add_argument("--tol", type=float, default=0.05, help="回归容差(分数下滑超过它才算回归)")
    ap.add_argument("--baseline-file", type=Path, default=HERE / "baseline.json")
    args = ap.parse_args(argv)

    backend = None
    if args.judge:
        # 离线默认走 DemoBackend(占位、不联网、不花钱);要真评测:去掉 LOOM_DEMO 并在项目配好 .env/后端。
        os.environ.setdefault("LOOM_DEMO", "1")
        try:
            from loom.backends import get_backend
            from loom.config import Config
            backend = get_backend(Config())
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 无法初始化后端,LLM grader 将跳过:{e}")

    results = run_suite(args.cases, backend=backend, judge=args.judge)
    if not results:
        print(f"✗ 在 {args.cases} 下没找到任何 case(需要 <case>/case.json)。")
        return 1

    _print_table(results)
    summ = aggregate(results)
    print(f"通过率 {summ['passed']}/{summ['cases']} = {summ['pass_rate']:.0%}   "
          f"平均分 {summ['mean_score']:.3f}")
    print("各维度均分:" + " · ".join(f"{k} {v:.2f}" for k, v in summ["per_grader"].items()))

    if args.baseline:
        save_baseline(args.baseline_file, results)
        print(f"\n✓ 已写入基线:{args.baseline_file}")
        return 0

    if args.gate:
        baseline = load_baseline(args.baseline_file)
        if baseline is None:
            print(f"\n✗ 没有基线可比对({args.baseline_file})。先跑一次 --baseline。")
            return 1
        regs = compare_to_baseline(results, baseline, tol=args.tol)
        if regs:
            print("\n❌ 检测到回归:")
            for x in regs:
                print(f"   · {x['case']}:{x['kind']}(基线 {x['was']} → 现在 {x['now']})")
            return 1
        print("\n✅ 无回归(与基线一致或更好)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
