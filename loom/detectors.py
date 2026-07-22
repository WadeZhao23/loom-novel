"""本地确定性检测器(纯规则、不调 LLM、不新加依赖)。

每个检测器是一个 text -> list[Issue] 的函数,注册在 agents.DETECTORS 工厂注册表中。
规则只挑具体句式模式、不打分,守 ADR-0006「不阻断」。
"""

from __future__ import annotations

import re
from typing import Callable

from .gates import Issue

DetectorFn = Callable[[str], list[Issue]]


# ── 成语堆砌检测 ──────────────────────────────────────────────────────────
# 成语大多为 4 字,在 200 字窗口内出现过多即标记。

# 四字格:连续的 4 个汉字且前后非汉字
_CJK = "\u4e00-\u9fff"
_CHENGYU_PAT = re.compile(rf"[{_CJK}]{{4}}")
_CHENGYU_WINDOW = 200
_CHENGYU_THRESHOLD = 5


def detect_chengyu_piling(text: str) -> list[Issue]:
    """检测成语堆砌:任意 200 字窗口内 >=4 个四字格则报硬伤。
    使用 finditer 做非重叠匹配,叠加最小间距 2 字防切分真实成语。"""
    issues: list[Issue] = []
    # finditer 天然非重叠,再过滤:相邻匹配之间至少隔 1 个非匹配字符
    raw = [(m.start(), m.group()) for m in _CHENGYU_PAT.finditer(text)]
    matches = []
    for start, word in raw:
        if matches and start - (matches[-1][0] + 4) < 1:
            continue  # 相邻不隔字符 → 是前一个 4 字格的尾巴,不算新成语
        matches.append((start, word))
    if len(matches) < _CHENGYU_THRESHOLD:
        return issues

    for i in range(len(matches)):
        start_pos = matches[i][0]
        count = 1
        for j in range(i + 1, len(matches)):
            if matches[j][0] - start_pos <= _CHENGYU_WINDOW:
                count += 1
            else:
                break
        if count >= _CHENGYU_THRESHOLD:
            end_idx = min(i + count, len(matches)) - 1
            evidence = text[start_pos:matches[end_idx][0] + 4]
            evidence = evidence[:80] if len(evidence) > 80 else evidence
            issues.append(Issue(
                kind="成语堆砌",
                desc=f"连续 {count} 个四字格密集出现(阈值 {_CHENGYU_THRESHOLD})",
                evidence=evidence,
                category="AI腔-句式",
                severity=3,
            ))
            break
    return issues


# ── 排比句滥用检测 ────────────────────────────────────────────────────────
# 排比:连续 3+ 行以相同 2-5 字开头。

_PARALLEL_PREFIX_RE = re.compile(rf"^([{_CJK}\w]{{2,3}})")


def detect_parallel_abuse(text: str) -> list[Issue]:
    """检测排比句滥用:连续 >=3 行以相同 2-5 字开头 -> 报硬伤。"""
    issues: list[Issue] = []
    lines = text.splitlines()
    if len(lines) < 3:
        return issues

    i = 0
    while i <= len(lines) - 3:
        m0 = _PARALLEL_PREFIX_RE.match(lines[i].strip())
        if not m0:
            i += 1
            continue
        prefix = m0.group(1)
        if len(prefix) < 2:
            i += 1
            continue
        count = 1
        for j in range(i + 1, len(lines)):
            m = _PARALLEL_PREFIX_RE.match(lines[j].strip())
            if m and m.group(1) == prefix:
                count += 1
            else:
                break
        if count >= 3:
            ev = "\n".join(lines[i:i + count])[:100]
            issues.append(Issue(
                kind="排比句滥用",
                desc=f"连续 {count} 行以「{prefix}」开头构成排比",
                evidence=ev,
                category="AI腔-句式",
                severity=3,
            ))
            i += count
        else:
            i += 1
    return issues


# ── 转折词密集检测 ────────────────────────────────────────────────────────
_BUT_WORDS = ("但是", "然而", "不过", "可是", "却", "虽然",
              "尽管", "即便", "却又", "反倒是", "可谓")
_BUT_RE = re.compile("|".join(re.escape(w) for w in _BUT_WORDS))
_BUT_WINDOW = 150
_BUT_THRESHOLD = 3


def detect_excessive_transitions(text: str) -> list[Issue]:
    """检测转折词密集使用:任意 150 字窗口内 >=3 个转折词 -> 报硬伤。"""
    issues: list[Issue] = []
    matches = [(m.start(), m.group()) for m in _BUT_RE.finditer(text)]
    if len(matches) < _BUT_THRESHOLD:
        return issues

    for i in range(len(matches)):
        start_pos = matches[i][0]
        count = 1
        for j in range(i + 1, len(matches)):
            if matches[j][0] - start_pos <= _BUT_WINDOW:
                count += 1
            else:
                break
        if count >= _BUT_THRESHOLD:
            end_idx = min(i + count, len(matches)) - 1
            end_pos = matches[end_idx][0] + len(matches[end_idx][1])
            window_text = text[start_pos:end_pos]
            ev = window_text[:80] if len(window_text) > 80 else window_text
            words = ", ".join(m[1] for m in matches[i:i + count][:5])
            issues.append(Issue(
                kind="转折词密集",
                desc=f"连续 {count} 个转折词密集出现({words})",
                evidence=ev,
                category="AI腔-句式",
                severity=3,
            ))
            break
    return issues
