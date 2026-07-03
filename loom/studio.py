"""书房:外置大脑的三个只读投影——时间轴 / 伏笔账本 / 专名册。

纯字符串切片,不调模型、不写盘、不打分;markdown 仍是唯一真相,这里只是"读法"。
(长篇作者最大的焦虑不是写不出下一章,是记不住前四十章——把 loom 已经在算的东西亮给他看。)
"""
from __future__ import annotations

from pathlib import Path

from .agents import _HARDFACT_KW, _SPOILER_KW, _md_h2_sections, _name_roster
from .config import load_config
from .hooks import _CH, parse_hooks, stale

CARD_REL = "外置大脑/卡章纲.md"


def timeline(root: Path | str) -> list[dict]:
    """时间轴:卡章纲逐章行(人写规划)+ 其下 [AI回顾] 摘要(learn 自动补)。"""
    p = Path(root) / CARD_REL
    if not p.is_file():
        return []
    out: list[dict] = []
    cur: dict | None = None
    recap_lines: list[str] = []
    in_recap = False

    def flush() -> None:
        nonlocal cur, recap_lines, in_recap
        if cur is not None:
            cur["recap"] = "\n".join(recap_lines).strip()
            out.append(cur)
        cur, recap_lines, in_recap = None, [], False

    for line in p.read_text(encoding="utf-8").splitlines():
        m = _CH.match(line)
        if m:
            flush()
            cur = {"n": int(m.group(1)), "plan": line.split(":", 1)[-1].split("：", 1)[-1].strip()}
            continue
        if cur is None:
            continue
        if line[:1] not in (" ", "\t"):
            if line.strip():
                flush()   # 顶格非章行(分卷标题等)→ 结束当前章块
            continue
        s = line.strip()
        if "[AI回顾]" in s:
            in_recap = True
            s = s.split("[AI回顾]", 1)[-1].strip()
        if in_recap and s:
            recap_lines.append(s)
    flush()
    return out


def foreshadow(root: Path | str) -> dict:
    """伏笔账本:全部 [埋设/推进/回收] 行(时间序)+ 悬空清单(复用 hooks.stale 的既有判据)。"""
    hooks = parse_hooks(root)
    rows = [{"chapter": h.chapter, "kind": h.kind, "text": h.text} for h in hooks]
    current = max((h.chapter for h in hooks), default=0)
    cfg = load_config(root)
    issues = stale(root, current + 1, cfg.foreshadow_distance) if current else []
    return {"rows": rows, "stale": [i.evidence for i in issues]}


def names(root: Path | str) -> dict:
    """专名册:人物卡的「类型 · 名字」名册 + 世界观里命中硬设定关键词的小节(标题+原文)。"""
    root = Path(root)
    roster = [ln.lstrip("- ").strip()
              for ln in _name_roster(root / "外置大脑" / "人物卡.md").splitlines() if ln.strip()]
    sections: list[dict] = []
    wv = root / "外置大脑" / "世界观.md"
    if wv.is_file():
        for head, body in _md_h2_sections(wv.read_text(encoding="utf-8")):
            if any(s in head for s in _SPOILER_KW):
                continue   # 反转段不进任何展示面(同硬设定直送的 deny 口径)
            if any(kw in head for kw in _HARDFACT_KW):
                lines = body.splitlines()
                sections.append({"title": head, "body": "\n".join(lines[1:]).strip()})
    return {"roster": roster, "sections": sections}


def studio(root: Path | str) -> dict:
    return {"timeline": timeline(root), "foreshadow": foreshadow(root), "names": names(root)}
