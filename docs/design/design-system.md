# Loom 设计系统（织 · Zhī Design System）

> 暖纸底 · 墨绿主色 · 暖金指纹 —— 一台为中文作者织字的织布机。
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
2. **用色靠「省」而非「配」。** 一个主色（墨绿＝动作/选中）＋一个只属于你的强调色（暖金＝写作指纹）。其余全是纸、墨、线的中性灰。**彩色出现 = 有语义。**
3. **专注是减法。** 把「现在这一句」之外的一切调暗。专注不是一个开关，是默认气质。
4. **留白即节奏。** 8px 网格 ＋ 慷慨行高/段距，让长时间阅读有呼吸。
5. **安静的高级感。** 不滥用渐变、不堆重投影、不纯黑纯白硬碰。暖近黑落在暖纸上——这就是「贵」的来源。
6. **暗色靠「亮面」而非「投影」。** dark 模式抬升＝表面变亮（往墨绿微着色），不是加更深阴影。
7. **动效服务于因果，不表演。** 只有状态转换才动；90–320ms；可被下一次输入打断；尊重 `prefers-reduced-motion`。
8. **品牌隐喻只在缝隙里出现。** 经/纬/线/纸/墨——用在分隔线、进度、指纹可视化等「结构件」上，不贴图。隐喻是骨，不是皮。正文区永远干净。

---

## 2. 颜色 Token（语义化 · 明暗双主题）

组件**只用语义层**。`[data-theme]` 切换：默认跟随系统 `prefers-color-scheme`，顶栏给手动覆盖并写入 `localStorage('loom_theme')`。配 `<meta name="color-scheme" content="light dark">` 让原生滚动条跟随。

### 2.1 LIGHT（默认 · 暖纸）

```css
:root, [data-theme="light"] {
  /* 背景层级（越抬升越白） */
  --bg:             #FAF8F3;   /* 暖纸底，app 画布 */
  --bg-sunken:      #F3F0E8;   /* 凹槽：输入轨道、代码块底 */
  --surface:        #FFFFFF;   /* 面板/侧栏/卡片＝手稿白页 */
  --surface-raised: #FFFFFF;   /* 弹层/菜单（靠阴影抬升） */
  --overlay-scrim:  rgba(35,36,30,.34);

  /* 文字层级 */
  --text:           #23241E;   /* 主文字 暖近黑   14.74:1 */
  --text-soft:      #66655A;   /* 二级/说明       5.54:1 */
  --text-mute:      #91907F;   /* 占位/装饰（仅大字/图标，3.04:1） */
  --text-on-accent: #FFFFFF;   /* 墨绿按钮上的字  5.16:1 */

  /* 线 */
  --line:           #E6E1D5;   /* 标准边框 */
  --line-soft:      #F1EDE3;   /* hover 底、极淡分隔 */
  --line-strong:    #D7D1C2;   /* 聚焦/选中边框 */

  /* 主色：墨绿（动作/选中/链接） */
  --accent:         #1C7C56;   /* 4.87:1 on paper */
  --accent-hover:   #155F41;
  --accent-ink:     #155F41;   /* 浅底上的绿字   6.69:1 on tint */
  --accent-tint:    #E9F2EC;   /* 选中行/成功底 */
  --accent-tint-2:  #D7EAE0;   /* 选中行 hover */

  /* 强调色：暖金＝写作指纹（只做线/芯片/填充，不当小字） */
  --gold:           #C0901E;   /* 指纹线、进度、描边、芯片底 */
  --gold-ink:       #8C6A12;   /* 需要金色文字时用它 4.73:1 */
  --gold-tint:      #F6EFDC;   /* 「这句像你」高亮底 */
  --gold-line:      rgba(192,144,30,.55);

  /* 状态 */
  --success:        #1C7C56;  --success-tint: #E9F2EC;
  --warning:        #B0791A;  --warning-tint: #F7EED9;
  --danger:         #BB4A30;  --danger-tint:  #F6E9E3;   /* 4.78:1 */
  --info:           #2C6E8C;  --info-tint:    #E6EFF3;
}
```

### 2.2 DARK（夜 · 暖墨黑）

暖中性黑（带一丝绿/黄，不发蓝）。抬升靠表面变亮，不靠投影。

```css
[data-theme="dark"] {
  --bg:             #16170F;
  --bg-sunken:      #101109;
  --surface:        #1E1F16;   /* text 13.32:1 */
  --surface-raised: #26271C;   /* text 12.1:1 */
  --overlay-scrim:  rgba(0,0,0,.55);

  --text:           #E9E6DC;   /* 暖白非纯白，防眩 14.45:1 */
  --text-soft:      #B0AE9F;   /* 8.08:1 */
  --text-mute:      #8E8D7E;   /* on surface 4.96:1 */
  --text-on-accent: #0E1009;   /* 亮绿按钮上用深字 */

  --line:           #33352A;
  --line-soft:      #26271C;
  --line-strong:    #45473A;

  --accent:         #4FB98E;   /* on surface 6.86:1 */
  --accent-hover:   #63C99E;
  --accent-ink:     #5FC596;
  --accent-tint:    #1A3328;
  --accent-tint-2:  #214030;

  --gold:           #E0B44E;   /* 9.29:1 暗底上金可作文字 */
  --gold-ink:       #E0B44E;
  --gold-tint:      #2C2613;
  --gold-line:      rgba(224,180,78,.45);

  --success:        #4FB98E;  --success-tint: #1A3328;
  --warning:        #E0B44E;  --warning-tint: #2C2613;
  --danger:         #E07A5F;  --danger-tint:  #3A201A;   /* 6.12:1 */
  --info:           #6AB3D4;  --info-tint:    #14282F;
}
```

> **唯一红线：** 亮色下 `--gold #C0901E` 在纸上仅 **2.73:1**，**永不承载正文/小字**。需要金色文字时切 `--gold-ink #8C6A12`。这恰好和 §6 的金线视觉语言一致——亮色下金的本职是「线与填充」，不是「字」。

---

## 3. 字体排版

### 3.1 字体栈

```css
--font-ui:   -apple-system, BlinkMacSystemFont, "PingFang SC",
             "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
--font-read: "Songti SC", "STSong", "Noto Serif CJK SC", Georgia,
             "Times New Roman", serif;                  /* 正文/手稿/AI 输出 */
--font-mono: "SF Mono", "JetBrains Mono", ui-monospace,
             "PingFang SC", monospace;                  /* 字数、diff、日志 */
```

**分野是 Loom 的文学气质核心：UI 用 sans（PingFang），一切「作品文字」用 serif（宋体），数字/diff/日志用 mono。**

### 3.2 模块化字号阶梯（base 16px，比例 ≈1.2）

| Token | px | line-height | weight | letter-spacing | 用途 |
|---|---|---|---|---|---|
| `--fs-display` | 26 | 1.25 | 800 | -0.02em | Logo / 欢迎页大标题 |
| `--fs-h1` | 21 | 1.35 | 700 | -0.015em | 弹层标题 / 章节名 |
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
- 光标 `caret-color: var(--accent)`（墨在纸上）；选区 `::selection{background:var(--gold-tint)}`（选中即被金线圈出，呼应指纹）。

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
/* light：暖色调真实投影（非灰黑，匹配纸感） */
[data-theme="light"] {
  --shadow-1: 0 1px 2px rgba(35,36,30,.05);    /* 列表项 hover、手稿页 */
  --shadow-2: 0 2px 8px rgba(35,36,30,.07);    /* 下拉/tooltip */
  --shadow-3: 0 8px 24px rgba(35,36,30,.10);   /* 弹层/卡片 */
  --shadow-4: 0 16px 48px rgba(35,36,30,.14);  /* 模态 */
  --shadow-focus: 0 0 0 3px var(--accent-tint);
}
/* dark：几乎不用投影，靠表面变亮 + 极淡内描边定义边界 */
[data-theme="dark"] {
  --shadow-1: 0 0 0 1px rgba(255,255,255,.03);
  --shadow-2: 0 2px 8px rgba(0,0,0,.4),  inset 0 0 0 1px rgba(255,255,255,.04);
  --shadow-3: 0 8px 28px rgba(0,0,0,.5), inset 0 0 0 1px rgba(255,255,255,.05);
  --shadow-4: 0 18px 56px rgba(0,0,0,.6),inset 0 0 0 1px rgba(255,255,255,.06);
  --shadow-focus: 0 0 0 3px rgba(79,185,142,.25);
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

## 6. Loom 专属视觉语言（金＝指纹）

把品牌隐喻变成**功能可视化**，不是装饰。金在全局唯一的主角位置就在这些「接缝」处，因此别处必须克制——形成「金＝指纹」的强语义锚。

1. **暖金缝合线＝写作指纹。** 选区底色用 `--gold-tint`，写作指纹文件用金色标识。未来当引擎能识别「这句像你」时，在该段左侧落一道极细暖金竖线（`box-shadow: inset 3px 0 var(--gold-line)`），像一根经线被缝进织物——置信度用透明度表达，不用红黄绿交通灯。
2. **流水线＝织布工序进度。** 五道工序（设定师→大纲师→写手→编辑→润色师）是一排 pill，pill 间用细线相连；**完成的连线染成 `--gold`**，像纬线一段段把经线织过去。pending＝`--line` 空心；running＝`--accent` 描边＋极慢呼吸（1.6s，唯一允许的循环，reduced-motion 下静止）；done＝`--accent` 实心＋连线转金。
3. **嗓音指纹卡。** 侧栏顶部一张卡，把抽象的「指纹」变成能被信任的对象：来源状态（中性默认/已学样本/继承）＋织纹签名底。
4. **diff 即「补线」，不是「改错」。** learn/重写的 diff 不用刺眼红绿：**新增/更像你的**用 `--gold-tint` 底（金＝更像你，不是绿＝正确）；删除用 `--danger-tint` 底＋删除线（像拆掉的线头）。情绪从「被纠正」转为「被织密」。
5. **空状态＝一台等着上线的织布机。** 欢迎卡/空章节用一张极简线描 SVG（经线垂落、一两根纬线半穿，全 `--line`/`--gold-line` 细线无填充）＋一句 serif 文案。安静、有呼吸、只有 Loom 会这么做。

> 共同纪律：以上金线/纹理/呼吸默认低饱和，可被 reduced-motion 关掉。隐喻出现在分隔、进度、指纹这些接缝处，**正文区永远干净**。

---

## 7. 组件规范（要点）

- **按钮**：`--radius-sm`，padding `9px 15px`。`primary`＝墨绿实心；默认＝`--surface`＋`--line`，hover 边框转 `--text-soft`；`ghost`＝透明，hover `--line-soft`；`danger`＝`--danger` 实心；`mini`＝`5px 11px`/`--fs-xs`。聚焦可见 `--shadow-focus`。
- **输入/选择**：`--surface` 底＋`--line`，focus 边框 `--accent`＋`--shadow-focus`。
- **侧栏列表项**：`--radius-sm`，hover `--line-soft`，active `--accent-tint`＋`--accent-ink`。行末 `badge`（`改过`/`已学`＝`--accent-tint`）。hover 时浮出行内动作（如 ⟳ 重写本章）。
- **写作指纹项**：`--gold-ink` 文字＋金点标识，唯一带金的列表项。
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

- 对比度全部 ≥ AA（正文 4.5:1）；金色文字一律走 `--gold-ink`。实测见附录。
- 焦点可见：所有可交互元素 `:focus-visible` 有 `--shadow-focus`。
- `prefers-reduced-motion: reduce` → 动效降为 0.01ms。
- `prefers-color-scheme` 初始化主题；`<meta name="color-scheme">` 同步原生控件。
- **DOM 契约不可破**：`app.js` 以元素 `id` 与若干 class（`.pill .running .done`、`.list li.active`、`.fp`、`.badge.on`、`.chg.add/.rem`、`.hidden`）驱动逻辑。重设计**只换样式与新增节点，绝不重命名或删除既有 id / 既有 class 语义**。

### 附录：关键对比度实测（WCAG 2.1，AA=4.5:1）

| 组合 | 比值 | 判定 |
|---|---|---|
| Light text `#23241E` / bg `#FAF8F3` | 14.74 | AAA |
| Light text-soft `#66655A` / bg | 5.54 | AA |
| Light accent `#1C7C56` / bg | 4.87 | AA |
| Light accent-ink `#155F41` / tint `#E9F2EC` | 6.69 | AA |
| Light **gold `#C0901E` / bg** | **2.73** | ✗ 仅作线/填充 |
| Light gold-ink `#8C6A12` / bg | 4.73 | AA |
| Light white / accent 按钮 | 5.16 | AA |
| Light danger `#BB4A30` / bg | 4.78 | AA |
| Dark text `#E9E6DC` / bg `#16170F` | 14.45 | AAA |
| Dark text-soft `#B0AE9F` / bg | 8.08 | AAA |
| Dark accent `#4FB98E` / surface `#1E1F16` | 6.86 | AA |
| Dark gold `#E0B44E` / bg | 9.29 | AAA |
| Dark danger `#E07A5F` / bg | 6.12 | AA |

---

## 来源

- iA Writer — [Focus Mode](https://ia.net/writer/support/editor/focus-mode) · [Responsive Typography](https://ia.net/topics/responsive-typography-the-basics)
- Linear — [How we redesigned the Linear UI (II)](https://linear.app/now/how-we-redesigned-the-linear-ui)
- Cultured Code — [Things Big and Small](https://culturedcode.com/things/blog/2023/09/things-big-and-small/)
- [Dark Mode Design Systems (Muzli)](https://muz.li/blog/dark-mode-design-systems-a-complete-guide-to-patterns-tokens-and-hierarchy/)
- [中文 CSS 排版原則指南](https://simular.co/blog/post/2-中文-css-排版原則指南) · [W3C G18 对比度](https://www.w3.org/TR/WCAG20-TECHS/G18.html)
