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


def _set_macos_app_name(name: str) -> None:
    """dev 模式(loom-app,进程是 python)下,把菜单栏/应用名从 'Python' 改成 name。

    从源码跑没有 .app 身份,macOS 会拿进程名当应用名,顶部菜单栏首项显示 'Python'。
    这里在 NSApplication 菜单构建前,改写 mainBundle 的 CFBundleName 即可纠正。
    打包成 .app 后由 Info.plist 决定,这步是 no-op(也不会出错)。
    (注:Activity Monitor / ps 里进程名仍是 python,那只有真打包 .app 才变。)
    """
    import sys

    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = name
    except Exception:
        pass  # 拿不到就算了,不影响启动


def _set_dock_icon() -> None:
    """dev 模式(loom-app,进程是 python)下,把 Dock 图标换成 Loom 的。

    打包成 .app 后 Dock 图标走 Info.plist 的 .icns,不需要这步;但从源码跑没有
    app 身份,默认是 Python 火箭,这里运行时补上。
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
    _set_macos_app_name("Loom")  # 菜单栏首项显示 Loom 而非 Python(须在建菜单前)
    port = _free_port()
    # log_config=None:别让 uvicorn 跑 dictConfig 去配彩色 formatter(内嵌服务器用不上,
    # 且无终端构建里 sys.stdout=None 会让它崩在 formatter 'default')。
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    )
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
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)


if __name__ == "__main__":
    run()
