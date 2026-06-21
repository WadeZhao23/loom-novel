# 图标:iconfont(阿里矢量图标库)Symbol 接入

界面里原来的 emoji 已全部换成 **iconfont Symbol(SVG sprite)** 图标。
代码侧已接好,只差一份「图标精灵文件」——它由你在 iconfont.cn 的项目导出。

## 怎么用(两步)

1. **建项目挑图标**
   - 打开 <https://www.iconfont.cn>,登录后「资源管理 → 我的项目」新建一个项目(比如 `loom`)。
   - 按下面的「采购清单」搜图标,逐个「添加入库」再「添加至项目」。
   - **图标 id 要对上**:把每个图标的命名改成清单里的 `icon-xxx`(图标 hover → 编辑 → 改 FontClass/名称)。
     - 嫌改名烦?也行——直接改 [`loom/webui/app.js`](../../loom/webui/app.js) 顶部的 `IC` 映射表,把右边的值换成你项目里的实际 id。**只改这一处**,各处调用不用动。
   - 风格建议:**线性(line)、24 单位、统一描边**,跟「织」设计系统的克制气质一致。

2. **导出精灵文件,放进项目**
   - 在项目页切到 **Symbol** 标签 → 点 **「下载至本地」**,得到一个 `iconfont.js`。
   - 把它存为 **`loom/webui/iconfont.js`**(覆盖即可)。`index.html` 已经 `<script src="/iconfont.js">` 引好了,刷新就显示。
   - 这样图标随包走、**离线可用**,符合 Loom「东西不离开你电脑」的原则。
   - (想图省事也可以把 `index.html` 里的 `/iconfont.js` 换成 iconfont 给的在线链接 `//at.alicdn.com/t/c/font_xxx.js`,但那样要联网。)

> 接上之前:界面照常能用,文字标签都在,只是图标位先空着。接上后零改动自动显示。

## 采购清单(id → 用途)

| id | 用途 | 搜索关键词建议 |
|---|---|---|
| `icon-book` | 欢迎页「先看看样例」 | book / 书 |
| `icon-key` | 欢迎页「怎么拿 API key」 | key / 钥匙 |
| `icon-sun` | 顶栏主题切换(亮色时显示) | sun / 太阳 |
| `icon-moon` | 顶栏主题切换(暗色时显示) | moon / 月亮 |
| `icon-focus` | 顶栏「专注模式」 | focus / 全屏 / 聚焦 |
| `icon-fullscreen-exit` | 「退出专注」 | exit fullscreen / 退出全屏 |
| `icon-chevron-right` | 侧栏折叠区箭头(展开时 CSS 自动转 90°) | chevron / 箭头 / 展开 |
| `icon-doc` | 侧栏「正文」 | doc / 文档 / 文稿 |
| `icon-arrow-right` | 「写下一章」 | arrow right / 右箭头 |
| `icon-arrow-left` | 顶栏「回首页」(退出当前书) | arrow left / 返回 / 左箭头 |
| `icon-export` | 「导出全书」 | export / 导出 |
| `icon-save` | 「备份整本」 | save / 磁盘 / 保存 |
| `icon-brain` | 侧栏「外置大脑」 | brain / 大脑 |
| `icon-fingerprint` | 「写作指纹」卡 | fingerprint / 指纹 |
| `icon-magic` | 「喂样本 seed」 | magic / 魔法棒 / 星 |
| `icon-tool` | 「skills」 | tool / 工具 / 扳手 |
| `icon-robot` | 「agents」 | robot / 机器人 |
| `icon-search` | 章内搜索 | search / 放大镜 |
| `icon-scissors` | 「重写选中」 | scissors / 剪刀 |
| `icon-trend-up` | 「学这章的手改 learn」 | trend up / 上升 / 增长 |
| `icon-arrow-up` | 搜索:上一个 | arrow up |
| `icon-arrow-down` | 搜索:下一个 | arrow down |
| `icon-close` | 关闭搜索 | close / 关闭 / ✕ |
| `icon-pin` | learn 面板「写后摘要」 | pin / 图钉 |
| `icon-edit` | 流水线日志:改动留痕 | edit / 笔 |
| `icon-check` | 流水线/自检:通过、完成 | check / 对勾 |
| `icon-cross` | 流水线/自检:失败 | close / 错误 / ✕ |
| `icon-refresh` | 重写本章、回炉重写 | refresh / 循环 / 重做 |
| `icon-warning` | 流水线:跑满残留警告 | warning / 警告 |
| `icon-play` | 流水线:工序开始 | play / 三角 |
| `icon-skip` | 流水线:跳过工序 | skip / 跳过 |

## 工作原理(给以后维护的人)

- HTML 里图标位是占位符:`<span class="ico" data-ico="export"></span>`(或纯图标按钮直接 `data-ico` 挂在 `<button>` 上)。
- [`app.js`](../../loom/webui/app.js) 的 `hydrateIcons()` 在 `DOMContentLoaded` 把占位符填成
  `<svg class="icon"><use xlink:href="#icon-export"></use></svg>`。
- 动态生成的图标(自检对勾、日志状态、章节「重写」按钮、主题切换)用 `icon("name")` 直接拼。
- 样式见 [`style.css`](../../loom/webui/style.css) §3b:`.icon { width:1em;height:1em;fill:currentColor }` ——
  **尺寸跟字号、颜色跟文字色**,所以明暗主题、强调色全自动适配,无需为图标单独配色。
- 原来的几个排版符号也已并入 iconfont:折叠箭头 `▸▾` → 一个 `icon-chevron-right`(展开转 90°)、
  指纹项的 `❖` → `icon-fingerprint`、状态确认的 `✓` → `icon-check`。
  - 例外:**API Key 输入框的占位符**按 HTML 规范只能放纯文本、塞不进 SVG,那里的 `✓` 直接去掉了(显示「API Key 已设置」)。
- 唯一保留的是命令面板/标题里的 **`⌘` 快捷键提示**——那是键盘按键记号(且多在 `title` 等纯文本位),不是图标,保留更易读。
