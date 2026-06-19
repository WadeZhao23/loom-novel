# loom · 织布机

把一队分工 Agent 织成一条**写小说的流水线**,做成一个**桌面客户端**(Mac / Windows)。
读着你的"外置大脑",一键跑出一章正文;你手改,它越写越像你。

> v0.1 原型。后端可插拔:DeepSeek(国产、不用梯子)/ Claude Code / Codex,在界面里选。

## 它是什么

- **外置大脑**(每本书独有、会变):世界观 / 人物卡 / 卡章纲 / **写作指纹**。
- **skills**(跨书复用、不变):网文大神 / 去AI味 / 故事引擎 / 黄金开篇 / 评估自检 / 世界观引擎。
- **agents**(5 道工序):设定师 → 大纲师 → 写手 → 编辑 → 润色师。每个顶部 YAML 声明它读哪些文件。

5 个 agent 顺序跑,累积一个"本章工作区",每步读到目前为止的全部产物;写第 N 章还会读你手改后的第 N-1 章做衔接。

### 两条核心理念

- **写作指纹 = 像你**。写手/润色师照它写;你点"学这章的手改",它把**你的改动**蒸馏进指纹,越写越像你。指纹只学你的改动,绝不学 AI 自己的输出。
- **去AI味 = 独立功能**,只擦通用机器味、让文字像真人——不针对任何检测器作弊。

## 跑起来

```bash
pip install -e .          # 装好后有三个入口
loom-app                  # ① 桌面客户端(原生窗口)—— 推荐
loom-serve                # ② 兜底:在浏览器里跑(pywebview 出问题时用)
loom                      # ③ 内部引擎调试 CLI(开发用,非产品)
```

打开后:**新建一本书** → 顶栏选后端、填 DeepSeek API Key(`platform.deepseek.com` 申请)→ 左侧"喂样本"让它懂你的文风 → **写第 1 章**(看 5 个 agent 依次点亮)→ 在编辑器里手改 → **学这章的手改**(指纹更新,越来越像你)。

- 用 Claude Code / Codex 当后端时,顶栏切 provider 即可,需本机已装好 `claude` / `codex` 命令。

## 架构(为什么这么搭)

纯 Python 引擎(`loom/`:backends/agents/fingerprint/scaffold/state)→ 本地 FastAPI(`server.py`)→ Web 单页界面(`webui/`)→ PyWebView 套原生窗口(`desktop.py`)。
引擎跨平台、与界面解耦(进度走事件回调),Windows 复用 ≈95%,只需重打包。详见 [docs/adr/0004](docs/adr/0004-desktop-client-pywebview.md)。

## 设计记录

词表见 [CONTEXT.md](CONTEXT.md),关键决定见 [docs/adr/](docs/adr/)(指纹为什么是活的、为什么只学你的改动、为什么不绑检测分数、为什么做成桌面端)。
