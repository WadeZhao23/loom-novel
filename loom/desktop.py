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
