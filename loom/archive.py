"""备份与导出:纯本地、不联网。对冲作者第一恐惧——稿子别丢、随时拿得出来。

- export_text:把全书正文拼成一个 txt(发起点/番茄、留档用)。
- backup_project:把整本书打包成 zip(不含 .env 密钥),供你拷去云盘/U盘。
两件都只读写本机文件,不调任何后端、不联网。
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path

from .config import load_config

_EXPORT_DIR = "导出"
_BACKUP_DIR = ".备份"
# 顶层目录/文件:不进备份。.备份(防递归套娃)、.env(密钥别进可移动的包)、导出件、缓存。
_BACKUP_SKIP = {_BACKUP_DIR, ".env", _EXPORT_DIR, "__pycache__"}


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe(name: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "_", name).strip() or "未命名"


def _title(project_root: Path) -> str:
    try:
        return load_config(project_root).title or project_root.name
    except Exception:
        return project_root.name


def export_text(project_root: Path) -> dict:
    """全书正文 → 一个 txt,落到 项目/导出/。返回 {path, chapters, chars}。"""
    body = project_root / "正文"
    chapters = sorted(int(p.stem[1:-1]) for p in body.glob("第*章.md")) if body.exists() else []
    if not chapters:
        raise ValueError("还没有正文可导出。先写一章。")
    title = _title(project_root)
    parts = []
    for n in chapters:
        text = (body / f"第{n}章.md").read_text(encoding="utf-8").strip()
        parts.append(f"第{n}章\n\n{text}")
    content = f"《{title}》\n\n\n" + "\n\n\n".join(parts) + "\n"
    out_dir = project_root / _EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe(title)}-{_stamp()}.txt"
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "chapters": len(chapters), "chars": len(content)}


def backup_project(project_root: Path, keep: int = 10) -> dict:
    """整本打包成 zip(不含 .env 密钥),落到 项目/.备份/;只留最近 keep 份。

    返回 {path, size, kept}。注意:zip 留在本机只是半个备份——拷到云盘/U盘才算真安全。
    """
    if not (project_root / "loom.toml").exists():
        raise FileNotFoundError(f"{project_root} 不是 loom 项目(没有 loom.toml)。")
    title = _safe(_title(project_root))
    bdir = project_root / _BACKUP_DIR
    bdir.mkdir(parents=True, exist_ok=True)
    zpath = bdir / f"{title}-{_stamp()}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(project_root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(project_root)
            if rel.parts[0] in _BACKUP_SKIP:  # 顶层就跳过(.备份/.env/导出/缓存)
                continue
            z.write(f, rel.as_posix())
    # 轮转:只留最近 keep 份,避免无限堆积
    backups = sorted(bdir.glob(f"{title}-*.zip"))
    for old in backups[:-keep]:
        old.unlink()
    return {"path": str(zpath), "size": zpath.stat().st_size, "kept": min(len(backups), keep)}
