import numpy as np, imageio.v2 as imageio, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from functools import lru_cache

W, H = 1080, 1920
PAPER=(250,248,243); INK=(35,36,30); SOFT=(111,110,98); GREEN=(28,124,86)
LINE=(228,223,211); WHITE=(255,255,255)
FPS, D = 30, 8

def _load(paths, size):
    for p in paths:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except Exception: pass
    return ImageFont.load_default()
@lru_cache(maxsize=None)
def SANS(s):  return _load(["/System/Library/Fonts/Hiragino Sans GB.ttc","/System/Library/Fonts/STHeiti Medium.ttc"], s)
@lru_cache(maxsize=None)
def SERIF(s): return _load(["/System/Library/Fonts/Supplemental/Songti.ttc","/System/Library/Fonts/STHeiti Medium.ttc"], s)

stills = {k: Image.open(os.path.join(os.path.dirname(__file__),"frames",f"{k}.png")).convert("RGB") for k in ["s0","s2","s6","s8","s9","s11"]}

_md = ImageDraw.Draw(Image.new("RGB",(10,10)))
def tsize(txt, f): b=_md.textbbox((0,0),txt,font=f); return b[2]-b[0], b[3]-b[1]
def center(draw, txt, cy, f, fill):
    w,h = tsize(txt,f); draw.text(((W-w)//2, cy-h//2), txt, font=f, fill=fill); return h

def base_canvas():
    im=Image.new("RGB",(W,H),PAPER); d=ImageDraw.Draw(im)
    for x in range(0,W,30): d.line([(x,0),(x,H)], fill=(246,243,236), width=1)
    return im

CARD_X, CARD_Y, CARD_W, CARD_H = 24, 700, 1032, 596
def make_shadow():
    sh=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(sh)
    d.rounded_rectangle([CARD_X, CARD_Y+12, CARD_X+CARD_W, CARD_Y+CARD_H+12], radius=26, fill=(35,36,30,70))
    return sh.filter(ImageFilter.GaussianBlur(20))
SHADOW=make_shadow()

def brand(draw, cy):
    f=SANS(40); txt="Loom"; w,h=tsize(txt,f)
    sq=34; gap=14; x0=(W-(sq+gap+w))//2
    draw.rounded_rectangle([x0, cy-sq//2, x0+sq, cy+sq//2], radius=8, fill=GREEN)
    draw.text((x0+sq+gap, cy-h//2-2), txt, font=f, fill=INK)

def render_shot(sc):
    bg=base_canvas(); d=ImageDraw.Draw(bg)
    brand(d, 116)
    ty=300
    for ln in sc["title"].split("\n"):
        h=center(d, ln, ty, SANS(74), INK); ty += h+22
    d.rounded_rectangle([(W-96)//2, ty+4, (W+96)//2, ty+16], radius=6, fill=GREEN)
    bg=bg.convert("RGBA"); bg.alpha_composite(SHADOW); bg=bg.convert("RGB"); d=ImageDraw.Draw(bg)
    d.rounded_rectangle([CARD_X,CARD_Y,CARD_X+CARD_W,CARD_Y+CARD_H], radius=26, fill=WHITE, outline=LINE, width=2)
    center(d, sc["cap"], 1474, SANS(46), SOFT)
    center(d, "接 Claude Code 实跑 · 越写越像你", 1822, SANS(32), SOFT)
    pad=16; ix,iy=CARD_X+pad, CARD_Y+pad; iw,ih=CARD_W-2*pad, CARD_H-2*pad
    st=stills[sc["still"]]
    n=max(1,int(round(sc["dur"]*FPS))); out=[]
    for k in range(n):
        t=k/(n-1) if n>1 else 0
        z=1.0+0.05*t
        cw,ch=int(st.width/z), int(st.height/z)
        l=(st.width-cw)//2; tp=(st.height-ch)//2
        crop=st.crop((l,tp,l+cw,tp+ch)).resize((iw,ih), Image.LANCZOS)
        canv=bg.copy(); canv.paste(crop,(ix,iy)); out.append(np.asarray(canv))
    return out

def render_card(sc):
    bg=base_canvas(); d=ImageDraw.Draw(bg)
    brand(d, 372)
    bigf = SERIF(168) if sc.get("bigfont")=="serif" else SANS(150)
    center(d, sc["big"], 740, bigf, INK)
    d.rounded_rectangle([(W-110)//2, 884, (W+110)//2, 898], radius=7, fill=GREEN)
    center(d, sc["serif"], 1030, SERIF(50), SOFT)
    center(d, sc["small"], 1132, SANS(36), SOFT)
    return [np.asarray(bg)] * max(1,int(round(sc["dur"]*FPS)))

scenes=[
 {"type":"card","big":"Loom","serif":"一队 Agent,织成一条写小说的流水线","small":"接 Claude Code · 实跑一章","dur":2.2},
 {"type":"shot","still":"s0","title":"一条命令,起一本书","cap":"新建项目 · 后端接 Claude Code","dur":1.9},
 {"type":"shot","still":"s2","title":"先喂它一段你写的字","cap":"从你的样本提炼「写作指纹」","dur":2.1},
 {"type":"shot","still":"s6","title":"5 个 Agent 接力写一章","cap":"设定 → 大纲 → 写手 → 编辑 → 润色","dur":2.1},
 {"type":"shot","still":"s8","title":"一章落定","cap":"全程真 · Claude 生成","dur":1.5},
 {"type":"shot","still":"s9","title":"成稿带着你的嗓音","cap":"短句 · 单句成段 · 动作收尾","dur":2.6},
 {"type":"shot","still":"s11","title":"它真的在学你","cap":"你改一次,指纹更新一次","dur":2.4},
 {"type":"card","big":"越写越像你","bigfont":"serif","serif":"Loom · 写作指纹越跑越像你","small":"开源 · DeepSeek / Claude Code","dur":2.4},
]

def write(dst):
    w=imageio.get_writer(dst,fps=FPS,quality=9,macro_block_size=8,codec="libx264")
    tail=None
    for si,sc in enumerate(scenes):
        f = render_card(sc) if sc["type"]=="card" else render_shot(sc)
        if tail is not None:
            for k in range(D):
                a=(k+1)/(D+1); w.append_data((tail[k]*(1-a)+f[k]*a).astype("uint8"))
            f=f[D:]
        if si<len(scenes)-1:
            for x in f[:-D]: w.append_data(x)
            tail=f[-D:]
        else:
            for x in f: w.append_data(x)
    w.close()

for dst in ("/Users/chambers/Desktop/loom-claude-vertical.mp4","/Users/chambers/Downloads/loom-claude-vertical.mp4"):
    write(dst)
print("竖屏完成:", W,"x",H,"|", round(sum(s["dur"] for s in scenes),1),"s |",
      round(os.path.getsize("/Users/chambers/Desktop/loom-claude-vertical.mp4")/1024),"KB")
