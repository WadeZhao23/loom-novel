"""agent 模式接线:`run_pipeline` 走写作 agent 循环,收尾动作与老流水线一字不差。

spec 2026-08-16 §3.2/§6(P1)。**灰度上线**:默认仍走老流水线——新路子在真机跑通一章之前
不该顶掉 880 条既有测试钉着的那条路(spec §6 的 P1 验收明写要「真机跑通一章」)。
"""
from __future__ import annotations

import dataclasses

from loom import agents, paths
from loom.config import Config, load_config, save_config

_稿 = "他没说话。火把的光爬上矿壁,血顺着指缝往下滴。" * 6


def _submit(产物: str, 内容: str) -> str:
    return f"用:提交\n产物:{产物}\n\n{内容}"


def test_默认不开agent模式(project):
    """灰度纪律:开关默认关。880 条既有测试钉的是老流水线那条路,不能被悄悄换掉。"""
    assert Config().agentic is False
    assert load_config(project).agentic is False


def test_agent模式开关能存进loom_toml再读回来(project):
    cfg = dataclasses.replace(load_config(project), agentic=True)
    save_config(project, cfg)
    assert load_config(project).agentic is True


def test_agent模式跑完一章_收尾动作与老流水线一致(project):
    """起标题 → 正文首行 H1 → 落盘 → .原稿 快照 → 入账本快照。
    这四件是 learn / drifted 判定的地基,agent 化后一件都不能少。"""
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        "先取设定师。\n用:取人格\n角色:设定师",
        _submit("本章设定锚点", "灵气复苏第三年,主角觉醒逆息体质,濒死才能爆发。"),
        _submit("本章场景骨头(分镜细纲)", "一(约400字):验伤。二(约400字):遇敌。"),
        _submit("本章终稿", _稿),
        "废矿里的火光",          # 自动起标题(附赠动作,与老流水线同一个调用点)
    ])
    cfg = dataclasses.replace(load_config(project), agentic=True, gate_rounds=0,
                              continuity_scan=False)
    path, final = agents.run_pipeline(project, 1, be, cfg)
    assert path.is_file()
    assert final.startswith("# 废矿里的火光"), "标题必须进正文首行 H1(ADR 0009)"
    assert paths.snapshot_path(project, 1).is_file(), ".原稿 快照是 learn 的 diff 源,不能少"
    assert _稿[:12] in path.read_text(encoding="utf-8")


def test_agent模式在默认gate轮数下跑通(project):
    """上面几条都把 gate 关了,但作者拿到手的默认是 `轮数=1`——这条路没跑过就是没跑过。

    默认轮数下:提交改稿触发质检、提交终稿触发去AI味,两道各发一次复审(只诊断不回炉),
    复审调用【不占循环轮次】,整章照常出稿。
    """
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        _submit("本章场景骨头(分镜细纲)", "一(约600字):验伤。二(约600字):遇敌。"),
        _submit("本章改稿", _稿),
        "通过",                    # 质检复审(挂在提交改稿上)
        _submit("本章终稿", _稿),
        "通过",                    # 去AI味复审(挂在提交终稿上)
        "废矿里的火光",             # 起标题
    ])
    cfg = dataclasses.replace(load_config(project), agentic=True, continuity_scan=False)
    assert cfg.gate_rounds == 1, "这条测试的意义就是跑默认值"
    path, final = agents.run_pipeline(project, 1, be, cfg)
    assert path.is_file() and final.startswith("# 废矿里的火光")


def test_agent模式也发chapter_done事件(project):
    """前端靠它收尾渲染。agent 化只换了中间怎么跑,对外的完成信号一模一样。"""
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        _submit("本章场景骨头(分镜细纲)", "一(约600字):验伤。二(约600字):遇敌。"),
        _submit("本章终稿", _稿), "废矿里的火光"])
    cfg = dataclasses.replace(load_config(project), agentic=True, gate_rounds=0,
                              continuity_scan=False)
    seen: list = []
    agents.run_pipeline(project, 1, be, cfg, seen.append)
    types = [e.get("type") for e in seen]
    assert "pipeline_start" in types and "chapter_done" in types
