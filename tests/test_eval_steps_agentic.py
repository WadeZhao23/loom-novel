"""棒级归因在 agent 模式下也要收得到产物。

`evals.generate.collect_steps` 原本只从 ledger 按【角色键】取五棒产物,而 agent 模式
写的是 `trail`(按【产物键】)——实测 ledger.steps 为空 → 五棒全 None、归因整个失效,
「该改哪一棒的 prompt」这个 eval 的核心问题在新架构上答不了。

产物名↔角色名的映射从 `artifacts.ARTIFACTS` 派生(spec.persona),不手抄五个名字。
"""
from __future__ import annotations

import dataclasses

from evals.generate import collect_steps
from loom import artifacts, trail
from loom.config import load_config


def _lay_trail(project, n: int) -> dict[str, str]:
    """按产物表往轨迹里铺一份「agent 交过的五件产物」,返回 角色→原文 的期望值。"""
    want = {}
    for spec in artifacts.ARTIFACTS:
        if not spec.persona:
            continue
        text = f"{spec.persona}交的{spec.name}正文。"
        trail.record_commit(project, n, spec.name, text, f"v2:{spec.persona}")
        want[spec.persona] = text
    return want


def test_agent模式从轨迹收得到五棒产物(project, tmp_path):
    want = _lay_trail(project, 3)
    got = collect_steps(project, 3, tmp_path, agentic=True)
    assert got == want


def test_agent模式下产物落进steps目录(project, tmp_path):
    _lay_trail(project, 3)
    collect_steps(project, 3, tmp_path, agentic=True)
    for spec in artifacts.ARTIFACTS:
        if spec.persona:
            assert (tmp_path / "steps" / f"{spec.persona}.md").is_file()


def test_agent模式没交的产物记skipped而不是0分(project, tmp_path):
    """旁路/没交不是失败——同流水线那边的既有纪律,绝不记 0 分。"""
    import json
    trail.record_commit(project, 3, "本章设定锚点", "只交了这一件。", "v2:a")
    got = collect_steps(project, 3, tmp_path, agentic=True)
    assert got["设定师"] == "只交了这一件。"
    assert got["大纲师"] is None
    status = json.loads((tmp_path / "steps.json").read_text(encoding="utf-8"))
    assert status["大纲师"] == "skipped"


def test_agent模式同一产物交多次取最后一次(project, tmp_path):
    """agent 会回头重来。归因该看它最终交出去的那份,不是中途那版。"""
    trail.record_commit(project, 3, "本章初稿", "第一版。", "v2:a")
    trail.record_commit(project, 3, "本章初稿", "回头重写的第二版。", "v2:b")
    got = collect_steps(project, 3, tmp_path, agentic=True)
    assert got["写手"] == "回头重写的第二版。"


def test_流水线模式仍走账本_不受影响(project, tmp_path):
    """老路是默认路径,一个字都不能改坏。"""
    from loom import ledger
    ledger.record_step(project, 3, "写手", "账本里的初稿。", "sig")
    got = collect_steps(project, 3, tmp_path)          # 不传 agentic
    assert got["写手"] == "账本里的初稿。"


def test_两条路互不串台(project, tmp_path):
    """同一章先跑过流水线、又跑过 agent 模式时,两边都有数据。
    按显式的 agentic 参数取,不靠「哪边非空」猜——猜会在这种场景下悄悄取错。"""
    from loom import ledger
    ledger.record_step(project, 3, "写手", "账本里的旧初稿。", "sig")
    trail.record_commit(project, 3, "本章初稿", "轨迹里的新初稿。", "v2:a")
    assert collect_steps(project, 3, tmp_path)["写手"] == "账本里的旧初稿。"
    assert collect_steps(project, 3, tmp_path, agentic=True)["写手"] == "轨迹里的新初稿。"
