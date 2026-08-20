"""流水线(默认路径)也要写细纲轨迹——否则自进化对绝大多数用户是惰性的。

实测发现:agent 模式默认关,而轨迹此前只由 `write_tools._handle_commit`(agent 专属)
和 `regen_outline` 写。默认路径跑完一章,轨迹为空 → `evolve.collect` 无证据 →
「学改法」永远不 ripe。P3 整块的价值绑死在一个默认关掉的开关上。

判据的方向必须钉死:轨迹记的是【AI 交出去的那份】,盘上那份是【作者手里的】,
两者不同才算「作者改过」。所以 WYSIWYG 旁路那支**绝不能**记——那份本来就是作者的,
记了等于拿作者自己的稿去和它自己比,永远比不出差异(更糟:若他之后再改,
差异会被算成「相对 AI 稿的改动」,而那根本不是 AI 写的)。
"""
from __future__ import annotations

import dataclasses

from loom import agents, evolve, paths, trail
from loom.config import load_config


def _稿(mark: str) -> str:
    """够长的正文体:要过 chapter_profile 的实字门槛(默认 800 字目标 → 96 实字)。"""
    return f"他没说话。火把的光爬上矿壁,血顺着指缝往下滴。({mark})" * 6


def _cfg(project, **over):
    return dataclasses.replace(load_config(project), gate_rounds=0,
                               continuity_scan=False, **over)


def test_流水线跑完一章细纲进轨迹(project):
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        "锚点:主角觉醒逆息体质。",
        "一(约400字):验伤。二(约400字):遇敌。",
        _稿("初稿"),
        _稿("改稿"),
        _稿("终稿"),
        "废矿里的火光",
    ])
    agents.run_pipeline(project, 1, be, _cfg(project))
    commits = trail.read_commits(project, 1)
    assert [c["产物"] for c in commits] == ["本章场景骨头(分镜细纲)"]
    assert "验伤" in commits[0]["text"]


def test_作者改了细纲就成为自进化的证据(project):
    """这条是整个目的:默认路径下,作者改细纲这件事要能被 evolve 看见。"""
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        "锚点:主角觉醒逆息体质。",
        "一(约400字):验伤。二(约400字):遇敌。三(约400字):爆发。",
        _稿("初稿"),
        _稿("改稿"),
        _稿("终稿"),
        "废矿里的火光",
    ])
    agents.run_pipeline(project, 1, be, _cfg(project))
    assert evolve.collect(project) == []          # 作者还没动,不该有证据
    p = paths.outline_path(project, 1)
    p.write_text("一(约600字):验伤。二(约600字):遇敌。", encoding="utf-8")   # 作者删成两场
    got = evolve.collect(project)
    assert len(got) == 1 and got[0].persona == "大纲师"
    assert "三(约400字)" in got[0].ai and "约600字" in got[0].author


def test_沿用作者已有细纲时绝不记进轨迹(project):
    """WYSIWYG 旁路:这份细纲本来就是作者的,不是 AI 交的。记了会把判据弄反——
    拿作者自己的稿当「AI 交的」,他后续的改动会被误算成「相对 AI 稿的改动」。"""
    from conftest import ScriptedBackend
    p = paths.outline_path(project, 1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("一(约600字):作者自己写的细纲。", encoding="utf-8")
    be = ScriptedBackend([
        "锚点:主角觉醒逆息体质。",
        _稿("初稿"),
        _稿("改稿"),
        _稿("终稿"),
        "废矿里的火光",
    ])
    agents.run_pipeline(project, 1, be, _cfg(project))
    assert trail.read_commits(project, 1) == []
    assert evolve.collect(project) == []


def test_轨迹写失败不拖累出稿(project, monkeypatch):
    """轨迹是省钱/学习的便利,绝不该让一章写不出来(同 trail.record_commit 自身的纪律)。"""
    from conftest import ScriptedBackend

    def boom(*a, **k):
        raise OSError("盘满了")

    monkeypatch.setattr(trail, "record_commit", boom)
    be = ScriptedBackend([
        "锚点:主角觉醒逆息体质。",
        "一(约400字):验伤。二(约400字):遇敌。",
        _稿("初稿"),
        _稿("改稿"),
        _稿("终稿"),
        "废矿里的火光",
    ])
    path, _final = agents.run_pipeline(project, 1, be, _cfg(project))
    assert path.is_file()
