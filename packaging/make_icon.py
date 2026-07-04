#!/usr/bin/env python3
"""从「织」weave-mark 生成 Loom 应用图标(水墨 · 可复现)。纯 Pillow,无外部依赖。

跑:.venv/bin/python packaging/make_icon.py
产物:
  - packaging/loom.icns        给 loom.spec 的 BUNDLE icon=(打包 .app 的图标)
  - packaging/loom-1024.png    预览/留档(也可转 Windows .ico)
  - loom/webui/app-icon.png    随包数据,desktop.py 运行时设 dock 图标(dev 模式也能有图标)

设计(纸墨设计系统 · docs/design/design-system.md):宣纸底 + 焦墨织标线描 + 右下一枚小朱印。
  织标经纬坐标取自 webui 的 weave-mark(index.html 的 viewBox 0..38),与 App 内标识同源。
  「红按印章逻辑、小面积」——朱只作右下角一枚阴刻小印(<5% 面积),绝不铺底。
所有随机(纸纹/飞白/印泥斑驳)用固定种子,输出可复现。
"""
from pathlib import Path
import random
import subprocess
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024
SS = 3                      # 超采样倍数(渲染 3x 再缩,笔触/圆头抗锯齿)
R = SIZE * SS
SEED = 20260704            # 固定种子 → 纸纹/斑驳可复现

SEAL_CHAR = "曌"          # 印面阴刻:武曌自造字(日月当空)
# 印面字体候选:重黑体优先(入印饱满、缩小仍可辨),退化到可用的中文粗体。
# 均为 macOS 系统字体(打包本就 macOS-only),缺字自动跳到下一候选。
SEAL_FONTS = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),      # W6(最重)
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),         # Heiti SC Medium
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),      # W3
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 1),   # Songti SC Bold
]


def resolve_seal_font():
    """挑第一个真正含「曌」字形的候选(拿一个大概率缺失的字比对,排除 tofu)。"""
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    for path, idx in SEAL_FONTS:
        try:
            f = ImageFont.truetype(path, 64, index=idx)
        except Exception:
            continue
        try:
            box_char = probe.textbbox((0, 0), SEAL_CHAR, font=f)
            box_miss = probe.textbbox((0, 0), "\U0002A6B2", font=f)
        except Exception:
            continue
        if box_char[2] > box_char[0] and box_char != box_miss:   # 有字形且不等于缺失字
            return path, idx
    raise RuntimeError("系统里找不到含「曌」的中文字体,请补一个候选到 SEAL_FONTS")

# 纸墨语义色(取自 docs/design/design-system.md 的 LIGHT token)
PAPER = (245, 241, 232)     # #F5F1E8 宣纸(app 画布)
PAPER_HI = (251, 248, 241)  # #FBF8F1 纸叠纸,中心略提亮
PAPER_LO = (226, 219, 204)  # 边缘压暗一档,给纸以厚度
INK = (31, 30, 27)          # #1F1E1B 焦墨(织标)
SEAL = (166, 58, 43)        # #A63A2B 印泥朱(你的痕迹,只作小印)
SEAL_DK = (142, 47, 34)     # #8E2F22 印泥深


def value_noise(size, cells, seed):
    """低频值噪声:cells×cells 随机点双三次放大成柔和纹理(替代 numpy)。"""
    rnd = random.Random(seed)
    small = Image.new("L", (cells, cells))
    small.putdata([rnd.randrange(256) for _ in range(cells * cells)])
    return small.resize((size, size), Image.BICUBIC)


def make_paper(inner, radius):
    """宣纸底:中心暖白微提亮 + 四缘压暗给厚度 + 极淡纸纹。"""
    base = Image.new("RGB", (inner, inner), PAPER)

    # 中心柔光(纸被灯照的微提亮)
    hi = Image.new("L", (inner, inner), 0)
    pad = inner * 0.10
    ImageDraw.Draw(hi).ellipse([pad, pad, inner - pad, inner - pad], fill=255)
    hi = hi.filter(ImageFilter.GaussianBlur(inner * 0.20))
    base = Image.composite(Image.new("RGB", (inner, inner), PAPER_HI), base, hi)

    # 四缘压暗(沿方角内一圈,柔化 → 纸的厚度感)
    vig = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(vig).rounded_rectangle(
        [0, 0, inner - 1, inner - 1], radius=radius, outline=255, width=int(inner * 0.09)
    )
    vig = vig.filter(ImageFilter.GaussianBlur(inner * 0.045))
    base = Image.composite(Image.new("RGB", (inner, inner), PAPER_LO), base, vig)

    # 极淡纸纹(overlay 混合,~5% 幅度,mid-gray 噪声几乎不偏色)
    grain = value_noise(inner, max(10, inner // 20), SEED + 1)
    noise_rgb = Image.merge("RGB", (grain, grain, grain))
    base = Image.blend(base, ImageChops.overlay(base, noise_rgb), 0.05)
    return base


def make_weave_mask():
    """焦墨织标的 alpha 遮罩(R 尺度):warp 4 竖 + weft 3 横,圆头,带轻微飞白。

    坐标同 webui weave-mark(index.html viewBox 0..38)——App 内外同一枚织标。
    """
    m = Image.new("L", (R, R), 0)
    draw = ImageDraw.Draw(m)

    s = 15.0 * SS                       # 38 单位 → 内容约 450px@1x(留出右下角给朱印)
    cx, cy = 17.5, 17.5                 # 织标中心略偏左上,让开右下角
    def P(vx, vy):
        return (round((vx - cx) * s + R / 2), round((vy - cy) * s + R / 2))

    warp_w = round(26 * SS)             # 竖纱(经)
    weft_w = round(34 * SS)             # 横纱(纬)略粗,突出「织入」

    warp_xs = (7, 14, 21, 28)
    weft = {12: (3, 29), 20: (3, 23), 28: (3, 33)}

    def cap(px, py, w):                 # 圆头(补圆点,笔尖收锋)
        draw.ellipse([px - w // 2, py - w // 2, px + w // 2, py + w // 2], fill=255)

    for x in warp_xs:
        a, b = P(x, 4), P(x, 34)
        draw.line([a, b], fill=255, width=warp_w)
        cap(*a, warp_w); cap(*b, warp_w)
    for y, (x0, x1) in weft.items():
        a, b = P(x0, y), P(x1, y)
        draw.line([a, b], fill=255, width=weft_w)
        cap(*a, weft_w); cap(*b, weft_w)

    # 飞白:低频亮噪声轻微削薄墨色(浓淡见笔,只减不加),粗颗粒 → 像墨的干湿而非像素噪点
    fly = value_noise(R, 34, SEED + 2).point(lambda v: 230 + v * 25 // 255)
    m = ImageChops.multiply(m, fly)
    # 边缘轻羽化:墨渗进纸,笔锋不再是硬边(核心仍实,小尺寸也清晰)
    m = m.filter(ImageFilter.GaussianBlur(R * 0.0009))
    return m


def make_seal(sw):
    """右下一枚阴刻小朱印(RGBA):朱砂方章,经纬阴刻见纸,边缘斑驳如钤印。"""
    seal = Image.new("RGBA", (sw, sw), (0, 0, 0, 0))
    rr = sw * 0.16
    ImageDraw.Draw(seal).rounded_rectangle([0, 0, sw - 1, sw - 1], radius=rr, fill=SEAL + (255,))

    # 印泥不匀:粗颗粒亮噪声轻微 multiply 到朱色上(浓淡斑驳,不像砂纸)
    mott = value_noise(sw, max(6, sw // 9), SEED + 3).point(lambda v: 214 + v * 41 // 255)
    rgb = ImageChops.multiply(seal.convert("RGB"), Image.merge("RGB", (mott, mott, mott)))

    # 钤印缺墨:极稀疏小斑点从 alpha 里抠掉(阈值很高 → 只咬掉零星几处,似钤压不实)
    alpha = seal.split()[3]
    bite = value_noise(sw, max(8, sw // 5), SEED + 4).point(lambda v: 0 if v > 224 else 255)
    alpha = ImageChops.multiply(alpha, bite)

    # 阴刻「曌」:字形从 alpha 减掉 → 露出底下宣纸(白文/阴文印),按墨迹外框精确居中
    carve = Image.new("L", (sw, sw), 0)
    cd = ImageDraw.Draw(carve)
    path, idx = resolve_seal_font()
    ref = ImageFont.truetype(path, sw, index=idx)               # 参考号:量字形外框
    rb = cd.textbbox((0, 0), SEAL_CHAR, font=ref)
    target = sw * 0.74                                          # 字占印面约 74%,留印边
    px = max(8, int(sw * target / max(rb[2] - rb[0], rb[3] - rb[1])))
    font = ImageFont.truetype(path, px, index=idx)
    b = cd.textbbox((0, 0), SEAL_CHAR, font=font)
    ox = (sw - (b[2] - b[0])) / 2 - b[0]
    oy = (sw - (b[3] - b[1])) / 2 - b[1]
    cd.text((ox, oy), SEAL_CHAR, font=font, fill=255)
    alpha = ImageChops.subtract(alpha, carve)

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def make_master():
    margin = round(96 * SS)             # macOS 图标四周留白(与旧版一致)
    inner = R - margin * 2
    radius = round(inner * 0.225)       # squircle 近似圆角

    scene = Image.new("RGB", (R, R), PAPER)
    scene.paste(make_paper(inner, radius), (margin, margin))

    # 焦墨织标:先落一层极淡墨晕(渗纸),再压清晰墨线
    mask = make_weave_mask()
    ink = Image.new("RGB", (R, R), INK)
    bleed = mask.filter(ImageFilter.GaussianBlur(R * 0.0035)).point(lambda v: v * 18 // 100)
    scene = Image.composite(ink, scene, bleed)
    scene = Image.composite(ink, scene, mask)

    # 右下角阴刻小朱印(钤在留白里,须整枚落在方角内、避开圆角)
    sw = round(inner * 0.20)
    inset = round(inner * 0.085)        # ≥ 圆角(0.225r)的 0.293 倍,保证印角不被裁
    sx = margin + inner - sw - inset
    sy = margin + inner - sw - inset
    seal = make_seal(sw)
    scene.paste(seal, (sx, sy), seal)

    # 方角圆矩形裁出图标外形(squircle alpha)
    out = scene.convert("RGBA")
    shape = Image.new("L", (R, R), 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        [margin, margin, R - margin - 1, R - margin - 1], radius=radius, fill=255
    )
    out.putalpha(shape)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


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
