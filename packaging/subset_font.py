#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""品牌楷体子集化:霞鹜文楷屏幕阅读版 → Loom Kai(可复跑)。

为什么捆字体:`--font-brand` 首选 LXGW WenKai Screen,系统楷只是兜底——
Windows 的 KaiTi 无粗体、非中文系统甚至没有楷体,品牌时刻(logo/弹窗标题/章题)
会整个塌掉。捆一份 GB2312 子集(~2MB woff2)让三端长一个样。

为什么改内部名为 "Loom Kai":OFL 1.1 有保留字体名(RFN)惯例,子集属于修改版;
上游虽未声明 RFN,改名彻底绕开争议,也避免与用户本机装的全量文楷同名相互干扰
(生僻字正好按 `--font-brand` 栈回退到本机全量文楷/系统楷)。
授权原文见 loom/webui/fonts/OFL.txt(随包分发,勿删)。

子集范围(刻意克制):
- ASCII 可打印区(logo "Loom" 本身是拉丁字母)
- GB2312 一二级汉字全 6763 字(书名/章题的常用字池)
- 一小撮章题常见中文标点(《》「」·—…〇 等)——不拉 GB2312 符号区整区,
  那里面一半是假名/西里尔,品牌时刻用不上
- 超出子集的生僻字(如「彧」「嬛」)回退系统楷/宋,不崩排版

跑法(项目根,需 fonttools + brotli:pip install fonttools brotli):
    python3 packaging/subset_font.py
源字体自动下载到 packaging/.font-cache/(已 gitignore),sha256 校验后子集化,
产物写进 loom/webui/fonts/:loom-kai.woff2(运行时唯一引用)+ loom-kai.ttf(备份)。
"""

import hashlib
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

from fontTools.subset import Options, Subsetter, load_font, save_font

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).resolve().parent / ".font-cache"
OUT_DIR = PROJECT_ROOT / "loom" / "webui" / "fonts"

# 钉死版本:换版本要同时换 URL 和 sha256,保证可复现
SOURCE_URL = (
    "https://github.com/lxgw/LxgwWenKai-Screen/releases/download/"
    "v1.522/LXGWWenKaiScreen.ttf"
)
SOURCE_SHA256 = "cd1a6fa39c4ea42fd8f4e289945789b0e510cf7016435640f8893cdad9b220f3"
SOURCE_NOTE = "LXGW WenKai Screen v1.522"

FAMILY = "Loom Kai"
PS_NAME = "LoomKai-Regular"
WOFF2_BUDGET = 3 * 1024 * 1024  # 设计系统承诺:单文件 ≤3MB

# 章题/弹窗标题里会出现、又不在 GB2312 汉字区的标点(〇 是"第一〇三章"的〇)
PUNCT = "、。,;:?!·~—…‘’“”「」『』《》〈〉()【】〔〕々〇　"


def gb2312_hanzi() -> str:
    """GB2312 一二级汉字全集(区位 0xB0A1–0xF7FE,共 6763 字)。"""
    chars = []
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.append(bytes((hi, lo)).decode("gb2312"))
            except UnicodeDecodeError:
                pass  # 末区尾部的空位
    return "".join(chars)


def fetch_source() -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    cached = CACHE_DIR / SOURCE_URL.rsplit("/", 1)[-1]
    if not cached.exists():
        print(f"下载 {SOURCE_NOTE} → {cached}")
        urllib.request.urlretrieve(SOURCE_URL, cached)
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        sys.exit(f"源字体 sha256 不符(得到 {digest}),删除 {cached} 重跑")
    return cached


def rename_family(font) -> None:
    """name 表改姓:内部 family → Loom Kai,授权记录(0/13/14)原样保留。"""
    note = f"{PS_NAME}; GB2312 subset of {SOURCE_NOTE}"
    for rec in font["name"].names:
        if rec.nameID in (1, 16):
            rec.string = FAMILY
        elif rec.nameID in (2, 17):
            rec.string = "Regular"
        elif rec.nameID == 3:
            rec.string = note
        elif rec.nameID == 4:
            rec.string = FAMILY
        elif rec.nameID == 6:
            rec.string = PS_NAME
        elif rec.nameID == 5:
            rec.string = rec.toUnicode() + f"; GB2312 subset for Loom"


def main() -> None:
    hanzi = gb2312_hanzi()
    assert len(hanzi) == 6763, f"GB2312 汉字数不对:{len(hanzi)}"
    ascii_printable = "".join(chr(c) for c in range(0x20, 0x7F))
    text = ascii_printable + hanzi + PUNCT

    source = fetch_source()
    options = Options()
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17]
    font = load_font(str(source), options)

    subsetter = Subsetter(options)
    subsetter.populate(text=text)
    subsetter.subset(font)

    missing = [ch for ch in hanzi if ord(ch) not in font.getBestCmap()]
    if missing:
        sys.exit(f"源字体缺 GB2312 字 {len(missing)} 个:{''.join(missing[:20])}…")

    rename_family(font)
    OUT_DIR.mkdir(exist_ok=True)

    ttf_path = OUT_DIR / "loom-kai.ttf"
    save_font(font, str(ttf_path), options)

    options.flavor = "woff2"
    woff2_path = OUT_DIR / "loom-kai.woff2"
    save_font(font, str(woff2_path), options)

    w2 = woff2_path.stat().st_size
    print(f"字形数 {len(font.getGlyphOrder())};"
          f" woff2 {w2 / 1024 / 1024:.2f}MB, ttf {ttf_path.stat().st_size / 1024 / 1024:.2f}MB")
    if w2 > WOFF2_BUDGET:
        sys.exit(f"woff2 超预算 3MB({w2} 字节),检查子集范围")
    print(f"完成 → {OUT_DIR}")


if __name__ == "__main__":
    main()
