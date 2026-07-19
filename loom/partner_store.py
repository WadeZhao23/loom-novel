"""伙伴对话存储:一条对话一个 当前.jsonl,单行 append、坏行跳过。

上下文不是状态:删整个 .伙伴对话/ 目录,书完好无损(门禁/完成度从书文件推导)。
读回带 errors="replace" 兜 GBK(人可改文件);坏行 try/except 跳过(同 ledger「坏就当无」)。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths


def _cur(root: Path) -> Path:
    return root / paths.PARTNER_CUR_REL


def append_event(root: Path, event: dict) -> None:
    p = _cur(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(root: Path, *, tail: int | None = None) -> list[dict]:
    p = _cur(root)
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue   # 坏行跳过,坏就当无
        if isinstance(ev, dict):
            out.append(ev)
    return out[-tail:] if tail else out


def find_proposal(root: Path, pid: str) -> dict | None:
    for ev in reversed(read_events(root)):   # 从近到远找
        if ev.get("t") == "proposal" and ev.get("id") == pid:
            return ev
    return None


def archive_current(root: Path, stamp: str) -> None:
    p = _cur(root)
    if p.is_file():
        p.rename(p.with_name(f"归档-{stamp}.jsonl"))
