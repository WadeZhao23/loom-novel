"""N 次运行 → 分布。

为什么需要它:生成链路没有 seed 通道,OpenAICompatBackend.complete 写死
temperature=0.9(loom/backends.py:280,311),同一 case 跑两次不保证字符级甚至
语义级一致。所以「这次 prompt 改动到底有没有让生成变好」必须看**多次运行的
分数分布**,而不是拿单次结果定生死——evals/README.md 早就写下了这条方法论,
本模块把它从文档声明变成工具行为。

红线(不造数):N 次里 M 次 infra,就照实记 n_valid=M / n_total=N,
**绝不用 M 次的均值冒充 N 次**。全 infra 时各项统计量为 None,不是 0.0。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Distribution:
    median: float | None
    lo: float | None
    hi: float | None
    n_valid: int
    n_total: int

    def as_dict(self) -> dict:
        return asdict(self)


def distribution(values: list[float | None]) -> Distribution:
    """一串分数(None=该次 infra 或该项本次不进分布)→ 中位数 + 区间 + 有效/总次数。"""
    n_total = len(values)
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return Distribution(None, None, None, 0, n_total)
    mid = len(xs) // 2
    med = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    return Distribution(round(med, 4), round(xs[0], 4), round(xs[-1], 4), len(xs), n_total)


def overlaps(a: dict, b: dict) -> bool:
    """两个分布的区间是否重叠。重叠 = **不得宣称有改进**。

    任一边没有有效数据 → 保守判重叠:没数据不等于「分开了」,不造结论。
    """
    if not a or not b or a.get("lo") is None or b.get("lo") is None:
        return True
    return a["lo"] <= b["hi"] and b["lo"] <= a["hi"]


def aggregate_runs(step_reports: list[dict | None]) -> dict:
    """N 份 step_report(None=该次 run 整体 infra)→ 逐棒逐项的分布 + 最弱棒。

    每个 (role, item) 的分数列表长度恒等于 n_total,与 infra run 落在哪个位置无关:
    先扫一遍所有 valid report 收集完整的 (role, item) 键集合,再对每个 run(含 None)
    按这份完整键集合逐一取值——不是像素级遍历时"顺手"给已见过的 item 补 None
    (那样一来,若第一个 run 恰好就是整体 infra,当时 item_scores 还是空的,
    该 run 补不到任何 None,对应 item 的列表就会比 n_total 短一格)。

    weakest 用**多数决**:超过半数的有效 run(分母是 len(valid),不是"有意见的
    valid run")都点了同一棒,才认它——单次波动不该把归因带偏。
    """
    n_total = len(step_reports)
    valid = [r for r in step_reports if r]
    if not valid:
        return {"n_total": n_total, "n_valid": 0, "steps": {}, "weakest": None}

    # 先收集所有出现过的 (role, item) 键,顺序固定(按首次出现),
    # 保证后面不管 None 落在哪个位置,每个 item 的分数列表长度都严格等于 n_total。
    keys: list[tuple[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    for rep in valid:
        for role, graders in rep.get("steps", {}).items():
            for g in graders:
                key = (role, g["name"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    keys.append(key)

    item_scores: dict[str, dict[str, list[float | None]]] = defaultdict(lambda: defaultdict(list))
    for rep in step_reports:
        steps = (rep or {}).get("steps", {})
        lookup: dict[tuple[str, str], dict] = {
            (role, g["name"]): g for role, graders in steps.items() for g in graders
        }
        for role, name in keys:
            g = lookup.get((role, name))
            if g is None:
                score = None  # 本次 run 整体 infra,或这个 item 这次没出现
            else:
                # 排除判据是 detail 的 [skipped]/[not-measurable] 前缀,不是 gating——
                # gating=False 还覆盖 observe-only 项(如 写手·AI翻转句:weight=0.0,
                # gating=False,但每次都真测了)。这类项若按 gating 排除,会把「真测过
                # 只是不参与门禁」和「genuinely 没测到」混为一谈,前者的分数从此再也
                # 进不了分布/summary/--compare,报告还会把它印成「全 skipped 或全
                # infra」——数字是假的(不造数红线)。
                detail = g.get("detail") or ""
                unmeasured = detail.startswith("[skipped]") or detail.startswith("[not-measurable]")
                score = None if unmeasured else g.get("score")
            item_scores[role][name].append(score)

    steps_out = {
        role: {name: distribution(vals).as_dict() for name, vals in items.items()}
        for role, items in item_scores.items()
    }

    votes = Counter(r["weakest"] for r in valid if r.get("weakest"))
    weakest = None
    if votes:
        top, cnt = votes.most_common(1)[0]
        if cnt * 2 > len(valid):  # 严格多数
            weakest = top

    return {"n_total": n_total, "n_valid": len(valid),
            "steps": steps_out, "weakest": weakest}
