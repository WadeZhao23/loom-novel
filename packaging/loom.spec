# -*- mode: python ; coding: utf-8 -*-
"""跨平台 PyInstaller 配置:Mac 出 Loom.app,Windows 出 dist/Loom/Loom.exe。

关键点(踩过的坑都在这):
- templates/ 和 webui/ 是【数据文件】,引擎用 Path(__file__).parent 找它们,
  必须按 `loom/...` 的包内路径打进去,否则冻结后找不到界面和模板。
- uvicorn / webview 有大量动态 import 和平台后端,用 collect_all 兜全。
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = os.path.dirname(SPECPATH)  # spec 在 packaging/ 下,上一级就是项目根

# --- 数据文件:保持 loom/ 包内结构 ---
datas = [
    (os.path.join(PROJECT_ROOT, "loom", "templates"), "loom/templates"),
    (os.path.join(PROJECT_ROOT, "loom", "webui"), "loom/webui"),
    (os.path.join(PROJECT_ROOT, "loom", "sample"), "loom/sample"),
]
binaries = []
hiddenimports = collect_submodules("loom")

# --- 动态 import 大户:整包收 ---
for pkg in ("uvicorn", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(PROJECT_ROOT, "packaging", "loom_app.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Loom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 产品形态:无终端窗口。首次调试可临时改 True 看报错
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Loom",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Loom.app",
        icon=os.path.join(PROJECT_ROOT, "packaging", "loom.icns"),  # 织标墨绿图标(make_icon.py 生成)
        bundle_identifier="com.chambers.loom",
        info_plist={
            "CFBundleName": "Loom",
            "CFBundleDisplayName": "Loom · 织布机",
            "CFBundleShortVersionString": "1.0.1",
            "NSHighResolutionCapable": True,
        },
    )
