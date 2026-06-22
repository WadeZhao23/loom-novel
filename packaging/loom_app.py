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

        # Windows 无终端(--noconsole)构建里 sys.stdout/stderr 是 None;
        # 任何 .isatty()/.write() 都会炸 —— uvicorn 配置日志的 formatter 'default'
        # 首当其冲(Windows 打不开就是这个)。指到 devnull,给所有库一个能安全写入的空流。
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")

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
