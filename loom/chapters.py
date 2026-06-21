"""章节结构操作:删除 / 在后插入空章 / 上下移。

核心是**安全重编号**:把一章的全部关联产物一起搬,两段式 rename(先全搬到临时名,
再搬到目标名)避免碰撞;删除走 正文/.回收站/ 可恢复;state.learned 章号同步重映射。

不动**卡章纲**:那是人写的规划,自动改太脆;改完只提示作者手动同步对应章号。
所有移动复用 fsutil 的原子语义(os.replace),配合既有的原子写 + 单章历史,不丢稿。
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from . import state
from .fsutil import atomic_write_text

# 每章的关联产物:(相对目录, 文件名模板, 是否目录)
_ARTIFACTS = [
    ("正文", "第{n}章.md", False),
    ("正文/.原稿", "第{n}章.md", False),
    ("正文/.原稿", "第{n}章.ledger.json", False),
    ("正文/.历史", "第{n}章", True),
    (".审稿留痕", "第{n}章.md", False),
    ("外置大脑/.指纹历史", "第{n}章-learn前.md", False),
]
SYNC_NOTE = "章节已重排,记得同步更新「卡章纲」里对应的章号(卡章纲是你写的,没自动改)。"


def chapter_numbers(root: Path | str) -> list[int]:
    body = Path(root) / "正文"
    return sorted(int(p.stem[1:-1]) for p in body.glob("第*章.md")) if body.is_dir() else []


def _paths(root: Path, n: int) -> list[Path]:
    return [Path(root) / d / tmpl.format(n=n) for d, tmpl, _ in _ARTIFACTS]


def _move(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():  # 两段式本应已避让,兜底清掉残留
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    os.replace(src, dst)


def _renumber(root: Path, mapping: dict[int, int]) -> None:
    """按 {old: new} 把各章全部产物搬到新号;两段式防碰撞;同步重映射 state.learned。"""
    root = Path(root)
    mapping = {o: n for o, n in mapping.items() if o != n}
    if mapping:
        staged: list[tuple[Path, int, int]] = []  # (临时路径, artifact 下标, new)
        for old, new in mapping.items():           # 段一:old → 临时名
            for i, src in enumerate(_paths(root, old)):
                if src.exists():
                    tmp = src.with_name(f"__rn{old}_{i}__{src.name}")
                    _move(src, tmp)
                    staged.append((tmp, i, new))
        for tmp, i, new in staged:                 # 段二:临时 → new
            d, tmpl, _ = _ARTIFACTS[i]
            _move(tmp, root / d / tmpl.format(n=new))
    # state.learned 跟着重映射(删除的章已在调用方先摘掉)
    st = state.load_state(root)
    st["learned"] = sorted({mapping.get(x, x) for x in st.get("learned", [])})
    state.save_state(root, st)


def delete_chapter(root: Path | str, n: int) -> dict:
    root = Path(root)
    nums = chapter_numbers(root)
    if n not in nums:
        raise ValueError(f"第 {n} 章不存在")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    trash = root / "正文" / ".回收站" / f"第{n}章-{ts}"
    for d, tmpl, _ in _ARTIFACTS:                    # 1) 进回收站(镜像目录结构,避免同名互相覆盖)
        src = root / d / tmpl.format(n=n)
        if src.exists():
            _move(src, trash / d / src.name)
    state.unmark_learned(root, n)                   # 2) learned 先摘掉这章
    _renumber(root, {k: k - 1 for k in nums if k > n})  # 3) 高于 n 的整体下移 1
    return {"ok": True, "deleted": n, "trash": str(trash), "note": SYNC_NOTE}


def insert_after(root: Path | str, n: int) -> dict:
    """在第 n 章后插入一章空章(n=0 表示插到最前)。新空章号 = n+1。"""
    root = Path(root)
    nums = chapter_numbers(root)
    _renumber(root, {k: k + 1 for k in nums if k > n})  # n 之后整体上移 1,空出 n+1
    new_n = n + 1
    atomic_write_text(root / "正文" / f"第{new_n}章.md", "")
    return {"ok": True, "inserted": new_n, "note": SYNC_NOTE}


def move_chapter(root: Path | str, n: int, direction: str) -> dict:
    root = Path(root)
    nums = chapter_numbers(root)
    if n not in nums:
        raise ValueError(f"第 {n} 章不存在")
    other = n - 1 if direction == "up" else n + 1
    if other not in nums:
        raise ValueError("已经到头了")
    _renumber(root, {n: other, other: n})           # 交换两章
    return {"ok": True, "moved": n, "to": other, "note": SYNC_NOTE}
