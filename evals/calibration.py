"""校准 meta-eval 纯函数:Cohen's κ + 每维 P/R/F1。零依赖手写(不引 sklearn)。

只算一致性/查全查准,不产任何「总体分」。11 例数据集每维正例仅 1-2 个,总体准确率
会被大量 absent 格灌水,故用 κ(扣偶然一致)+ 分维 recall(高代价维单独看)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .dataset import DIMENSIONS


def cohen_kappa(a: list, b: list) -> float:
    """两个等长标签序列的 Cohen's κ。完全一致→1.0;单一类别且一致→1.0。"""
    if len(a) != len(b):
        raise ValueError(f"κ 两序列须等长:{len(a)} != {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("κ 空序列无定义")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe >= 1.0:                       # 单一类别:两方都恒判同一类
        return 1.0 if po == 1.0 else 0.0
    return round((po - pe) / (1 - pe), 4)


@dataclass
class PRF:
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None

    def as_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": self.precision, "recall": self.recall, "f1": self.f1}


def prf_for_dimension(gold: list[bool], pred: list[bool]) -> PRF:
    """单维度跨 case 的 P/R/F1。分母为 0 的指标记 None(未定义,不伪造 0/1)。"""
    if len(gold) != len(pred):
        raise ValueError(f"P/R/F1 两序列须等长:{len(gold)} != {len(pred)}")
    tp = sum(1 for g, p in zip(gold, pred) if g and p)
    fp = sum(1 for g, p in zip(gold, pred) if (not g) and p)
    fn = sum(1 for g, p in zip(gold, pred) if g and (not p))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    precision = round(precision, 4) if precision is not None else None
    recall = round(recall, 4) if recall is not None else None
    return PRF(tp, fp, fn, precision, recall, f1)


TARGETS_PATH = Path(__file__).resolve().parent / "calibration" / "targets.json"
GATING_PATH = Path(__file__).resolve().parent / "calibration" / "gating.json"


def load_targets() -> dict:
    return json.loads(TARGETS_PATH.read_text(encoding="utf-8"))


def load_gating() -> dict:
    return json.loads(GATING_PATH.read_text(encoding="utf-8"))


def gate_policy(dimension: str, gating: dict) -> str:
    """维度的门禁策略;未声明的维度默认 observe(最保守,不拦截)。"""
    return gating.get("dimensions", {}).get(dimension, "observe")


def gate_hard_dimensions(report: dict, gating: dict, targets: dict) -> tuple[bool, list, list]:
    """对每个 policy=hard 的维度,断言 recall ≥ high_cost_recall target。
    recall=None(无金标正例/未评)→ 记 warning 跳过,不算失败(测不了的不能拦)。
    返回 (ok, failures, warnings)。这是「校准过的 Judge 必须保持校准」的元门禁。"""
    target = targets["high_cost_recall"]
    jvg = report.get("judge_vs_gold", {})
    failures, warnings = [], []
    for dim, policy in gating.get("dimensions", {}).items():
        if policy != "hard":
            continue
        m = jvg.get(dim)
        recall = m.get("recall") if m else None
        if recall is None:
            warnings.append(f"{dim}:无金标正例/未评,无法门禁(跳过)")
            continue
        if recall < target:
            failures.append(f"{dim}:recall {recall} < 目标 {target}")
    return (not failures, failures, warnings)


def evaluate_against_targets(metric_value: float | None, target: float) -> dict:
    """指标 vs 预注册阈值的纯比较。value=None(无数据)→ met=None(待测,非未达标)。"""
    met = None if metric_value is None else (metric_value >= target)
    return {"target": target, "value": metric_value, "met": met}


def present_matrix(cases_labels: list[dict]) -> dict:
    """[{labels:[{dimension,present}...]}...] → {dimension: [present per case]}。"""
    out = {d: [] for d in DIMENSIONS}
    for case in cases_labels:
        by_dim = {l["dimension"]: bool(l["present"]) for l in case["labels"]}
        for d in DIMENSIONS:
            out[d].append(by_dim.get(d, False))
    return out


def verdict_matrix(judge_results: list) -> dict:
    """[JudgeResult(非 infra)] → {dimension: [present per case]}。

    infra 的 case 必须在调用前被调用方滤除——绝不在此处静默把「后端/解析失败」当成
    「Judge 判全维干净」(那会伪造 8 维全 False,悄悄拉低高代价维 recall)。遇到任何
    infra_error(或空 verdicts)一律 fail-loud,而不是默默吞掉。
    """
    out = {d: [] for d in DIMENSIONS}
    for r in judge_results:
        if r.infra_error or not r.verdicts:
            raise ValueError(
                f"verdict_matrix 拒绝 infra case(case_id={r.case_id!r})——"
                "infra case 必须在调用前滤除,别喂进 verdict_matrix,否则会把「后端/解析"
                "失败」静默伪装成「Judge 判全维干净」污染 P/R/F1。"
            )
        by_dim = {v.dimension: v.present for v in r.verdicts}
        for d in DIMENSIONS:
            out[d].append(by_dim.get(d, False))
    return out


def aligned_matrices(gold_cases: list[dict], judge_results: list) -> tuple[dict, dict, list]:
    """按 case_id 对齐金标与 Judge 结果,滤掉 infra,返回 (gold_matrix, judge_matrix, dropped_infra_ids)。

    保证两 matrix 同 case 顺序(按 gold_cases 顺序取两侧都在的 case),从结构上杜绝
    「等长但顺序不同」的静默位置错位——build_calibration_report 按下标 zip 两个已塑好
    的 matrix,不检查 case_id,若调用方手工对齐时两侧丢了不同 case 但恰好等长,
    prf_for_dimension 的等长守卫挡不住。Phase 4 接线应走这个入口,而非手工对齐。

    gold_cases 每项需含 'id' 和 'labels';judge_results 是 list[JudgeResult]。
    """
    dropped = [r.case_id for r in judge_results if r.infra_error]
    ok = {r.case_id: r for r in judge_results if not r.infra_error}
    gold_by_id = {c["id"]: c for c in gold_cases}
    aligned_ids = [c["id"] for c in gold_cases if c["id"] in ok]   # 按 gold 顺序取交集
    gold_matrix = present_matrix([gold_by_id[i] for i in aligned_ids])
    judge_matrix = verdict_matrix([ok[i] for i in aligned_ids])    # 此时 ok 里都非 infra,verdict_matrix 不会 raise
    return gold_matrix, judge_matrix, dropped


def build_calibration_report(gold: dict, judge: dict | None, human_pairs: list | None,
                              dropped_infra: list | None = None, n_total: int | None = None) -> dict:
    """校准报告。judge/human 缺 → 对应段如实留空位(待真机/待标注),绝不造数。

    dropped_infra/n_total(可选,默认 None):披露因 infra 掉出的 case——若调用方对齐后
    悄悄丢了 dropped,报告会把「子集上算的 P/R/F1」标成「已计算」而不说明只在几例上算。
    传了 dropped_infra 才会在 coverage 段体现掉数;缺省时 coverage 段如实标「待真机/未评」。
    """
    # judge 是 {dim:[bool per evaluated case]}。全部 case 都 infra 时 aligned_matrices 仍返回
    # 非空 dict、但每维值为空 list(judge_matrix={dim:[]})——`if judge:` 对此判真,会走进
    # prf_for_dimension/cohen_kappa 对空序列计算,cohen_kappa([],[]) 直接 raise ValueError,
    # 让「全 infra 时如实报告 coverage」这条兜底路径本身崩溃。改用 has_evaluated(至少 1
    # 个已评 case)做守卫:无已评例 → 跳过度量、judge_vs_gold 留空,不产假数也不崩。
    n_eval = len(next(iter(judge.values()))) if judge else 0
    has_evaluated = bool(judge) and n_eval > 0

    if has_evaluated:
        judge_vs_gold_status = "已计算"
    elif not judge:
        judge_vs_gold_status = "待真机"
    else:
        judge_vs_gold_status = "全infra掉出,无可评例"

    report: dict = {
        "dimensions": list(DIMENSIONS),
        "targets": load_targets(),
        "judge_vs_gold": {},
        "judge_vs_gold_status": judge_vs_gold_status,
        "human_human_kappa": {"status": "待标注", "n": 0, "value": None,
                              "note": "人-人一致性需两名标注者对 calibration split 独立标注后计算"},
    }
    if has_evaluated:
        for d in DIMENSIONS:
            report["judge_vs_gold"][d] = prf_for_dimension(gold[d], judge[d]).as_dict()
        flat_gold = [x for d in DIMENSIONS for x in gold[d]]
        flat_judge = [x for d in DIMENSIONS for x in judge[d]]
        report["judge_vs_gold_kappa"] = cohen_kappa(flat_gold, flat_judge)
    if human_pairs:
        a = [x for pair in human_pairs for x in pair[0]]
        b = [x for pair in human_pairs for x in pair[1]]
        report["human_human_kappa"] = {"status": "已计算", "n": len(a),
                                       "value": cohen_kappa(a, b), "note": ""}

    if has_evaluated:
        cov_status = "已计算"
    elif not judge:
        cov_status = "待真机"
    else:
        cov_status = "全infra掉出,无可评例"
    report["coverage"] = {
        "status": cov_status,
        "n_total": n_total,
        "n_evaluated": n_eval,
        "n_infra_dropped": len(dropped_infra) if dropped_infra is not None else None,
        "dropped_case_ids": list(dropped_infra) if dropped_infra is not None else [],
    }
    return report


def calibrate(gold_cases: list, judge_results: list) -> dict:
    """端到端安全入口:对齐(滤 infra)→ 算 P/R/F1+κ → 报告自动披露掉数。
    Phase 4 接线只准走这个,别手工 aligned_matrices 后把 dropped 丢了(会掩盖 infra 掉数)。"""
    gold_matrix, judge_matrix, dropped = aligned_matrices(gold_cases, judge_results)
    return build_calibration_report(gold_matrix, judge_matrix, human_pairs=None,
                                    dropped_infra=dropped, n_total=len(judge_results))


def _md_report(report: dict) -> str:
    lines = ["# LLM-Judge 校准报告", "",
             f"预注册阈值:{report['targets']['note']}", ""]
    cov = report.get("coverage", {})
    if cov.get("n_infra_dropped"):
        lines += [f"⚠ 覆盖:共 {cov['n_total']} 例,{cov['n_infra_dropped']} 例因 infra 掉出"
                  f"({cov['dropped_case_ids']}),P/R/F1 只在 {cov['n_evaluated']} 例上算。", ""]
    elif cov.get("status") == "待真机":
        lines += ["覆盖:待真机(未跑真实 Judge)。", ""]
    lines += ["## 人-人一致性",
             f"- 状态:{report['human_human_kappa']['status']}(N={report['human_human_kappa']['n']})",
             f"- κ:{report['human_human_kappa']['value']}", "",
             f"## Judge vs 金标(状态:{report['judge_vs_gold_status']})", ""]
    if report["judge_vs_gold"]:
        lines.append("| 维度 | tp | fp | fn | precision | recall | f1 |")
        lines.append("|---|---|---|---|---|---|---|")
        for d in report["dimensions"]:
            m = report["judge_vs_gold"][d]
            lines.append(f"| {d} | {m['tp']} | {m['fp']} | {m['fn']} | "
                         f"{m['precision']} | {m['recall']} | {m['f1']} |")
        lines.append("")
        lines.append(f"整体 Judge-金标 κ:{report.get('judge_vs_gold_kappa')}")
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "report.json"
    m = out_dir / "report.md"
    j.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    m.write_text(_md_report(report), encoding="utf-8")
    return j, m
