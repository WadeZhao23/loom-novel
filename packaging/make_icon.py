#!/usr/bin/env python3
"""从「织」weave-mark 生成 Loom 应用图标(可复现)。纯 Pillow,无外部依赖。

跑:.venv/bin/python packaging/make_icon.py
产物:
  - packaging/loom.icns        给 loom.spec 的 BUNDLE icon=(打包 .app 的图标)
  - packaging/loom-1024.png    预览/留档(也可转 Windows .ico)
  - loom/webui/app-icon.png    随包数据,desktop.py 运行时设 dock 图标(dev 模式也能有图标)

设计:墨绿底(品牌主色)+ 暖金织标(指纹色),坐标取自 webui 的 weave-mark viewBox。
"""
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024
SS = 2                      # 超采样倍数(渲染 2x 再缩,抗锯齿)
R = SIZE * SS

# 品牌色(取自设计系统语义 token,见 docs/design/design-system.md)
GREEN_TOP = (28, 124, 86)   # #1C7C56 accent
GREEN_BOT = (15, 64, 41)    # 更深墨绿,竖向渐变收底
GOLD = (224, 180, 78)       # #E0B44E 暖金(指纹色)


def _vgradient(size, top, bot):
    col = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        col.putpixel((0, y), tuple(round(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    return col.resize((size, size))


def make_master():
    img = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    margin = round(96 * SS)            # macOS 图标四周留白
    inner = R - margin * 2
    radius = round(inner * 0.225)      # squircle 近似圆角

    grad = _vgradient(inner, GREEN_TOP, GREEN_BOT).convert("RGBA")
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner - 1, inner - 1], radius=radius, fill=255)
    img.paste(grad, (margin, margin), mask)

    # 织标:warp 4 竖 + weft 3 横,坐标取自 webui weave-mark 的 viewBox(0..38)
    draw = ImageDraw.Draw(img)
    s = 16.0 * SS                      # 缩放:38 单位 → 内容约 480px(@1x)
    cx, cy = 18, 19                    # 内容盒中心,映射到画布中心
    def P(vx, vy):
        return (round((vx - cx) * s + R / 2), round((vy - cy) * s + R / 2))
    warp_w = round(30 * SS)            # 竖线粗 ~30px@1024(加粗,dock 小尺寸也辨识得出)
    weft_w = round(40 * SS)            # 横线(weft)略粗,突出"织入"的横纱

    warp_xs = (7, 14, 21, 28)
    weft = {12: (3, 29), 20: (3, 23), 28: (3, 33)}

    def cap(px, py, w):                # 圆头(Pillow line 是平头,端点补圆点)
        draw.ellipse([px - w // 2, py - w // 2, px + w // 2, py + w // 2], fill=GOLD)

    for x in warp_xs:
        draw.line([P(x, 4), P(x, 34)], fill=GOLD, width=warp_w)
        cap(*P(x, 4), warp_w); cap(*P(x, 34), warp_w)
    for y, (x0, x1) in weft.items():
        draw.line([P(x0, y), P(x1, y)], fill=GOLD, width=weft_w)
        cap(*P(x0, y), weft_w); cap(*P(x1, y), weft_w)

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def build_icns(master):
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "loom.iconset"
        iconset.mkdir()
        for sz in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = sz * scale
                suffix = "@2x" if scale == 2 else ""
                master.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{sz}x{sz}{suffix}.png")
        out = ROOT / "packaging" / "loom.icns"
        subprocess.run(["iconutil", "-c", "icns", "-o", str(out), str(iconset)], check=True)
        return out


def main():
    master = make_master()
    master.save(ROOT / "packaging" / "loom-1024.png")
    (ROOT / "loom" / "webui").mkdir(parents=True, exist_ok=True)
    master.resize((512, 512), Image.LANCZOS).save(ROOT / "loom" / "webui" / "app-icon.png")
    icns = build_icns(master)
    print(f"✓ {icns.relative_to(ROOT)}")
    print(f"✓ packaging/loom-1024.png")
    print(f"✓ loom/webui/app-icon.png(运行时 dock 图标)")


if __name__ == "__main__":
    main()
