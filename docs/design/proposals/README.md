# 图标水墨化提案(未采用,仅供评审)

现行 `loom/webui/app-icon.png` 与 `packaging/loom-1024.png` 仍是纸墨设计系统之前的绿底金线织机,与宣纸/墨/朱印的体系不搭。两个重绘方向(ModelScope Qwen-Image 出的概念稿,采用前需矢量重绘):

- `app-icon-ink-a.jpg` — 宣纸底 + 墨色织机线描 + 右下一枚小朱印。贴合设计系统「红按印章逻辑、小面积」的用法,**推荐方向**。
- `app-icon-ink-b.jpg` — 整枚朱砂印章,印面阴刻织机经纬。更有辨识度但让朱红成为品牌主色,与「红绝不做主题色铺开」相悖。

采用任一方向时:先矢量化重绘 1024px 源图,替换 `packaging/loom-1024.png` 后跑 `packaging/make_icon.py` 重新生成 icns,同步替换 `loom/webui/app-icon.png`。
