"""极简断点续跑账本:正文/.原稿/第N章.ledger.json 记每道工序的 sha + 产物 + 上游签名。

中途断网/报错时,已完成工序已落盘;重跑只算"未完成或上游已变"的工序,省 DeepSeek 字数计费。

红线:
- 只记工程续跑信息(sha/产物文本/上游签名),与"管 what 的设定师""管 voice 的写作指纹"都正交;不喂任何 agent。
- output 文本只用于续跑回填 workspace,落在 正文/.原稿/ 下,绝不回流写作指纹(与 learn 的 diff 链隔离)。
- 不引入 SQLite/向量/schema 版本协商/打分;坏 JSON 就当无 ledger 重跑,刻意极简。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .fsutil import atomic_write_text
from typing import Callable


def _ledger_path(root: Path, n: int) -> Path:
    return root / "正文" / ".原稿" / f"第{n}章.ledger.json"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_ledger(root: Path, n: int) -> dict:
    p = _ledger_path(root, n)
    if not p.exists():
        return {"chapter": n, "snapshot_sha": "", "steps": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"chapter": n, "snapshot_sha": "", "steps": {}}
    except Exception:  # 坏 JSON → 当无 ledger,重跑(极简:不做 schema 协商)
        return {"chapter": n, "snapshot_sha": "", "steps": {}}


def save_ledger(root: Path, n: int, led: dict) -> None:
    atomic_write_text(_ledger_path(root, n), json.dumps(led, ensure_ascii=False, indent=2))


def record_step(root: Path, n: int, role: str, output: str, upstream_sha: str) -> None:
    led = load_ledger(root, n)
    led["steps"][role] = {"output_sha": sha(output), "output": output, "upstream_sha": upstream_sha}
    save_ledger(root, n, led)


def record_snapshot(root: Path, n: int, final_text: str) -> None:
    led = load_ledger(root, n)
    led["snapshot_sha"] = sha(final_text.strip())
    save_ledger(root, n, led)


def chapter_drifted(root: Path, n: int) -> bool:
    """正文/第N章.md 与上次落盘的终稿不一致(作者手改过)→ True。"""
    out = root / "正文" / f"第{n}章.md"
    if not out.exists():
        return False
    led = load_ledger(root, n)
    if not led.get("snapshot_sha"):
        return False
    return sha(out.read_text(encoding="utf-8").strip()) != led["snapshot_sha"]


def resume_point(root: Path, n: int,
                 upstream_of: Callable[[str, list], str]) -> tuple[int, list]:
    """返回 (起始工序下标, 预填 workspace)。

    顺序找第一个 ledger 缺失、或上游签名已变的工序作续跑起点;其前的产物预填进 workspace。
    upstream_of(role, workspace_so_far) -> 该工序入场时的上游签名 sha。
    """
    from .agents import PIPELINE, load_agent

    led = load_ledger(root, n)
    steps = led.get("steps", {})
    workspace: list[tuple[str, str]] = []
    for i, role in enumerate(PIPELINE):
        entry = steps.get(role)
        if not entry or entry.get("upstream_sha") != upstream_of(role, workspace):
            return i, workspace            # 此工序起重跑,其前产物已预填
        workspace.append((load_agent(root, role).produces, entry["output"]))
    return len(PIPELINE), workspace        # 全部完成且上游未变
