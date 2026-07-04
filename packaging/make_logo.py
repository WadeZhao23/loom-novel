#!/usr/bin/env python3
"""从水墨织标生成 Loom 品牌标志(logo,透明底,亮/暗两版)。纯 Pillow,可复现。

跑:.venv/bin/python packaging/make_logo.py
产物:
  - docs/design/loom-logo.png        亮版(焦墨织标 + 朱印),浅底 / README 亮色用
  - docs/design/loom-logo-dark.png   暗版(纸白织标 + 提亮朱),深底 / README 暗色用

与 App 图标同源(同一枚经纬 weave-mark + 曌 阴刻印),但去掉宣纸方块、透明底 →
纯标志(logomark)。印面「曌」走白文镂空:字取页面底色,亮/暗页面都读得出。
配色取自纸墨设计系统(docs/design/design-system.md);随机用固定种子,可复现。
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# 复用图标的共享件(颜色/噪声/字体解析/印面字),不改动 make_icon 的产物
from make_icon import (
    INK, SEAL, SEAL_CHAR, resolve_seal_font, value_noise,
)

ROOT = Path(__file__).resolve().parent.parent
M = 1024                    # 织标渲染基准边(内容裁切前),足够清晰再缩
SS = 3
R = M * SS
SEED = 20260704

# 纸墨设计系统 token
INK_LIGHT = INK             # #1F1E1B 焦墨(亮版织标)
SEAL_LIGHT = SEAL          # #A63A2B 印泥朱(亮版印面)
INK_DARK = (232, 227, 217)  # #E8E3D9 暖白宣纸(暗版织标,夜=墨中显纸)
SEAL_DARK = (210, 96, 79)   # #D2604F 提亮降饱和朱(暗版印面)


def weave_alpha():
    """经纬织标的 alpha 遮罩(R 尺度,透明底):坐标同 webui weave-mark(viewBox 0..38)。"""
    m = Image.new("L", (R, R), 0)
    draw = ImageDraw.Draw(m)

    vb0, vb1 = 1.5, 36.5                # 含圆头留白的内容框
    span = vb1 - vb0
    pad = R * 0.11
    scale = (R - 2 * pad) / span
    def P(vx, vy):
        return (pad + (vx - vb0) * scale, pad + (vy - vb0) * scale)

    warp_w = round(scale * 1.72)        # 竖纱(经),同图标比例
    weft_w = round(scale * 2.25)        # 横纱(纬)略粗

    warp_xs = (7, 14, 21, 28)
    weft = {12: (3, 29), 20: (3, 23), 28: (3, 33)}

    def cap(px, py, w):                 # 圆头收锋
        draw.ellipse([px - w // 2, py - w // 2, px + w // 2, py + w // 2], fill=255)

    for x in warp_xs:
        a, b = P(x, 4), P(x, 34)
        draw.line([a, b], fill=255, width=warp_w)
        cap(*a, warp_w); cap(*b, warp_w)
    for y, (x0, x1) in weft.items():
        a, b = P(x0, y), P(x1, y)
        draw.line([a, b], fill=255, width=weft_w)
        cap(*a, weft_w); cap(*b, weft_w)

    fly = value_noise(R, 34, SEED + 2).point(lambda v: 232 + v * 23 // 255)   # 飞白
    m = ImageChops.multiply(m, fly)
    m = m.filter(ImageFilter.GaussianBlur(R * 0.0009))                        # 渗纸羽化
    return m


def make_seal(sw, field):
    """阴刻小朱印(RGBA):朱砂方章 + 白文镂空「曌」,边缘斑驳。field=印面朱色。"""
    seal = Image.new("RGBA", (sw, sw), (0, 0, 0, 0))
    ImageDraw.Draw(seal).rounded_rectangle([0, 0, sw - 1, sw - 1], radius=sw * 0.16,
                                           fill=field + (255,))

    mott = value_noise(sw, max(6, sw // 9), SEED + 3).point(lambda v: 214 + v * 41 // 255)
    rgb = ImageChops.multiply(seal.convert("RGB"), Image.merge("RGB", (mott, mott, mott)))

    alpha = seal.split()[3]
    bite = value_noise(sw, max(8, sw // 5), SEED + 4).point(lambda v: 0 if v > 224 else 255)
    alpha = ImageChops.multiply(alpha, bite)

    # 白文镂空「曌」:字形从 alpha 减掉 → 透出页面底色,按墨迹外框精确居中
    carve = Image.new("L", (sw, sw), 0)
    cd = ImageDraw.Draw(carve)
    path, idx = resolve_seal_font()
    rb = cd.textbbox((0, 0), SEAL_CHAR, font=ImageFont.truetype(path, sw, index=idx))
    target = sw * 0.74
    px = max(8, int(sw * target / max(rb[2] - rb[0], rb[3] - rb[1])))
    font = ImageFont.truetype(path, px, index=idx)
    b = cd.textbbox((0, 0), SEAL_CHAR, font=font)
    cd.text(((sw - (b[2] - b[0])) / 2 - b[0], (sw - (b[3] - b[1])) / 2 - b[1]),
            SEAL_CHAR, font=font, fill=255)
    alpha = ImageChops.subtract(alpha, carve)

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def make_logo(ink, seal_field):
    """在透明底上合成:焦墨织标 + 右下阴刻小朱印,裁到内容外框、留匀边。"""
    canvas = Image.new("RGBA", (R, R), (0, 0, 0, 0))

    mask = weave_alpha()
    ink_layer = Image.new("RGBA", (R, R), ink + (255,))
    canvas = Image.composite(ink_layer, canvas, mask)

    sw = round(R * 0.265)               # 印相对织标略小,钤在右下角、只压住网格一角
    seal = make_seal(sw, seal_field)
    sx = round(R * 0.66)
    sy = round(R * 0.685)
    canvas.alpha_composite(seal, (sx, sy))

    bbox = canvas.getbbox()            # 裁到实际墨迹
    canvas = canvas.crop(bbox)
    pad = round(max(canvas.size) * 0.06)
    padded = Image.new("RGBA", (canvas.width + 2 * pad, canvas.height + 2 * pad), (0, 0, 0, 0))
    padded.alpha_composite(canvas, (pad, pad))
    side = max(padded.size)            # 正方画布,居中(便于任意场景摆放)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(padded, ((side - padded.width) // 2, (side - padded.height) // 2))
    return square.resize((M, M), Image.LANCZOS)


def main():
    outdir = ROOT / "docs" / "design"
    outdir.mkdir(parents=True, exist_ok=True)
    make_logo(INK_LIGHT, SEAL_LIGHT).save(outdir / "loom-logo.png")
    make_logo(INK_DARK, SEAL_DARK).save(outdir / "loom-logo-dark.png")
    print("✓ docs/design/loom-logo.png(亮版)")
    print("✓ docs/design/loom-logo-dark.png(暗版)")


if __name__ == "__main__":
    main()
