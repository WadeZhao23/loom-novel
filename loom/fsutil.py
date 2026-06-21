"""原子写盘 + 单章版本历史 —— 守住「稿子很安全」这个核心承诺。

- atomic_write_text:所有"截断式"写盘都走它。写同目录隐藏 .tmp → flush + os.fsync →
  os.replace(POSIX 上是原子 rename)。崩溃/断电/磁盘满最坏只丢这一次没落地的写,
  绝不会把已有正文截成 0 字节或半截。
- 章节正文在被覆盖前留一份历史快照(正文/.历史/第N章/<时间戳>.md),误删/误覆盖可回滚;
  与「备份整本」(zip 灾备)互补——历史是单章后悔药。
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

HISTORY_DIR = ".历史"
_KEEP = 30  # 每章最多保留的历史份数
_CHAP_RE = re.compile(r"^正文/(第.+?章)\.md$")


def atomic_write_text(path: Path | str, content: str, encoding: str = "utf-8") -> None:
    """原子写文本:写 .tmp → fsync → os.replace。失败不会留下半截目标文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # 原子替换:要么旧的、要么新的,不会有中间态
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _chapter_key(rel: str) -> str | None:
    m = _CHAP_RE.match(str(rel).replace("\\", "/"))
    return m.group(1) if m else None


def _hist_dir(root: Path | str, key: str) -> Path:
    return Path(root) / "正文" / HISTORY_DIR / key


def snapshot_chapter(root: Path | str, rel: str) -> None:
    """覆盖正文章节前调用:把"当前磁盘内容"存一份历史(空内容不存)。非章节路径直接跳过。"""
    key = _chapter_key(rel)
    if not key:
        return
    cur = Path(root) / rel
    if not cur.is_file():
        return
    try:
        content = cur.read_text(encoding="utf-8")
    except OSError:
        return
    if not content.strip():
        return
    hist = _hist_dir(root, key)
    # 带微秒 → 文件名唯一且「字典序==时间序」,不必再补序号(同秒多次也不会撞/乱序)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    atomic_write_text(hist / f"{ts}.md", content)
    _prune(hist)


def _prune(hist: Path) -> None:
    snaps = sorted(hist.glob("*.md"))
    for p in snaps[: max(0, len(snaps) - _KEEP)]:
        try:
            p.unlink()
        except OSError:
            pass


def list_history(root: Path | str, rel: str) -> list[dict]:
    key = _chapter_key(rel)
    if not key:
        return []
    hist = _hist_dir(root, key)
    if not hist.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(hist.glob("*.md"), reverse=True):  # 新→旧
        try:
            txt = p.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append({
            "id": p.stem,
            "chars": len(re.findall(r"\S", txt)),
            "preview": txt.strip()[:140],
        })
    return out


def restore_history(root: Path | str, rel: str, snap_id: str) -> str:
    """回滚到某历史版本;回滚前先把当前版本也存一份(可再回滚回来)。返回恢复后的内容。"""
    key = _chapter_key(rel)
    if not key:
        raise ValueError("不是正文章节,无法回滚")
    src = _hist_dir(root, key) / f"{snap_id}.md"
    if not src.is_file():
        raise FileNotFoundError("该历史版本不存在")
    content = src.read_text(encoding="utf-8")
    snapshot_chapter(root, rel)
    atomic_write_text(Path(root) / rel, content)
    return content
