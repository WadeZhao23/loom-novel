"""产物级续跑:重跑时把【已提交且上游未变】的产物原样放回,不重算、不重付费。

spec 2026-08-16 §4「续跑账本」那一行 + §6 P2。流水线是「每棒 sha + 上游签名」,
agent 化后没有棒,改成按【提交序】重放轨迹,撞到第一个签名失配即停。
"""
from __future__ import annotations

import dataclasses

from loom import write_tools, writeloop
from loom.config import load_config

_稿 = "他没说话。火把的光爬上矿壁，血顺着指缝往下滴。" * 6


def _submit(产物: str, 内容: str) -> str:
    return f"用:提交\n产物:{产物}\n\n{内容}"


def _sess(project, backend=None, *, outline=True, **over):
    if outline:
        _seed_outline(project)
    cfg = dataclasses.replace(load_config(project), **over)
    return write_tools.Session(root=project, chapter_n=1, config=cfg, backend=backend)


def _first_run(project, replies):
    from conftest import ScriptedBackend
    be = ScriptedBackend(list(replies))
    sess = _sess(project, be, gate_rounds=0)
    writeloop.run_chapter(sess)
    return be


def test_全部产物已提交时重跑零调用(project):
    from conftest import ScriptedBackend
    _first_run(project, [
        _submit("本章设定锚点", "灵气复苏第三年，主角觉醒逆息体质。"),
        _submit("本章终稿", _稿),
    ])
    be2 = ScriptedBackend([])          # 一条回复都不给:只要它调模型就会拿到空串并炸
    sess2 = _sess(project, be2, gate_rounds=0)
    assert writeloop.run_chapter(sess2) == _稿
    assert be2.calls == [], "上游没变,一次模型调用都不该发"


def test_重放把已提交产物放回工作区(project):
    from conftest import ScriptedBackend
    _first_run(project, [
        _submit("本章设定锚点", "灵气复苏第三年，主角觉醒逆息体质。"),
        _submit("本章终稿", _稿),
    ])
    be2 = ScriptedBackend([])
    sess2 = _sess(project, be2, gate_rounds=0)
    writeloop.run_chapter(sess2)
    assert [label for label, _ in sess2.workspace] == ["本章设定锚点", "本章终稿"]


def test_重放发agent_skip让作者知道跳过了什么(project):
    from conftest import ScriptedBackend
    _first_run(project, [
        _submit("本章设定锚点", "灵气复苏第三年，主角觉醒逆息体质。"),
        _submit("本章终稿", _稿),
    ])
    be2 = ScriptedBackend([])
    seen: list = []
    sess2 = _sess(project, be2, gate_rounds=0)
    sess2.progress = seen.append
    writeloop.run_chapter(sess2)
    skipped = [e["role"] for e in seen if e.get("type") == "agent_skip"]
    assert skipped == ["设定师", "润色师"]


def test_改了人格提示词就从那件产物起重跑(project):
    """上游变了必须重算——这是续跑的正确性底线。作者改了写手的写法要求,
    却还沿用旧初稿,等于他的改动被静默吃掉(v1 签名踩过这个坑)。"""
    from conftest import ScriptedBackend
    _first_run(project, [
        _submit("本章设定锚点", "灵气复苏第三年，主角觉醒逆息体质。"),
        _submit("本章终稿", _稿),
    ])
    p = project / "agents/润色师.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n补一条:多用短句。\n", encoding="utf-8")
    新稿 = _稿 + "他把刀收回鞘里。"
    be2 = ScriptedBackend([_submit("本章终稿", 新稿)])
    sess2 = _sess(project, be2, gate_rounds=0)
    assert writeloop.run_chapter(sess2) == 新稿
    assert len(be2.calls) == 1, "只有终稿该重算"
    # 关键区分:锚点【被重放了】(上游没变),不是这一轮重新产的——没续跑的话工作区里只有终稿
    assert [l for l, _ in sess2.workspace] == ["本章设定锚点", "本章终稿"]


def test_重放不再跑质量关卡(project):
    """轨迹里存的是【过完关卡之后】的文本。重放还跑一遍 = 为同一份稿重复付复审的钱。"""
    from conftest import ScriptedBackend

    class Rec:
        def __init__(self, replies): self.replies = list(replies); self.systems = []
        def complete(self, system, user, *, max_chars=None, on_chunk=None, **kw):
            self.systems.append(system)
            return self.replies.pop(0) if self.replies else ""

    _seed_outline(project)
    be = Rec([_submit("本章终稿", _稿), "通过"])
    sess = write_tools.Session(root=project, chapter_n=1, config=load_config(project), backend=be)
    assert sess.config.gate_rounds == 1
    writeloop.run_chapter(sess)
    assert any("独立审读" in s for s in be.systems), "首跑该跑去AI味关卡"

    be2 = Rec([])
    sess2 = write_tools.Session(root=project, chapter_n=1, config=load_config(project), backend=be2)
    writeloop.run_chapter(sess2)
    assert be2.systems == [], "重放不该再发任何调用(含复审)"


def _seed_outline(project, n: int = 1) -> None:
    """铺一份细纲。正文稿的提交前置条件(篇幅结构闸)要求它在先——除非这条测试测的正是那个条件。"""
    from loom import paths
    p = paths.outline_path(project, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("一(约600字):验伤。二(约600字):遇敌。", encoding="utf-8")
