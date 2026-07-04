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


# 固定默认端口:localStorage(记住上次的书 / 最近书 / 主题)按 origin=127.0.0.1:端口 存,
# 端口每次变 origin 就变、存的全丢——这正是「每次进来都要重开书」的真根因。固定端口=稳定 origin,
# 本地记忆才留得住。端口被别的程序占了才回退随机(此时那次记忆丢失可接受,极少发生)。
DEFAULT_PORT = 8473  # 冷门端口,撞车概率低;LOOM_PORT 可覆盖


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_port() -> int:
    import os
    want = int(os.environ.get("LOOM_PORT", DEFAULT_PORT))
    if _port_free(want):
        return want
    s = socket.socket()          # 固定端口被占 → 回退随机(记忆这次留不住,但至少能起来)
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
    """原生窗口;窗口起不来(pythonnet/.NET/WebView2 缺失)就自动退回浏览器,不再硬崩。"""
    import os
    import sys

    _set_macos_app_name("Loom")  # 菜单栏首项显示 Loom 而非 Python(须在建菜单前)
    port = _free_port()
    # log_config=None:别让 uvicorn 跑 dictConfig 去配彩色 formatter(内嵌服务器用不上,
    # 且无终端构建里 sys.stdout=None 会让它崩在 formatter 'default')。
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    )
    threading.Thread(target=server.run, daemon=True).start()
    _wait_up(port)

    # Windows 上强制用系统自带的 .NET Framework(netfx),绕开多数机器没装的 CoreCLR(.NET 5+)。
    # pywebview 的 WinForms 后端靠 pythonnet 托管 .NET,`import clr` 正是杂牌/精简版 Windows
    # 上崩 "Failed to resolve Python.Runtime.Loader.Initialize" 的高发区。
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")

    try:
        import webview

        class _JsApi:
            """暴露给 webui 的原生能力桥(window.pywebview.api.*)。
            C端用户不该手输文件路径——导入书/选文件夹走系统对话框。"""

            def pick_folder(self):
                w = webview.windows[0] if webview.windows else None
                if w is None:
                    return None
                res = w.create_file_dialog(webview.FOLDER_DIALOG)
                return res[0] if res else None   # 取消选择 → None,前端保持原值

        webview.create_window(
            "Loom · 织布机",
            f"http://127.0.0.1:{port}",
            width=1180, height=780, min_size=(920, 600),
            js_api=_JsApi(),
        )
        _set_dock_icon()
        webview.start()
    except Exception:
        # pythonnet/.NET/WebView2 任何问题都不该让整个 App 崩(用户群里精简版 Windows 很多)。
        # 服务线程已经在跑,直接开浏览器指向同一端口,并 hold 住进程别退出,等同 serve() 兜底。
        import traceback
        import webbrowser

        traceback.print_exc()  # 会被 loom_app 的 excepthook 落到 loom-crash.log
        webbrowser.open(f"http://127.0.0.1:{port}")
        while True:
            time.sleep(1)


def serve() -> None:
    """无窗口兜底:起服务 + 自动开浏览器。"""
    import webbrowser

    port = _free_port()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Loom 跑在 http://127.0.0.1:{port}  (Ctrl-C 退出)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)


if __name__ == "__main__":
    run()
