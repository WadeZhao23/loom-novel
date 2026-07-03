"""局部重写:选中一段,按写作指纹的嗓音 + 作者指令只重写这一段(整章作上下文)。

铁律(见 docs/design/局部重写.md):局部重写产出的是 AI 文本。learn 只学你的手改、绝不学 AI(ADR 0001)。
所以应用一次重写时,必须把这段 AI 改动【外科式同步进 .原稿 快照】,否则下次 learn 会把它当文风学进指纹。
不变量:快照永远 = "若全程只有 AI 生成、没人手打字" 的那一版。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import events
from .backends import Backend
from .fsutil import atomic_write_text, snapshot_chapter
from .paths import FINGERPRINT_REL, chapter_path, chapter_rel, snapshot_path

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


_REWRITE_SYSTEM = """你是作者本人的写手。我给你整章正文作上下文、作者选中要重写的一段、以及作者的指令。
按【写作指纹】的嗓音重写【选中段】,满足指令。只输出重写后的那一段本身,不要整章、不要任何解释或引号包裹。
默认不改剧情/人物/设定(除非指令明确要求);长度与原段相当;与前后文衔接自然。"""


def rewrite_span(project_root: Path, chapter_n: int, full_text: str, span: str,
                 instruction: str, backend: Backend, progress: Progress = _noop) -> str:
    if not span.strip():
        raise ValueError("没选中要重写的段落。先在正文里选一段。")
    fp_path = project_root / FINGERPRINT_REL
    fp = fp_path.read_text(encoding="utf-8") if fp_path.exists() else "(还没有写作指纹)"
    progress(events.info("正在按你的嗓音重写选中段…"))
    user = (
        f"## 写作指纹\n{fp}\n\n"
        f"## 整章上下文(供衔接,别整章输出)\n{full_text}\n\n"
        f"## 要重写的选中段\n{span}\n\n"
        f"## 作者指令\n{instruction.strip() or '(按你的嗓音改得更顺,别改剧情)'}"
    )
    return backend.complete(_REWRITE_SYSTEM, user, max_chars=len(span) + 300).strip()


def apply_rewrite(project_root: Path, chapter_n: int, new_content: str,
                  old_span: str, new_span: str) -> None:
    """落盘正文 + 外科式同步快照(把快照里的旧段换成新段,只换一处)。守住 learn 不被 AI 重写污染。"""
    out = chapter_path(project_root, chapter_n)
    snap = snapshot_path(project_root, chapter_n)
    body = new_content.rstrip() + "\n"
    snapshot_chapter(project_root, chapter_rel(chapter_n))  # 应用重写前留一版,误替换可回滚
    atomic_write_text(out, body)
    if snap.exists():
        s = snap.read_text(encoding="utf-8")
        # 旧段还在快照里 → 精准替换(其余手改部分仍是原 AI 版,learn 照常看见你的手改);
        # 不在(你刚手改过这段)→ 退化为整章作新 AI 基线(只丢信号,不污染)。
        s2 = s.replace(old_span, new_span, 1) if old_span and old_span in s else body
        atomic_write_text(snap, s2)
