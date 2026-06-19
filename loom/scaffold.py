"""loom init:纯离线铺项目骨架(永不联网、永不因缺 key 失败)。

只负责建文件、返回路径。怎么展示(CLI 树 / GUI 列表)交给前端。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .fingerprint import neutral_default

TEMPLATES_DIR = Path(__file__).parent / "templates"
HIGHLIGHT = "外置大脑/写作指纹.md"  # 全片卖点


def init(name: str, parent: Path | None = None) -> Path:
    """在 parent(默认当前目录)下建一个名为 name 的项目骨架,返回项目根路径。"""
    target = (parent or Path.cwd()) / name
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"目录 {target} 已存在且非空,换个名字或先清空。")

    shutil.copytree(TEMPLATES_DIR, target, dirs_exist_ok=True)

    # loom.toml 填上书名
    toml = target / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("__TITLE__", name), encoding="utf-8")

    # 写作指纹.md 离线落一份中性默认(不联网、不播种)
    (target / "外置大脑" / "写作指纹.md").write_text(neutral_default(), encoding="utf-8")

    # 正文/.原稿 先建好(AI 原稿快照将落在这里)
    (target / "正文" / ".原稿").mkdir(parents=True, exist_ok=True)
    gitkeep = target / "正文" / ".gitkeep"
    if gitkeep.exists():
        gitkeep.unlink()

    return target
