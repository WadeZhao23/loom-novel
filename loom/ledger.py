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

from .chaptertext import body_key
from .fsutil import atomic_write_text
from .paths import chapter_path, ledger_path as _ledger_path
from typing import Callable


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
    # snapshot_sha 只比【正文体】(chaptertext.body_key 归一):改标题不算「手改正文」,不该触发 drifted 重写闸。
    # 老章无 H1 时 body_key 原样返回,sha 与旧账本一致——向后兼容,无需迁移。
    led = load_ledger(root, n)
    led["snapshot_sha"] = sha(body_key(final_text))
    save_ledger(root, n, led)


def chapter_drifted(root: Path, n: int) -> bool:
    """正文/第N章.md 的【正文体】与上次落盘的终稿不一致(作者手改过正文)→ True。改标题不算。

    与 server 徽标 / cli status 的 body_changed 同口径(body_key 归一),只是这里比的是落盘 sha。"""
    out = chapter_path(root, n)
    if not out.exists():
        return False
    led = load_ledger(root, n)
    if not led.get("snapshot_sha"):
        return False
    return sha(body_key(out.read_text(encoding="utf-8"))) != led["snapshot_sha"]


# 续跑【策略】(找起点/签名比对/老账本升级)已归位 loom/resume.py(S5);
# 本模块只留纯存取——load/save/record/drifted,坏 JSON 当无账本,刻意极简。
