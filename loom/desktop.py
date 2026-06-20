"""桌面入口:本地起 FastAPI(127.0.0.1),再用 PyWebView 套成原生窗口。

- loom-app   : 原生窗口(Mac WebKit / Windows WebView2)
- loom-serve : 不开窗口,只起服务并打开浏览器(pywebview 出问题时的兜底)
"""

from __future__ import annotations

import socket
import threading
import time

import uvicorn

from .server import app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(port: int, timeout: float = 8.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)


def _set_dock_icon() -> None:
    """dev 模式(loom-app,进程是 python)下,把 Dock 图标换成 Loom 的。

    打包成 .app 后 Dock 图标走 Info.plist 的 .icns,不需要这步;但从源码跑没有
    app 身份,默认是 Python 火箭,这里运行时补上。菜单栏名仍会是 Python——那由
    bundle 决定,只有打包 .app 能根治。
    """
    try:
        from pathlib import Path

        png = Path(__file__).resolve().parent / "webui" / "app-icon.png"
        if not png.exists():
            return
        from AppKit import NSApplication, NSImage

        img = NSImage.alloc().initByReferencingFile_(str(png))
        if img and img.isValid():
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass  # 锦上添花,失败不影响启动


def run() -> None:
    """原生窗口。"""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    _wait_up(port)

    import webview

    webview.create_window(
        "Loom · 织布机",
        f"http://127.0.0.1:{port}",
        width=1180, height=780, min_size=(920, 600),
    )
    _set_dock_icon()
    webview.start()


def serve() -> None:
    """无窗口兜底:起服务 + 自动开浏览器。"""
    import webbrowser

    port = _free_port()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Loom 跑在 http://127.0.0.1:{port}  (Ctrl-C 退出)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    run()
