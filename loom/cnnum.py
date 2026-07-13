"""中文/阿拉伯章号 → int 排序键。只给导入正文按真实章序重排用;纯 stdlib、不 import 任何 loom 模块。"""

from __future__ import annotations

import re

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}
_CN_CHARS = set(_CN_DIGIT) | set(_CN_UNIT)
_NUM_IN_NAME = re.compile(r"第\s*([0-9]+|[零〇一二两三四五六七八九十百千]+)\s*章")
_SERIAL = re.compile(r"^0*([0-9]+)\b")


def cn_to_int(s: str) -> int | None:
    """中文数字串 → int(一/十一/二十/三十五/一百零一/两百/零);非中文数字返回 None。"""
    s = (s or "").strip()
    if not s or any(c not in _CN_CHARS for c in s):
        return None
    return _cn_parse(s)


def _cn_parse(s: str) -> int | None:
    """确定性:遇单位(十/百/千)把暂存数字乘单位入总;「十X」开头补 1。"""
    total, cur = 0, 0
    for i, c in enumerate(s):
        if c in _CN_DIGIT:
            cur = _CN_DIGIT[c]
        elif c in _CN_UNIT:
            unit = _CN_UNIT[c]
            total += (cur if cur else 1) * unit   # 「十一」的十=1*10;「二十」的十=2*10
            cur = 0
        else:
            return None
    return total + cur


def chapter_order_key(filename: str) -> tuple[int, str]:
    """从文件名抽章号作排序键;抽不到 → (10**9, filename) 排最后、按名稳定。"""
    stem = filename.rsplit(".", 1)[0]
    m = _NUM_IN_NAME.search(stem)
    if m:
        tok = m.group(1)
        n = int(tok) if tok.isdigit() else cn_to_int(tok)
        if n is not None:
            return (n, filename)
    ms = _SERIAL.match(stem)   # 纯序号文件名 01.txt / 2.txt
    if ms:
        return (int(ms.group(1)), filename)
    return (10 ** 9, filename)
