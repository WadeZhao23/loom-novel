"""续跑签名与策略(S5):签名 v2 结构化逐项哈希 + 老账本 v1 原位升级垫片。

v1 的三个缺口(架构评审实测):① agent 的 system_prompt 不入签——改提示词后续跑
沿用旧产物(该重跑不重跑,静默吃旧设定);② config(终稿字数/回炉轮数)不入签——
改了也不重算;③ 裸字符串拼接非注入安全(不同工作区可拼出同串)。
v2 逐项「长度前缀 + 种类 + 名字 + 归一文本」哈希,并带 "v2:" 前缀标记版本。

【烧钱红线 · 迁移垫片】老账本(v1 签名)在新版首跑时逐工序用 v1 算法复核:
命中即**原位升级**为 v2 签名、绝不重跑——全体老书升级日零额外计费。
判不上(真变了/坏了)才从该工序重算,与既有语义一致。

策略归位于此,ledger.py 退化为纯存取(load/save/record);hardfacts 仍刻意不入签
(其源文件在设定师 reads 里,改硬设定必从第 0 棒失配重跑——见 run_pipeline 注释)。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import ledger

SIG_PREFIX = "v2:"


def sig_v2(system_prompt: str, read_items: list[tuple[str, str]],
           workspace: list[tuple[str, str]], prev: str, cfg_bits: dict) -> str:
    """结构化上游签名。reads 按名排序(顺序不敏感)+ 逐文件 strip(末尾空白不敏感,
    与 prompt 拼装同口径);workspace 保持工序序(顺序即语义)且逐项带 produces 定界。"""
    h = hashlib.sha256()

    def item(kind: str, name: str, text: str) -> None:
        text = (text or "").replace("\r\n", "\n")
        for part in (kind, name, text):
            b = part.encode("utf-8")
            h.update(str(len(b)).encode("ascii"))
            h.update(b"\x1f")
            h.update(b)
        h.update(b"\x1e")

    item("system", "", system_prompt)
    for rel, text in sorted(read_items):
        item("read", rel, (text or "").strip())
    for produces, text in workspace:
        item("ws", produces, text)
    item("prev", "", prev)
    item("cfg", "", json.dumps(cfg_bits, ensure_ascii=False, sort_keys=True))
    return SIG_PREFIX + h.hexdigest()


def sig_v1(knowledge: str, workspace: list[tuple[str, str]], prev: str) -> str:
    """旧算法逐字节复刻——只给迁移垫片复核老账本用,永远别改。"""
    return ledger.sha(knowledge + "\x1f" + "\n".join(t for _, t in workspace) + "\x1f" + prev)


def resume_point(root: Path, n: int, upstream_v2, upstream_v1) -> tuple[int, list]:
    """返回 (起始工序下标, 预填 workspace)。

    逐工序:v2 命中→跳过;老签名(无 v2: 前缀)且 v1 复核命中→原位升级为 v2 后跳过
    (零重跑);都不中→从此工序重算。升级过的账本落盘一次。
    """
    from .agents import PIPELINE, load_agent   # 函数级导入:resume 是策略层,静态依赖单向

    led = ledger.load_ledger(root, n)
    steps = led.get("steps", {})
    workspace: list[tuple[str, str]] = []
    upgraded = False

    def _done(idx: int) -> tuple[int, list]:
        if upgraded:
            ledger.save_ledger(root, n, led)
        return idx, workspace

    for i, role in enumerate(PIPELINE):
        entry = steps.get(role)
        if not entry:
            return _done(i)
        have = str(entry.get("upstream_sha", ""))
        want2 = upstream_v2(role, workspace)
        if have == want2:
            pass
        elif not have.startswith(SIG_PREFIX) and have == upstream_v1(role, workspace):
            entry["upstream_sha"] = want2   # 老账本原位升级:同一上游,只换签名算法
            upgraded = True
        else:
            return _done(i)
        workspace.append((load_agent(root, role).produces, entry["output"]))
    return _done(len(PIPELINE))
