"""伏笔悬空检测器:扫 卡章纲 里 recap 自动写的 [埋设]/[推进]/[回收] 伏笔行,
找出"埋了很久、卡章纲里却查不到任何后续推进/回收"的悬空伏笔。

只读 外置大脑/卡章纲.md(recap.py 已写进 [AI回顾] 子块的伏笔行,见 recap._format_block),
**纯字符串匹配**——不打分、不建实体库、不向量检索。只**回头诊断**("你第K章埋了X、一直没还"),
绝不替作者写前向规划/不替他兑现伏笔(向前规划永远归人,守 ADR-0007)。

命中是**纯提醒**:写第N章时(编辑棒后)算一遍,有悬空就追加进 .审稿留痕/、发提示——
**不进回炉**(它读的是卡章纲、质检回炉改的是正文,改了也清不掉,只会空转),也绝不阻断出稿。

借鉴 inkos 的"未回收伏笔按章距升级"思路(AGPL,**仅思想、未取其代码**),Python 清写;
只取这一内核,不引入它的 HookRecord 依赖图 / 半衰期 / promotion / Zod 那套重机械(违 Loom 极简)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .gates import Issue
from .paths import CARD_REL

_CH = re.compile(r"^- 第(\d+)章[:：]")              # 顶格章规划行(人手写)
_FORE = re.compile(r"\[(埋设|推进|回收)\]\s*(.+?)\s*$")  # recap 写的伏笔行(缩进)
_CJK = re.compile(r"[一-鿿]+")
_MAX_HITS = 6  # 与 CRITIC_质检 的「最多 5 条」同量级,免得刷屏


@dataclass
class Hook:
    chapter: int
    kind: str   # 埋设 / 推进 / 回收
    text: str


def parse_hooks(root: Path | str) -> list[Hook]:
    """从卡章纲取所有伏笔行(章号 + 类别 + 文本)。只认章行下【缩进】的 recap 子行,不碰人手写规划行。"""
    p = Path(root) / CARD_REL
    if not p.is_file():
        return []
    hooks: list[Hook] = []
    cur: int | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        m = _CH.match(line)
        if m:
            cur = int(m.group(1))
            continue
        if cur is None or line[:1] not in (" ", "\t"):
            continue  # 顶格行(章规划行/标题/引言)不取伏笔,只扫章行下缩进的 [AI回顾] 子块
        fm = _FORE.search(line)
        if fm:
            text = fm.group(2).strip()
            if text and text != "无":
                hooks.append(Hook(cur, fm.group(1), text))
    return hooks


def _noise_chars(planted: list[Hook]) -> set[str]:
    """主角名/常用字这类**出现在多数埋设里**的高频字 → 标为噪声,不作伏笔身份的匹配依据。

    用字符级文档频率(出现在几条埋设里),而非全文计数:主角名几乎条条都有 → 高 df;
    具体名物(青玉牌/地窖)只在一条 → 低 df。避免「沈砚的X」这类名字前缀二元组冒充区别词。
    """
    df: dict[str, int] = {}
    for h in planted:
        for ch in set("".join(_CJK.findall(h.text))):
            df[ch] = df.get(ch, 0) + 1
    cut = max(2, int(len(planted) * 0.5))
    return {c for c, d in df.items() if d >= cut}


def _distinctive(text: str, noise: set[str]) -> set[str]:
    """文本的区别性词集合:CJK 二元组里**两字都不是噪声字**的那些(单字 run 取非噪声单字)。"""
    out: set[str] = set()
    for run in _CJK.findall(text):
        if len(run) == 1:
            if run not in noise:
                out.add(run)
            continue
        for i in range(len(run) - 1):
            a, b = run[i], run[i + 1]
            if a not in noise and b not in noise:
                out.add(run[i:i + 2])
    return out


def stale(root: Path | str, current_chapter: int, threshold: int) -> list[Issue]:
    """返回悬空伏笔清单(gates.Issue)。threshold<=0 关闭。

    判据:某条 [埋设] 在第K章,到 current_chapter 已超过 threshold 章,且后文(章号>K)
    没有任何 [推进]/[回收] 与它**共享区别性词**(剔除主角名这类高频噪声字后仍相同的二元组)。
    判不准(该埋设无区别性词)就**不报**——宁可漏,不乱催(守"提示不阻断"的克制)。
    """
    if threshold <= 0:
        return []
    hooks = parse_hooks(root)
    planted = [h for h in hooks if h.kind == "埋设"]
    if not planted:
        return []
    later = [h for h in hooks if h.kind in ("推进", "回收")]
    noise = _noise_chars(planted)

    issues: list[Issue] = []
    for h in planted:
        dist = current_chapter - h.chapter
        if dist <= threshold:
            continue  # 还新,不催
        distinctive = _distinctive(h.text, noise)
        if not distinctive:
            continue  # 这条埋设没有区别性词 → 判不准,不猜不报
        if any(r.chapter > h.chapter and (distinctive & _distinctive(r.text, noise)) for r in later):
            continue  # 后文有推进/回收提到它 → 不算悬空
        issues.append(Issue(
            kind="伏笔悬空",
            desc=f"第{h.chapter}章埋的伏笔已 {dist} 章未见推进/回收(若本章正回收可忽略)",
            evidence=h.text[:60],
        ))
        if len(issues) >= _MAX_HITS:
            break
    return issues
