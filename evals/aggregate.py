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

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Distribution:
    median: float | None
    lo: float | None
    hi: float | None
    n_valid: int
    n_total: int
    scores: list[float] | None = None   # 原始分数(升序)。判据要它,见 mannwhitney_p 的 docstring

    def as_dict(self) -> dict:
        return asdict(self)


def distribution(values: list[float | None]) -> Distribution:
    """一串分数(None=该次 infra 或该项本次不进分布)→ 中位数 + 区间 + 有效/总次数 + 原始分数。

    lo/hi 是 **min~max**,只作描述性展示(这批样本铺多开),**不再当判据**——
    它不随 N 收窄,反而 N 越大越容易抽到极端值、区间越宽。判据见 mannwhitney_p。
    """
    n_total = len(values)
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return Distribution(None, None, None, 0, n_total, None)
    mid = len(xs) // 2
    med = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    return Distribution(round(med, 4), round(xs[0], 4), round(xs[-1], 4), len(xs), n_total,
                        [round(x, 4) for x in xs])


# ── 两批是否真的不同:Mann-Whitney U ────────────────────────────────────────
# 为什么换掉 min~max 重叠判据(真事故,2026-08-10):
#   设定师·锚点篇幅 改前 [0.0 … 0.934] vs 改后 [0.537 … 1.0],10 v 10。
#   min~max 判「重叠 → 分不出」,但精确检验 p=0.0245——**那是个假阴性,把一个真实的改进
#   判成了没变化**。原因:min~max 描述的是【样本铺多开】,不是【统计量有多不确定】,
#   它不随 N 收窄。加样本只会让它更容易抽到极端值、区间更宽,于是**任何 N 都判不开**。
# 为什么不是 IQR:IQR 同样描述分布的散布,同样不随 N 收窄,换成它等于没修。
# 为什么不是中位数置信区间:方向对(随 N 收窄),但本数据结极多(大量 1.0),
#   实测 10v10 时 CI 仍恒重叠,分辨力不够。
# 为什么秩检验合适:它比的是【两批的秩分布】,对结稳健、分布无关,且随 N 收窄。

_EXACT_MAX_N = 60          # 总样本数上限:超过就退正态近似(DP 表会太大)


def _midranks(values: list[float]) -> list[float]:
    """并列取平均秩(midrank)。结多时必须这么做,否则秩和有偏。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    rk = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j + 2) / 2          # 1-based 平均秩
        for t in range(i, j + 1):
            rk[order[t]] = avg
        i = j + 1
    return rk


def _exact_p_from_ranks(ranks: list[float], n1: int, obs_sum2: int) -> float:
    """精确双尾 p:枚举「从这些秩里取 n1 个」的所有秩和(DP,不是暴力组合)。

    秩是 .5 的倍数(midrank),整体 ×2 变成整数好做 DP。
    dp[k][s] = 取 k 个、秩和(×2)为 s 的组合数。
    """
    r2 = [int(round(r * 2)) for r in ranks]
    total_sum = sum(r2)
    max_s = sum(sorted(r2, reverse=True)[:n1])
    dp = [[0] * (max_s + 1) for _ in range(n1 + 1)]
    dp[0][0] = 1
    for r in r2:
        for k in range(min(n1, len(r2)) - 1, -1, -1):
            row = dp[k]
            nxt = dp[k + 1]
            for s in range(max_s - r, -1, -1):
                if row[s]:
                    nxt[s + r] += row[s]
    counts = dp[n1]
    total = sum(counts)
    if not total:
        return 1.0
    # 双尾:以「离均值的距离 ≥ 观测距离」为极端。均值 = n1 * 总秩和 / N
    mean2 = n1 * total_sum / len(r2)
    obs_dev = abs(obs_sum2 - mean2)
    extreme = sum(c for s, c in enumerate(counts) if c and abs(s - mean2) >= obs_dev - 1e-9)
    return min(extreme / total, 1.0)


def _normal_p_from_ranks(ranks: list[float], values: list[float], n1: int, obs_sum: float) -> float:
    """正态近似 + 结校正。只在样本大到做不了精确检验时用。

    实测警告:结很多时它和精确 p 能差 0.1 以上(润色师·AI味下降 一例:0.263 vs 0.370),
    足以在阈值附近翻盘。所以能精确就绝不用它。
    """
    n2 = len(values) - n1
    n = len(values)
    mu = n1 * (n + 1) / 2
    tie = Counter(values)
    tsum = sum(t ** 3 - t for t in tie.values())
    var = n1 * n2 / 12 * ((n + 1) - tsum / (n * (n - 1))) if n > 1 else 0.0
    if var <= 0:
        return 1.0
    z = (abs(obs_sum - mu) - 0.5) / math.sqrt(var)
    return math.erfc(z / math.sqrt(2))


def mannwhitney_p(a: list[float], b: list[float]) -> tuple[float, str]:
    """两批分数是否来自同一分布 → (双尾 p, 用的哪种方法)。

    能精确就精确(总样本 ≤60),否则退正态近似——返回值第二项如实标明用了哪种,
    别让读者以为所有 p 都是同一成色。任一边为空 → (1.0, "无数据"):不造结论。
    """
    if not a or not b:
        return 1.0, "无数据"
    values = list(a) + list(b)
    ranks = _midranks(values)
    obs_sum = sum(ranks[:len(a)])
    if len(values) <= _EXACT_MAX_N:
        return _exact_p_from_ranks(ranks, len(a), int(round(obs_sum * 2))), "精确"
    return _normal_p_from_ranks(ranks, values, len(a), obs_sum), "正态近似"


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
