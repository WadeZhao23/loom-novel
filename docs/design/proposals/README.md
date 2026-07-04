# 图标水墨化提案(已采用 · 存档)

**已落地**:`packaging/make_icon.py` 现直接程序化渲染水墨图标——宣纸底 + 焦墨织标线描 + 右下一枚阴刻小朱印(印面白文刻「**曌**」,武曌自造字·日月当空),配色取自纸墨设计系统(`--bg` 宣纸 / `--text` 焦墨 / `--seal` 印泥朱)。跑一次即重生 `packaging/loom.icns`、`packaging/loom-1024.png`、`loom/webui/app-icon.png`,纯 Pillow、固定种子、可复现(印面字体走 macOS 系统重黑体,缺字自动降级,见 `SEAL_FONTS`)。

采用的是 `app-icon-ink-a.jpg` 的**理念**(宣纸 + 墨 + 右下小朱印,红只按印章逻辑小面积用),但**织标沿用 App 内同源的抽象经纬 weave-mark**(而非概念稿里的写实织机)——好处:与 webui 标识一致,且缩到 dock/Finder 16px 仍辨识得出(写实织机会糊)。

## 两版概念稿(ModelScope Qwen-Image 出的,仅留档)

- `app-icon-ink-a.jpg` — 宣纸底 + 墨色织机线描 + 右下一枚小朱印。**已按其理念落地**(见上)。
- `app-icon-ink-b.jpg` — 整枚朱砂印章,印面阴刻织机经纬。**未采用**:让朱红成为品牌主色,与「红绝不做主题色铺开」相悖。

## 想调整图标时

改 `packaging/make_icon.py`(色值、经纬坐标、朱印位置/大小都在里头),跑 `.venv/bin/python packaging/make_icon.py` 重新生成三件产物即可,无需外部图源。
