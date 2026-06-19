"""一点点持久状态:指纹来源、哪些章 learn 过。放在项目根的 .loom_state.json。"""

from __future__ import annotations

import json
from pathlib import Path

_STATE_FILE = ".loom_state.json"


def _path(project_root: Path) -> Path:
    return project_root / _STATE_FILE


def load_state(project_root: Path) -> dict:
    p = _path(project_root)
    if not p.exists():
        return {"fingerprint_source": "default", "learned": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"fingerprint_source": "default", "learned": []}


def save_state(project_root: Path, state: dict) -> None:
    _path(project_root).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def set_fingerprint_source(project_root: Path, source: str) -> None:
    st = load_state(project_root)
    st["fingerprint_source"] = source
    save_state(project_root, st)


def mark_learned(project_root: Path, chapter_n: int) -> None:
    st = load_state(project_root)
    learned = set(st.get("learned", []))
    learned.add(chapter_n)
    st["learned"] = sorted(learned)
    save_state(project_root, st)
