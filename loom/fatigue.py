"""跨章重复/腔调疲劳检测器:看最近几章 + 本章草稿,挑「章首/章末与近章雷同」「整句跨章近重复」。

纯字符串数学(Dice 二元组相似度),不分词、不向量、不打分——命中出 gates.Issue(带原文证据),
喂进既有「去AI味」关卡当确定性地板,和 aitell(句内 AI 翻转句)一道跑、互补:aitell 抓**句内**,
本模块抓**跨章**。命中前比对写作指纹 anchor,作者签名句(含他有意复用的母题句)豁免。

借 inkos long-span-fatigue.ts 的思路(AGPL,**仅思想、未取其代码**),Python 清写;只取两项**高精度**
信号——Dice 章首/章末雷同 + 整句跨章近重复——不引入它的 n-gram 频次/章型单调/情绪流那套(降误报、守极简)。
"""
from __future__ import annotations

import re
from pathlib import Path

from .chaptertext import strip_title
from .gates import Issue

WINDOW = 5              # 只比最近 5 章(够抓套路,不拖)
_OPEN_CLOSE_FLOOR = 0.62  # 章首/章末雷同的 Dice 阈值(偏高,避免误伤正常的相似过渡)
_SENT_FLOOR = 0.72        # 整句跨章近重复的 Dice 阈值
_MIN_SENT = 8             # 太短的句子不比(口语短句天然重复,如「他没说话」)
_MAX_HITS = 5

_SENT_SPLIT = re.compile(r"[。!?！?…\n]+")
_CJK = re.compile(r"[一-鿿]")


def scan(project_root: Path | str, chapter_n: int, draft: str,
         anchors: list[str] | None = None, *, window: int = WINDOW) -> list[Issue]:
    """扫本章草稿对最近 window 章的跨章重复 → gates.Issue 列表。anchors 命中即豁免。"""
    anchors = anchors or []
    draft = strip_title(draft or "").strip()
    if not draft:
        return []
    priors = _prior_chapters(Path(project_root), chapter_n, window)
    if not priors:
        return []
    d_sents = _sentences(draft)
    if not d_sents:
        return []

    def _is_anchor(s: str) -> bool:
        return any(s in a or a in s for a in anchors)

    issues: list[Issue] = []

    # 1) 章首 / 章末与近章雷同(套路化开篇/收尾)
    d_first, d_last = d_sents[0], d_sents[-1]
    if not _is_anchor(d_first):
        k = _echo_chapter(_bigrams(d_first), [(k, _sentences(b)[0]) for k, b in priors if _sentences(b)])
        if k:
            issues.append(Issue("跨章·章首雷同", f"本章开头与第{k}章开头高度雷同(套路化开篇)", _ev(d_first)))
    if not _is_anchor(d_last):
        k = _echo_chapter(_bigrams(d_last), [(k, _sentences(b)[-1]) for k, b in priors if _sentences(b)])
        if k:
            issues.append(Issue("跨章·章末雷同", f"本章结尾与第{k}章结尾高度雷同(套路化收尾)", _ev(d_last)))

    # 2) 整句跨章近重复(成句复用,不是短语撞车)
    prior_sents = [(k, s, _bigrams(s)) for k, body in priors
                   for s in _sentences(body) if _cjk_len(s) >= _MIN_SENT]
    seen: set[str] = set()
    for ds in d_sents:
        if ds == d_first or ds == d_last:
            continue  # 首/末句已由上面章首/章末检查覆盖,不重复报
        if _cjk_len(ds) < _MIN_SENT or _is_anchor(ds):
            continue
        dbg = _bigrams(ds)
        hit = next((k for k, _s, pbg in prior_sents if _dice(dbg, pbg) >= _SENT_FLOOR), None)
        if hit is not None:
            ev = _ev(ds)
            if ev not in seen:
                seen.add(ev)
                issues.append(Issue("跨章·近重复句", f"与第{hit}章某句几乎雷同(整句复用)", ev))
        if len(issues) >= _MAX_HITS:
            break
    return issues[:_MAX_HITS]


# ── 内部 ──────────────────────────────────────────────────────────────────

def _prior_chapters(project_root: Path, chapter_n: int, window: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for k in range(max(1, chapter_n - window), chapter_n):
        p = project_root / "正文" / f"第{k}章.md"
        if p.exists():
            body = strip_title(p.read_text(encoding="utf-8")).strip()
            if body:
                out.append((k, body))
    return out


def _echo_chapter(target_bg: set[str], cands: list[tuple[int, str]]) -> int | None:
    """target 二元组与各章对应句比 Dice,超阈值返回那一章号(取最相似的那章)。"""
    best_k, best = None, _OPEN_CLOSE_FLOOR
    for k, s in cands:
        d = _dice(target_bg, _bigrams(s))
        if d >= best:
            best_k, best = k, d
    return best_k


def _sentences(body: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(body or "") if s.strip()]


def _cjk_len(s: str) -> int:
    return len(_CJK.findall(s))


def _bigrams(s: str) -> set[str]:
    cs = _CJK.findall(s)  # 只取 CJK 字,丢标点/拉丁,比的是内容字面
    if len(cs) < 2:
        return set(cs)
    return {cs[i] + cs[i + 1] for i in range(len(cs) - 1)}


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def _ev(s: str) -> str:
    s = s.strip()
    return s if len(s) <= 40 else s[:38] + "…"
