# 形态:跨平台桌面客户端(Python 引擎 + 本地 Web UI + PyWebView),CLI 退为内部引擎

Loom 的产品形态从命令行改成**桌面客户端**。技术栈:**复用已有的纯 Python `loom` 引擎**(backends/agents/fingerprint/scaffold/state 不动)→ 套一层**本地 FastAPI** 暴露 JSON/流式接口 → **Web 单页 UI** → 用 **PyWebView** 套成原生窗口(Mac 用 WebKit、Windows 用 Edge WebView2)。打包分平台(Mac `.app` / Windows `.exe`),源码同一套。

后端仍可插拔:DeepSeek / Claude Code(`claude -p`)/ Codex(`codex`),在客户端里选。非沙盒进程,子进程调 claude/codex 最省事。

## 为什么

- **复用**:引擎刚建好并离线验证过,纯 Python + pathlib,Windows 直接能用;换原生 SwiftUI 等于把引擎重写或外挂,且 Windows 复用为 0。
- **跨平台**:用户明确要 Mac + Windows 复用。PyWebView 与 FastAPI 都跨平台,复用率 ≈95%,只有打包分平台。
- **可自检/可回退**:本地 Web 架构可在浏览器里直接开(pywebview 出问题时的兜底),5-agent 实时进度用流式接口很自然。

## Considered Options

- **PyWebView + 本地 FastAPI(选中)**:最轻、引擎全复用、跨平台、可浏览器兜底。
- **原生 SwiftUI**:观感最好但 Apple 独占、Windows 复用 0、引擎要重写,否决。
- **Tauri/Electron + Python 侧车**:也跨平台,但 Node/Rust 工具链更重,首版更慢,暂不选。

## 影响

引擎层去掉对 Rich `Console` 的直接依赖,改成**发进度事件(progress 回调)**;CLI 和桌面端各自把事件渲染成自己的样子。CLI 不再是产品,保留为内部调试入口。
