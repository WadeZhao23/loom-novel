"""PyInstaller 的入口脚本。

打包出来的就是这个:起本地 FastAPI + PyWebView 原生窗口。
设 LOOM_NO_WINDOW=1 时退回浏览器兜底(调试用)。
pyproject 里的 `loom-app` 仍是开发期 `pip install -e .` 的入口,二者并存。
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    # 冻结后没有终端;把未捕获异常写到用户能找到的日志里,别静默退出
    if getattr(sys, "frozen", False):
        import tempfile
        from pathlib import Path

        log = Path(tempfile.gettempdir()) / "loom-crash.log"

        def _hook(exc_type, exc, tb):
            import traceback

            with log.open("a", encoding="utf-8") as f:
                traceback.print_exception(exc_type, exc, tb, file=f)
            sys.__excepthook__(exc_type, exc, tb)

        sys.excepthook = _hook

    if os.environ.get("LOOM_NO_WINDOW") == "1":
        from loom.desktop import serve

        serve()
    else:
        from loom.desktop import run

        run()


if __name__ == "__main__":
    main()
