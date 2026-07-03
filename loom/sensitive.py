"""违禁词 / 敏感内容粗筛:解析 外置大脑/违禁词.md 的「触发词」+ 内置基线,对文本做本地子串匹配。

只在本地跑、不发任何 LLM 请求、不消耗 token。命中**只提示、不阻断**——
平台审核偏严但不公开清单,终审仍靠人;这层只兜低级漏网。
"""
from __future__ import annotations

import re
from pathlib import Path

from .paths import BANNED_REL as REL
from .paths import PROJECT_CARD_REL as CARD_REL  # 立项卡的「平台:」行给基线定松紧(粗粒度二档,非逐平台白名单)
_SPLIT = re.compile(r"[、,，/\s]+")
_TRIGGER = re.compile(r"^\**\s*触发词\**\s*[:：]\s*(.+)$")
_HEAD = re.compile(r"^#+\s*(.+?)\s*$")
_PLATFORM = re.compile(r"^\s*平台\s*[:：]\s*(.+)$")

# 兜底基线(违禁词.md 缺失时用):只放安全的「话题/品牌/脏话」代表词,
# 政治与露骨词不在代码里硬编码,留给作者在 违禁词.md 自维护。
_BASELINE = {
    "暴力血腥 · 自残": ["自杀", "自残", "割腕", "上吊"],
    "违法犯罪教学": ["制毒", "配方", "炸药", "雷管"],
    "赌博 · 毒品": ["赌博", "吸毒", "贩毒", "摇头丸"],
    "真实指涉": ["微信", "淘宝", "抖音", "iPhone", "茅台"],
    "低俗脏话": ["他妈的", "卧槽"],
}

# 严格档【额外】叠加的几个代表词(仅当立项卡平台=起点/番茄时并进基线)。
# 粗粒度二档:严 / 默认,只多几条通用代表词——刻意【不】做逐平台白名单/映射树(ADR 0011:
# 会过时的逐平台清单不维护),终审仍靠人、依旧只提示不阻断(ADR 0006)。
_BASELINE_STRICT_EXTRA = {
    "低俗脏话": ["妈的", "傻逼", "狗日"],
    "暴力血腥 · 自残": ["跳楼", "服毒"],
}


def _platform_strict(root: Path | str) -> bool:
    """读立项卡「平台:」行,平台含 起点 / 番茄 → True(基线走严格档)。

    全程兜底:缺卡 / 空卡 / 没写平台 / 解析异常一律返回 False,绝不抛错(自检不能因缺卡崩)。
    """
    try:
        p = Path(root) / CARD_REL
        if not p.is_file():
            return False
        for line in p.read_text(encoding="utf-8").splitlines():
            m = _PLATFORM.match(line)
            if m:
                plat = m.group(1)
                return ("起点" in plat) or ("番茄" in plat)
        return False
    except Exception:
        return False


def load_words(root: Path | str) -> dict[str, str]:
    """{触发词: 分类}。优先读项目的 违禁词.md;读不到 / 没配触发词则用内置基线。

    用内置基线时,若立项卡平台=起点/番茄,再叠一小撮严格档代表词(粗粒度二档,非逐平台白名单)。
    """
    words: dict[str, str] = {}
    p = Path(root) / REL
    if p.is_file():
        cat = "未分类"
        for line in p.read_text(encoding="utf-8").splitlines():
            h = _HEAD.match(line)
            if h:
                cat = re.sub(r"^[\d.、\s]+", "", h.group(1)).strip() or cat
                continue
            m = _TRIGGER.match(line.strip())
            if not m:
                continue
            body = re.split(r"[((]", m.group(1))[0]  # 去掉「(请自行维护)」这类说明
            for w in _SPLIT.split(body):
                w = w.strip()
                if len(w) >= 2:
                    words[w] = cat
    if not words:
        baseline = {cat: list(ws) for cat, ws in _BASELINE.items()}
        if _platform_strict(root):  # 起点/番茄:严格档只【多加】几条通用代表词,不换成逐平台白名单
            for cat, extra in _BASELINE_STRICT_EXTRA.items():
                baseline.setdefault(cat, []).extend(extra)
        for cat, ws in baseline.items():
            for w in ws:
                words[w] = cat
    return words


def _contexts(text: str, w: str, limit: int = 3) -> list[str]:
    """命中词前后各截 ~10 字的上下文片段(最多 limit 条),给人眼快速判真伪。"""
    out: list[str] = []
    i = text.find(w)
    while i >= 0 and len(out) < limit:
        out.append(text[max(0, i - 10): i + len(w) + 10].replace("\n", " "))
        i = text.find(w, i + len(w))
    return out


def scan(text: str, root: Path | str) -> list[dict]:
    """返回命中列表:[{word, category, count, contexts}],按命中次数降序。

    纯子串匹配、只提示不阻断(不引入分词库):单字词一律不报——「颤抖」踩「抖」这类
    子串误伤太多,词长 ≥2 才算数(load_words 已滤,这里兜底);contexts 带前后文片段。"""
    text = text or ""
    hits = []
    for w, cat in load_words(root).items():
        if len(w) < 2:
            continue
        c = text.count(w)
        if c:
            hits.append({"word": w, "category": cat, "count": c, "contexts": _contexts(text, w)})
    hits.sort(key=lambda h: (-h["count"], h["category"], h["word"]))
    return hits
