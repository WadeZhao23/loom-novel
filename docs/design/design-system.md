# Loom 设计系统（纸墨 · Zhǐ Mò Design System）

> 宣纸底 · 墨分五色 · 一枚印泥红 —— 一台为中文作者织字的织布机。
>
> 母题只有一个:**纸、墨、一根线**(线即叙事线)。两轴语义:**墨 = 交互与落定**(`--accent`),**朱 = 你的痕迹**(`--seal`:指纹/手改/学到的,印=作者落款)。红按**印章逻辑**用:一屏至多一处、小面积、绝不做主题色铺开。
>
> 本文是 Loom 桌面界面（`loom/webui/`）的**单一设计真相**。所有颜色、字号、间距、动效都以这里的 **Design Token** 为准；组件只引用语义 token，不写死值。改主题只换映射，不动组件。
>
> 数值已按 WCAG 2.1 AA 实测（见 §9 附录）。落地见 `loom/webui/style.css`。

---

## 0. 它是什么 / 不是什么

Loom 不是 SaaS 仪表盘，是一张**手稿纸**。它的不可替代性是「越写越像你」——这件事必须被**看见**，但绝不能喧宾夺主。视觉重心永远是中间那张白页，工具是配角。

参考坐标：长文写作工具的排版克制（iA Writer / Ulysses / Bear / Craft）+ 安静效率工具的精确与夜色（Linear / Things 3）。

---

## 1. 八条设计原则

1. **排版即界面。** 正文是主角，chrome 是配角。视觉重心永远是那张手稿白页。
2. **用色靠「省」而非「配」。** 墨（`--accent`＝动作/落定,亮色焦墨、暗色纸白反转）＋一枚只属于你的印（`--seal` 印泥朱＝写作指纹/手改痕迹）。其余全是墨分五色的中性阶（焦浓重淡清 → text/text-soft/text-mute/line-strong/line）。**彩色出现 = 有语义;红出现 = 你的痕迹。**
3. **专注是减法。** 把「现在这一句」之外的一切调暗。专注不是一个开关，是默认气质。
4. **留白即节奏。** 8px 网格 ＋ 慷慨行高/段距，让长时间阅读有呼吸。
5. **安静的高级感。** 不滥用渐变、不堆重投影、不纯黑纯白硬碰。暖近黑落在暖纸上——这就是「贵」的来源。
6. **暗色是墨池,不是深宣纸。** 夜间把图底反转:日=纸上写墨,夜=墨中显纸(偏青漆黑底＋暖白宣纸字,禁纯黑纯白)。抬升＝表面变亮,不是加更深阴影。
7. **动效服务于因果，不表演。** 只有状态转换才动；90–320ms；可被下一次输入打断；尊重 `prefers-reduced-motion`。
8. **品牌隐喻只在缝隙里出现。** 经/纬/线/纸/墨——用在分隔线、进度、指纹可视化等「结构件」上，不贴图。隐喻是骨，不是皮。正文区永远干净。

---

## 2. 颜色 Token（语义化 · 明暗双主题）

组件**只用语义层**。`[data-theme]` 切换：默认跟随系统 `prefers-color-scheme`，顶栏给手动覆盖并写入 `localStorage('loom_theme')`。配 `<meta name="color-scheme" content="light dark">` 让原生滚动条跟随。

### 2.1 LIGHT（默认 · 宣纸）

```css
:root, [data-theme="light"] {
  /* 背景层级(纸叠纸,不用刺眼纯白) */
  --bg:             #F5F1E8;   /* 宣纸,app 画布 */
  --bg-sunken:      #EDE8DB;   /* 凹槽:输入轨道、代码块底 */
  --surface:        #FBF8F1;   /* 面板/侧栏/卡片=手稿页 */
  --surface-raised: #FDFBF6;   /* 弹层/菜单(靠阴影抬升) */
  --overlay-scrim:  rgba(31,30,27,.38);

  /* 文字层级=墨分五色(焦浓重淡清) */
  --text:           #1F1E1B;   /* 焦墨 14.79:1 */
  --text-soft:      #6B6862;   /* 重墨 4.93:1 */
  --text-mute:      #9C978E;   /* 淡墨(仅占位/装饰,2.58:1) */
  --text-on-accent: #F7F3EA;   /* 墨上显纸 15.05:1 */

  /* 线=清墨 */
  --line:           #DFD9CC;
  --line-soft:      #EAE5D8;
  --line-strong:    #C9C2B2;

  /* 墨:交互与落定(主按钮=纸上落墨,完成=墨落定) */
  --accent:         #1F1E1B;
  --accent-hover:   #3E3C38;   /* 浓墨 */
  --accent-ink:     #1F1E1B;
  --accent-tint:    #EAE4D6;   /* 淡墨晕:选中行/工作流底 */
  --accent-tint-2:  #DFD8C7;

  /* 印泥朱:你的痕迹(指纹/手改/学到的)。印章逻辑,小面积 */
  --seal:           #A63A2B;   /* 5.71:1,可承载小字 */
  --seal-ink:       #8E2F22;   /* 7.22:1 */
  --seal-tint:      #F3E4DE;   /* 朱批底:选区/学习高亮 */
  --seal-line:      rgba(166,58,43,.5);

  /* 状态(语义色,小面积) */
  --success:        #376F55;  --success-tint: #E5EEE6;   /* 竹青 5.22:1 */
  --warning:        #A87718;  --warning-tint: #F5EDD8;
  --danger:         #B2432A;  --danger-tint:  #F6E8E2;   /* 赤 5.0:1,偏橙区别于印泥 */
  --info:           #46617A;  --info-tint:    #E7EDF2;   /* 黛蓝 */
}
```

### 2.2 DARK（墨池 · 夜=墨中显纸）

偏青漆黑(不是深宣纸——深棕夜纸发灰发脏)。文字用暖白宣纸色,禁纯白防眩。抬升靠表面变亮,不靠投影。

```css
[data-theme="dark"] {
  --bg:             #14161A;   /* 墨池 */
  --bg-sunken:      #101216;
  --surface:        #1B1E23;   /* text 13.07:1 */
  --surface-raised: #22262C;
  --overlay-scrim:  rgba(0,0,0,.6);

  --text:           #E8E3D9;   /* 暖白宣纸 14.16:1 */
  --text-soft:      #B3AEA3;   /* 7.56:1 */
  --text-mute:      #837F76;   /* 4.19:1(仅占位/说明) */
  --text-on-accent: #14161A;   /* 纸上显墨(反转) */

  --line:           #2E3138;
  --line-soft:      #24272D;
  --line-strong:    #41454E;

  /* 夜里墨纸反转:交互主色=纸色 */
  --accent:         #E8E3D9;
  --accent-hover:   #F5F1E8;
  --accent-ink:     #E8E3D9;
  --accent-tint:    #262A31;
  --accent-tint-2:  #2C3138;

  --seal:           #D2604F;   /* 朱提亮降饱和 4.77:1 */
  --seal-ink:       #DC7563;   /* 5.84:1 */
  --seal-tint:      #31211D;
  --seal-line:      rgba(210,96,79,.45);

  --success:        #7FAE93;  --success-tint: #1C2822;   /* 7.23:1 */
  --warning:        #D3A84C;  --warning-tint: #2C2515;
  --danger:         #E07A5F;  --danger-tint:  #3A201A;
  --info:           #8AA7C0;  --info-tint:    #1C242D;
}
```

> **印章红线:** `--seal` 是「你的痕迹」的专属色——指纹、手改、学到的、朱批。**一屏静息态至多一处朱**(通常是侧栏指纹卡),面积 <5%;绝不做按钮主色、绝不大面积铺底。主操作永远是墨(`--accent`)。danger 与 seal 同为暖红系,靠场景区分:danger 只出现在删除/错误,且永远带语义文案。

---

## 3. 字体排版

### 3.1 字体栈

```css
--font-ui:    -apple-system, BlinkMacSystemFont, "PingFang SC",
              "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
--font-brand: "LXGW WenKai Screen", "LXGW WenKai", "Kaiti SC", "STKaiti",
              "KaiTi", "楷体", "Songti SC", serif;      /* 品牌时刻:logo/弹窗标题/章题 */
--font-read:  "Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC",
              Georgia, "PingFang SC", "Microsoft YaHei", serif;  /* 手稿正文;Win 退黑体,绝不落 SimSun */
--font-mono:  "SF Mono", "JetBrains Mono", ui-monospace,
              "PingFang SC", monospace;                 /* 字数、diff、日志 */
```

**分野是 Loom 的文学气质核心:UI 用 sans,「作品文字」用 serif(宋),「品牌时刻」用楷。**
楷体三条纪律:只用于 ≥18px 的品牌时刻(logo/弹窗标题/章题/引语),**每屏至多一处**;只用 `font-weight: 400`(KaiTi 无粗体,伪粗发虚);功能文本(按钮/菜单/正文)永不用楷。发版前捆绑霞鹜文楷屏幕阅读版 GB2312 子集(约 1.7MB woff2,OFL;见打包任务),开发期靠系统 Kaiti SC / KaiTi 兜底。

### 3.2 模块化字号阶梯（base 16px，比例 ≈1.2）

| Token | px | line-height | weight | letter-spacing | 用途 |
|---|---|---|---|---|---|
| `--fs-display` | 26 | 1.25 | 400(楷) | 0 | Logo / 欢迎页大标题(--font-brand) |
| `--fs-h1` | 21 | 1.35 | 400(楷) | 0 | 弹层标题 / 章节名(--font-brand) |
| `--fs-h2` | 18 | 1.4 | 700 | -0.01em | 区块标题 |
| `--fs-body` | 14 | 1.6 | 400 | 0 | **UI 正文**（侧栏/表单/按钮） |
| `--fs-read` | **17** | **1.9** | 400 | 0 | **手稿正文（中文 serif）** |
| `--fs-sm` | 13 | 1.5 | 400 | 0 | 说明 / path / 状态栏 |
| `--fs-xs` | 12 | 1.4 | 600 | 0.02em | 侧栏分组标题 / badge / 字数 |
| `--fs-caption` | 11 | 1.3 | 600 | 0.04em | 角标 / 工序名 |

### 3.3 中文正文最佳实践（落到 `#editor`）

- **字号 17px**：屏幕阅读距离比纸远，中文笔画密，低于 16 易糊。
- **行高 1.9**：宋体笔画细、字面满，比黑体更吃行距；2.0 略散，1.9 更黏读。
- **每行 ≈34–38 个汉字**：CJK 的「黄金测量」。用 `max-width: 38em` 居中，**别满屏铺开**。
- **段距 `0.9em`** 优于段首缩进；要缩进则 `text-indent: 2em` 且去段距，二选一。
- **字间距 0**：CJK 自带字身框，加间距破坏节奏。
- 光标 `caret-color: var(--seal)`（落笔见朱）；选区 `::selection{background:var(--seal-tint)}`（选中即朱批，呼应「你的痕迹」）。

---

## 4. 间距 · 圆角（8px 网格）

```css
--space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
--space-5: 24px; --space-6: 32px; --space-7: 48px; --space-8: 64px;

--radius-xs: 6px;   /* badge / 小芯片 */
--radius-sm: 8px;   /* 按钮/输入/列表项/手稿页 */
--radius-md: 12px;  /* 卡片/内嵌块 */
--radius-lg: 16px;  /* 弹层/欢迎卡 */
--radius-xl: 20px;  /* 大对话框（少用） */
--radius-pill: 999px;
```

只用这 5 档圆角，删掉旧版散落的 9/10/18px。内圆角＝外圆角−padding（同心，避免嵌套尖角）。

---

## 5. 高度（Elevation）· 动效

```css
/* light：墨色真实投影（匹配纸感） */
[data-theme="light"] {
  --shadow-1: 0 1px 2px rgba(31,30,27,.05);    /* 列表项 hover、手稿页 */
  --shadow-2: 0 2px 8px rgba(31,30,27,.07);    /* 下拉/tooltip */
  --shadow-3: 0 8px 24px rgba(31,30,27,.10);   /* 弹层/卡片 */
  --shadow-4: 0 16px 48px rgba(31,30,27,.14);  /* 模态 */
  --shadow-focus: 0 0 0 3px rgba(31,30,27,.12);       /* 墨晕焦点环 */
}
/* dark：几乎不用投影，靠表面变亮 + 极淡纸色内描边定义边界 */
[data-theme="dark"] {
  --shadow-1: 0 0 0 1px rgba(232,227,217,.04);
  --shadow-2: 0 2px 8px rgba(0,0,0,.4),  inset 0 0 0 1px rgba(232,227,217,.05);
  --shadow-3: 0 8px 28px rgba(0,0,0,.5), inset 0 0 0 1px rgba(232,227,217,.06);
  --shadow-4: 0 18px 56px rgba(0,0,0,.6),inset 0 0 0 1px rgba(232,227,217,.07);
  --shadow-focus: 0 0 0 3px rgba(232,227,217,.16);
}

/* 动效 */
--dur-1: 90ms;   /* 即时反馈：按下、芯片高亮 */
--dur-2: 150ms;  /* 标准：hover、聚焦环、tooltip */
--dur-3: 220ms;  /* 面板：抽屉、淡出、pill 状态 */
--dur-4: 320ms;  /* 大转场：弹层进出、专注切换 */
--ease-out:   cubic-bezier(.22,1,.36,1);   /* 进入/展开，最常用 */
--ease-inout: cubic-bezier(.4,0,.2,1);
--ease-soft:  cubic-bezier(.4,0,.6,1);     /* 退出/淡出 */
```

高度语义：0 画布 / 1 静止卡·hover / 2 浮层 / 3 弹层 / 4 模态。同组件态变不跳级。

**该动 / 不该动**：hover 底色、聚焦环、pill 状态、弹层进出（`opacity`+`translateY(8px→0)`）该动；正文文字位移、切章整页 slide、打字特效、装饰性循环、转圈 loading（用「织进度」替代）不该动。所有动效**可被下一次输入打断**。`@media (prefers-reduced-motion: reduce)` 下全部降到 0.01ms。

---

## 6. Loom 专属视觉语言（朱＝印＝你的痕迹）

把品牌隐喻变成**功能可视化**，不是装饰。朱在全局唯一的主角位置就在这些「接缝」处，因此别处必须克制——形成「朱＝你的签名」的强语义锚（印=作者落款，写作指纹=你的签名）。

1. **朱印＝写作指纹。** 选区底色用 `--seal-tint`（朱批），写作指纹文件用朱色标识，光标是朱（落笔见朱）。未来当引擎能识别「这句像你」时，在该段左侧落一道极细朱竖线（`box-shadow: inset 3px 0 var(--seal-line)`）——置信度用透明度表达，不用红黄绿交通灯。
2. **流水线＝一根朱线串起五道工序。** 五道工序（设定师→大纲师→写手→编辑→润色师）是一排 pill，pill 间用细线相连；**完成的连线染成 `--seal`**——叙事线被一段段织过去。pending＝`--line` 空心；running＝`--accent` 描边＋极慢呼吸（1.6s，唯一允许的循环，reduced-motion 下静止）；done＝`--accent` 实心（墨落定）＋连线转朱。
3. **嗓音指纹卡。** 侧栏顶部一张卡，把抽象的「指纹」变成能被信任的对象：来源状态（中性默认/已学样本/继承）＋极淡朱纹签名底（`--seal-tint` 细竖纹）。
4. **diff 即「盖印/拆线」，不是「改错」。** learn 的 diff 不用刺眼红绿：**新学进的**用 `--seal-tint` 底（朱＝印上了你的痕迹）；**拆掉的**用 `--bg-sunken` 底＋删除线（墨涂掉，不用红——删除线本身已表意，红只留给真正的危险）。情绪从「被纠正」转为「被盖章认可」。
5. **空状态＝一台等着上线的织布机。** 欢迎卡/空章节用一张极简线描 SVG（经线垂落、一两根纬线半穿，全 `--line` 细线无填充）＋一句楷体文案。安静、有呼吸、只有 Loom 会这么做。

> 共同纪律：纹理/笔触只出现在**一次性品牌时刻**（启动页/空状态/章节完成），工作界面纹理 ≤3% 透明度;朱线/呼吸默认低饱和，可被 reduced-motion 关掉。隐喻出现在分隔、进度、指纹这些接缝处，**正文区永远干净**。新界面自检三问：配色是否 ≤3 色系？红是否只出现一次？是否有任何重复出现的国风装饰元素？

---

## 7. 组件规范（要点）

- **按钮**：`--radius-sm`，padding `9px 15px`。`primary`＝纸上落墨（亮色焦墨实心、暗色纸白实心）；默认＝`--surface`＋`--line`，hover 边框转 `--text-soft`；`ghost`＝透明，hover `--line-soft`；`danger`＝`--danger` 实心；`mini`＝`5px 11px`/`--fs-xs`。聚焦可见 `--shadow-focus`（墨晕）。
- **输入/选择**：`--surface` 底＋`--line`，focus 边框 `--accent`＋`--shadow-focus`。
- **侧栏列表项**：`--radius-sm`，hover `--line-soft`，active `--accent-tint`＋`--accent-ink`。行末 `badge`（`改过`/`已学`＝`--accent-tint`）。hover 时浮出行内动作（如 ⟳ 重写本章）。
- **写作指纹项**：`--seal-ink` 文字＋朱印标识，唯一带朱的列表项（印章逻辑的那「一处」）。
- **pill（工序）**：见 §6.2。
- **弹层**：`--surface-raised`＋`--shadow-4`＋`--radius-lg`；scrim `--overlay-scrim`；进出 `opacity`+`translateY` `--dur-4 --ease-out`。
- **toast**：底部居中，`--text` 底（dark 下 `--surface-raised`），`err` 用 `--danger`。
- **状态栏/字数**：editor 底部一行 `--font-mono --fs-sm`：`字数 1,284 · 目标 800 · 已达标 ✓`，配一条对照 `chapter_chars` 的细进度条。字数变化 90ms 微淡，不跳动。
- **命令面板（⌘K）/ 章内搜索（⌘F）**：浮层，键盘优先，Esc 关。

---

## 8. 编辑器与专注写作

- **测量与居中**：`#editor` `max-width:38em` 居中，两侧暖纸留白即天然 chrome；窗口越宽留白越多，文字宽度恒定。
- **专注模式（⌘.）**：隐藏侧栏＋顶栏，只剩居中手稿页，背景渐到纯 `--bg`，320ms ease-out。再按退出。
- **live 字数 / 目标进度**：见 §7 状态栏。Loom 唯一鼓励的「实时数字」。
- **自动保存**：可编辑文件 `input` 后 debounce 落盘（`PUT /api/file`），顶部脏点提示「未保存/已保存」。**修掉一个真实数据坑**：learn 前必须先 flush 落盘，否则 learn 读到未保存的旧正文。
- **未来（需把 `#editor` 升级到段落模型，单独排期，勿动现有 textarea 选区逻辑）**：打字机滚动（光标行恒定停视口 42–50% 偏上）、按段淡出非当前段（中文默认按「段」不按「句」，长句多按句会闪）。⚠️ 现版保留 `<textarea>`，因为局部重写依赖 `selectionStart/selectionEnd` 与 `value` 切片，改 `contenteditable` 会破坏它。

---

## 9. 无障碍 · 实现约定

- 对比度全部 ≥ AA（正文 4.5:1）；朱色文字一律走 `--seal`/`--seal-ink`（两者均过 AA）。实测见附录。
- 焦点可见：所有可交互元素 `:focus-visible` 有 `--shadow-focus`。
- `prefers-reduced-motion: reduce` → 动效降为 0.01ms。
- `prefers-color-scheme` 初始化主题；`<meta name="color-scheme">` 同步原生控件。
- **DOM 契约不可破**：`app.js` 以元素 `id` 与若干 class（`.pill .running .done`、`.list li.active`、`.fp`、`.badge.on`、`.chg.add/.rem`、`.hidden`）驱动逻辑。重设计**只换样式与新增节点，绝不重命名或删除既有 id / 既有 class 语义**。

### 附录：关键对比度实测（WCAG 2.1，AA=4.5:1）

| 组合 | 比值 | 判定 |
|---|---|---|
| Light text `#1F1E1B` / bg `#F5F1E8` | 14.79 | AAA |
| Light text-soft `#6B6862` / bg | 4.93 | AA |
| Light seal `#A63A2B` / bg | 5.71 | AA |
| Light seal-ink `#8E2F22` / seal-tint `#F3E4DE` | 6.58 | AA |
| Light 纸字 `#F7F3EA` / accent 焦墨按钮 | 15.05 | AAA |
| Light success `#376F55` / bg | 5.22 | AA |
| Light danger `#B2432A` / bg | 5.0 | AA |
| Dark text `#E8E3D9` / bg `#14161A` | 14.16 | AAA |
| Dark text `#E8E3D9` / surface `#1B1E23` | 13.07 | AAA |
| Dark text-soft `#B3AEA3` / surface | 7.56 | AAA |
| Dark seal `#D2604F` / bg | 4.77 | AA |
| Dark seal-ink `#DC7563` / bg | 5.84 | AA |
| Dark 墨字 `#14161A` / accent 纸白按钮 | 14.16 | AAA |
| Dark success `#7FAE93` / bg | 7.23 | AAA |

---

## 来源

- iA Writer — [Focus Mode](https://ia.net/writer/support/editor/focus-mode) · [Responsive Typography](https://ia.net/topics/responsive-typography-the-basics)
- Linear — [How we redesigned the Linear UI (II)](https://linear.app/now/how-we-redesigned-the-linear-ui)
- Cultured Code — [Things Big and Small](https://culturedcode.com/things/blog/2023/09/things-big-and-small/)
- [Dark Mode Design Systems (Muzli)](https://muz.li/blog/dark-mode-design-systems-a-complete-guide-to-patterns-tokens-and-hierarchy/)
- [中文 CSS 排版原則指南](https://simular.co/blog/post/2-中文-css-排版原則指南) · [W3C G18 对比度](https://www.w3.org/TR/WCAG20-TECHS/G18.html)
