"""AI 腔「对比句式」本地检测器:抓「不是A而是B / 不是A,是B / 不是A是B」这类高频 AI 翻转句。

只在本地跑、不发 LLM、不消耗 token、**不打分**——命中只产出一条「带原文证据的硬伤」(gates.Issue),
喂进既有的「去AI味」关卡当**确定性地板**,跟 LLM 复审合流(见 agents._GATES['润色师'])。判据是
「命中清单空不空」,不是分数;残留照常进审稿留痕、绝不硬阻断(守 ADR-0006)。

**指纹护栏(像你≠AI腔,守 ADR-0002)**:命中前先比对【写作指纹】的 anchor 例句——是作者逐字签名
的句子就豁免;并且默认**不报跨句号的「。是」翻转**(cross_sentence=False)——因为句号切断的并列
否定常是作者的声音(「那不是笑。」「不是忍。是不在意。」),逗号并排才是 AI 写法。只报高精度的
AI 形态:紧贴「而是」、软分隔后的「,是/,而是」、以及同句无分隔的「不是A是B」。

检测算法移植自 oh-story-claudecode 的 `skills/story-deslop/scripts/check-ai-patterns.js`
(MIT License, Copyright (c) 2025-2026 oh-story-claudecode),用 Python 重写;按 Loom「指纹优先」
把跨句号翻转收敛为可选(默认关)。两边都是 MIT,保留其版权与许可声明于此。
"""
from __future__ import annotations

import re
from pathlib import Path

from .gates import Issue
from .paths import FINGERPRINT_REL as REL_FINGERPRINT  # 指纹路径常量收敛到 paths(与 fingerprint 同源)

_STOP = set("。！？!?\n")
_SOFT_SEP = set("，,、；;：:")
_HARD_SEP = set("。.！!？?")
_MAX_NEG_SPAN = 80   # 否定铺垫最多向后扫多少字找肯定翻转
_MAX_POS_SPAN = 80   # 肯定项最多截取多少字作证据,免得引一长段
_EITHER_OR_PREV = set("不就也")  # 「不是A就是B / 也是B」里紧贴的「是」是连词,不是肯定项系动词
_TAG_PARTICLES = set("吗吧嘛")   # 「…,是吗/吧/嘛」是反问尾巴,不是否定后的肯定翻转

_KIND = "AI腔·对比句式"
_MSG = "高频 AI 对比句式;删掉否定铺垫,直接写后项,或改成动作/细节呈现。"
_MAX_HITS = 6  # 与 CRITIC_去AI味 的「最多 6 条」对齐,免得刷屏

_FENCE = re.compile(r"^(`{3,}|~{3,})")
_TRAIL = re.compile(r"[\s|）)】\]]+$")


# ── 文风指纹 anchor 例句:逐字签名句,命中要豁免 ──────────────────────────────

def load_anchors(root: Path | str) -> list[str]:
    """从 外置大脑/写作指纹.md 的「anchor 例句」段取作者逐字保留的原句(去掉 > 引用前缀)。"""
    p = Path(root) / REL_FINGERPRINT
    if not p.is_file():
        return []
    anchors: list[str] = []
    in_anchor = False
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#"):
            in_anchor = "anchor" in s.lower()
            continue
        if in_anchor and s.startswith(">"):
            a = s.lstrip(">").strip()
            if a:
                anchors.append(a)
    return anchors


# ── 对外:扫一段文本 → 硬伤清单 ──────────────────────────────────────────────

def detect(text: str, anchors: list[str] | None = None, *, cross_sentence: bool = False) -> list[Issue]:
    """扫文本里的 AI 对比句式,返回 gates.Issue 列表(去重、封顶 _MAX_HITS)。

    anchors 命中即豁免(作者签名句);cross_sentence=True 才报跨句号的「。是」翻转。
    """
    text = text or ""
    anchors = anchors or []
    issues: list[Issue] = []
    seen: set[str] = set()
    for block in _blocks(text):
        for _line, _col, raw in _scan_block(block, cross_sentence):
            # 豁免只认「检测句落在 anchor 里」(raw in a)一个方向:反向 a in raw 太宽,
            # 一条短 anchor 会放跑所有包含它的 AI 腔整句。
            if any(raw in a for a in anchors):
                continue  # 作者逐字签名句,豁免(像你≠AI腔)
            ev = _compact(raw)
            if ev in seen:
                continue
            seen.add(ev)
            issues.append(Issue(kind=_KIND, desc=_MSG, evidence=ev))
            if len(issues) >= _MAX_HITS:
                return issues
    return issues


# ── 内部:分块(跳 YAML frontmatter / 代码围栏)→ 逐块定位扫描 ─────────────────

def _blocks(text: str) -> list[list[tuple[str, int]]]:
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    out: list[list[tuple[str, int]]] = []
    block: list[tuple[str, int]] = []
    fence: tuple[str, int] | None = None
    in_fm = _has_frontmatter(lines)
    for i, line in enumerate(lines):
        t = line.strip()
        if in_fm:
            if i > 0 and t == "---":
                in_fm = False
            continue
        m = _FENCE.match(t)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
            continue
        if m:
            if block:
                out.append(block)
                block = []
            fence = (m.group(1)[0], len(m.group(1)))
            continue
        block.append((line, i + 1))
    if block:
        out.append(block)
    return out


def _has_frontmatter(lines: list[str]) -> bool:
    if not lines or lines[0].strip() != "---":
        return False
    saw = False
    for ln in lines[1:40]:
        t = ln.strip()
        if t == "---":
            return saw
        if re.match(r"^[A-Za-z0-9_-]+:\s*", t):
            saw = True
    return False


def _scan_block(block: list[tuple[str, int]], cross_sentence: bool) -> list[tuple[int, int, str]]:
    text = "\n".join(ln for ln, _ in block)
    starts: list[tuple[int, int]] = []
    cur = 0
    for ln, no in block:
        starts.append((cur, no))
        cur += len(ln) + 1
    return _find(text, starts, cross_sentence)


def _pos(starts: list[tuple[int, int]], offset: int) -> tuple[int, int]:
    lo, hi = 0, len(starts) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        off, no = starts[mid]
        nxt = starts[mid + 1] if mid + 1 < len(starts) else None
        if offset < off:
            hi = mid - 1
        elif nxt and offset >= nxt[0]:
            lo = mid + 1
        else:
            return no, offset - off + 1
    return starts[0][1], 1


def _find(text: str, starts: list[tuple[int, int]], cross_sentence: bool) -> list[tuple[int, int, str]]:
    findings: list[tuple[int, int, str]] = []
    offset = 0
    n = len(text)
    while offset < n:
        start = text.find("不是", offset)
        if start == -1:
            break
        if start > 0 and text[start - 1] == "是":  # 「是不是」问句片段,跳过
            offset = start + 2
            continue
        cand = text[start:]
        end = _flip_end(cand, cross_sentence)
        if end == -1:
            offset = start + 2
            continue
        raw = _TRAIL.sub("", _extract(cand, end))
        if len(raw) >= 4:
            line, col = _pos(starts, start)
            findings.append((line, col, raw))
        offset = start + max(len(raw), 2)
    return findings


def _flip_end(cand: str, cross_sentence: bool) -> int:
    """从「不是」往后找肯定翻转的结束位;找不到返回 -1。逐分支移植自 check-ai-patterns.js。"""
    i = 2  # 跳过「不是」
    scanned = 0
    crossed = False  # 已越过分隔符:其后紧贴的「是」可能是 只是/可是/于是 的词尾,不算翻转
    L = len(cand)
    while i < L and scanned <= _MAX_NEG_SPAN:
        ch = cand[i]
        if cand[i:i + 2] == "而是":
            return i + 2
        if ch in _SOFT_SEP:
            nxt = _skip_gap(cand, i + 1)
            if cand[nxt:nxt + 2] == "而是":
                return nxt + 2
            if nxt < L and cand[nxt] == "是" and not (nxt + 1 < L and cand[nxt + 1] in _TAG_PARTICLES):
                return nxt + 1
            crossed = True
        if ch in _HARD_SEP:
            nxt = _skip_gap(cand, i + 1)
            # 跨句号的「。是」翻转默认不报(那是作者的声音,逗号并排才是 AI 写法)
            if cross_sentence and nxt < L and cand[nxt] == "是" and not (nxt + 1 < L and cand[nxt + 1] in _TAG_PARTICLES):
                return nxt + 1
            if ch != ".":
                break
            crossed = True
        if ch in _STOP:
            break
        # 同句无分隔的紧凑式「不是A是B」(分隔符之前才认,之后的「是」多是连词词尾)
        if ch == "是" and cand[i - 1] not in _EITHER_OR_PREV and not crossed:
            return i + 1
        i += 1
        scanned += 1
    return -1


def _extract(cand: str, marker_end: int) -> str:
    e = marker_end
    limit = min(len(cand), marker_end + _MAX_POS_SPAN)
    while e < limit and cand[e] not in _STOP:
        e += 1
    return cand[:e]


def _skip_gap(text: str, i: int) -> int:
    """跳过行内空白;允许跨一个换行(再跳其后空白),让「,\\n而是」也能接上。"""
    L = len(text)
    while i < L and text[i] in " \t\r":
        i += 1
    if i < L and text[i] == "\n":
        i += 1
        while i < L and text[i] in " \t\r":
            i += 1
    return i


def _compact(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s[:77] + "..." if len(s) > 80 else s
