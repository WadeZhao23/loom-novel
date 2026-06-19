#!/usr/bin/env bash
# 一键打包。在项目根跑:  bash packaging/build.sh
# Mac 产出 dist/Loom.app;Windows 在 Git Bash / WSL 里跑产出 dist/Loom/Loom.exe
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PY" ]; then PY="python3"; fi

echo "==> 用 $PY"
"$PY" -m pip install -q --upgrade pyinstaller
"$PY" -m PyInstaller --noconfirm --clean packaging/loom.spec

echo ""
echo "==> 完成。产物在 dist/"
ls -lh dist/ 2>/dev/null || true
