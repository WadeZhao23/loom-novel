"""违禁词 / 敏感内容粗筛:解析 外置大脑/违禁词.md 的「触发词」+ 内置基线,对文本做本地子串匹配。

只在本地跑、不发任何 LLM 请求、不消耗 token。命中**只提示、不阻断**——
平台审核偏严但不公开清单,终审仍靠人;这层只兜低级漏网。
"""
from __future__ import annotations

import re
from pathlib import Path

REL = "外置大脑/违禁词.md"
_SPLIT = re.compile(r"[、,，/\s]+")
_TRIGGER = re.compile(r"^\**\s*触发词\**\s*[:：]\s*(.+)$")
_HEAD = re.compile(r"^#+\s*(.+?)\s*$")

# 兜底基线(违禁词.md 缺失时用):只放安全的「话题/品牌/脏话」代表词,
# 政治与露骨词不在代码里硬编码,留给作者在 违禁词.md 自维护。
_BASELINE = {
    "暴力血腥 · 自残": ["自杀", "自残", "割腕", "上吊"],
    "违法犯罪教学": ["制毒", "配方", "炸药", "雷管"],
    "赌博 · 毒品": ["赌博", "吸毒", "贩毒", "摇头丸"],
    "真实指涉": ["微信", "淘宝", "抖音", "iPhone", "茅台"],
    "低俗脏话": ["他妈的", "卧槽"],
}


def load_words(root: Path | str) -> dict[str, str]:
    """{触发词: 分类}。优先读项目的 违禁词.md;读不到 / 没配触发词则用内置基线。"""
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
        for cat, ws in _BASELINE.items():
            for w in ws:
                words[w] = cat
    return words


def scan(text: str, root: Path | str) -> list[dict]:
    """返回命中列表:[{word, category, count}],按命中次数降序。"""
    text = text or ""
    hits = []
    for w, cat in load_words(root).items():
        c = text.count(w)
        if c:
            hits.append({"word": w, "category": cat, "count": c})
    hits.sort(key=lambda h: (-h["count"], h["category"], h["word"]))
    return hits
