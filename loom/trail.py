"""写章轨迹:`正文/.轨迹/第N章.jsonl`,agent 模式产物级续跑的料。

设计(docs/superpowers/specs/2026-08-16-loom-continual-harness-design.md §5.1/§7.5):
- **纪律照抄 `.伙伴对话/当前.jsonl`**:单事件单行 append、坏行跳过、写盘原子性靠「一行一 flush」
  ——断电最多丢正在写的那一行,前面的产物照常可续。
- 【红线】**永不当状态真相**。门禁/完成度/章节列表一律从文件现状推导,谁都不许读它派生状态。
  它只有一个用途:重跑时把【已提交且上游没变】的产物原样放回工作区,省重算的钱。
- **整个目录删掉,书完好无损**——下次从头跑而已(同 `.伙伴对话/` 的待遇)。
- 进 `loom backup`(backup 只跳顶层目录,这层自动含进去)、进 `paths.CHAPTER_ARTIFACTS`
  (删章/重编号跟着搬——漏了会串章)。

存的是【过完关卡之后】的文本:重放不再重跑质检/去AI味,否则每次续跑都要为同一份稿重复付费。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths


def record_commit(root: Path | str, n: int, artifact: str, text: str, sig: str) -> None:
    """记一次成功提交。任何异常都吞掉——轨迹是省钱的便利,绝不拖累出稿。"""
    try:
        p = paths.trail_path(root, n)
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"t": "commit", "产物": artifact, "text": text, "sig": sig},
                          ensure_ascii=False)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_commits(root: Path | str, n: int) -> list[dict]:
    """按提交序返回 commit 事件。没有轨迹/坏行 → 跳过,绝不抛。"""
    p = paths.trail_path(root, n)
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue          # 半截行(断电写到一半)→ 跳过,前面的照样可用
        if isinstance(ev, dict) and ev.get("t") == "commit":
            out.append(ev)
    return out


def chapters(root: Path | str) -> list[int]:
    """盘上有轨迹的章号(升序)。证据采集按它枚举——证据的来源是轨迹,不是正文文件
    (正文可能还没落、或作者删了又写)。"""
    d = Path(root) / paths.TRAIL_DIR
    if not d.is_dir():
        return []
    out = []
    for p in d.glob("第*章.jsonl"):
        stem = p.stem
        if stem.startswith("第") and stem.endswith("章") and stem[1:-1].isdigit():
            out.append(int(stem[1:-1]))
    return sorted(out)


def clear(root: Path | str, n: int) -> None:
    """丢弃本章轨迹(上游变了、或作者要求从头跑)。不存在也不报错。"""
    try:
        paths.trail_path(root, n).unlink(missing_ok=True)
    except OSError:
        pass
