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
