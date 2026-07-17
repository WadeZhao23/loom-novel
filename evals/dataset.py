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
