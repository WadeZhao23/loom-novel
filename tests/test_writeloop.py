"""写作 agent 循环:一个 agent、五个人格、循环到终稿提交。

spec 2026-08-16 §3.2。形状照搬 `partner.run_turn`(已在 claude/codex/DeepSeek 三类后端上
跑通):每轮一次 `complete()`,模型按文本协议输出「用:」块,Loom 侧执行、回喂、再 complete。
真实读写永远在 Loom 服务端,模型自己没有 shell/文件能力。
"""
from __future__ import annotations

import dataclasses

import pytest

from loom import write_tools, writeloop
from loom.backends import LoomBackendError
from loom.config import load_config
from loom.parse import parse_tool_blocks

_稿 = "他没说话。火把的光爬上矿壁,血顺着指缝往下滴。" * 6


def _sess(project, backend=None, *, outline=True, **cfg_over):
    if outline:
        _seed_outline(project)
    cfg = dataclasses.replace(load_config(project), **cfg_over)
    return write_tools.Session(root=project, chapter_n=1, config=cfg, backend=backend)


def _submit(产物: str, 内容: str) -> str:
    return f"用:提交\n产物:{产物}\n\n{内容}"


# ── 协议层:提交整章正文,「内容」是多行散文,塞不进一行「键:值」 ──────────────

def test_工具块带多行正文体():
    """`_TOOL_KV_RE` 是逐行 `键:值`,整章正文进不去。解析器给每个块补一个 body:
    参数行之后、到下一个「用:」或结尾为止的原文。"""
    raw = "好的,我来写。\n用:提交\n产物:本章终稿\n\n他没说话。\n火把的光爬上矿壁。"
    say, tools = parse_tool_blocks(raw, valid_names={"提交"})
    assert say == "好的,我来写。"
    assert tools[0]["body"] == "他没说话。\n火把的光爬上矿壁。"


def test_多个工具块各自的正文体不互相吞():
    raw = "用:提交\n产物:本章设定锚点\n\n锚点甲。\n用:提交\n产物:本章初稿\n\n初稿乙。"
    _, tools = parse_tool_blocks(raw, valid_names={"提交"})
    assert tools[0]["body"] == "锚点甲。"
    assert tools[1]["body"] == "初稿乙。"


def test_无正文体的工具块body为空():
    """只读工具没有正文体——别让它凭空多出一个 body 字段的假值。"""
    _, tools = parse_tool_blocks("用:查硬设定", valid_names={"查硬设定"})
    assert tools[0]["body"] == ""


# ── 循环 ────────────────────────────────────────────────────────────────

def test_循环跑到终稿提交即收工(project):
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        "先看看这本书的硬设定。\n用:查硬设定",
        "写好了。\n" + _submit("本章终稿", _稿),
    ])
    sess = _sess(project, be, gate_rounds=0)
    assert writeloop.run_chapter(sess) == _稿
    assert len(be.calls) == 2, "拿到终稿就该停,不该再多问一轮"


def test_协议行绝不漏到作者屏幕(project):
    """spec §5.2 critical(伙伴通道那条纪律原样适用):流式转发时,「用:」开头的协议行
    及其参数行一律不许出现在作者看到的字里。"""
    from conftest import ScriptedBackend
    be = ScriptedBackend(["马上写。\n" + _submit("本章终稿", _稿)], stream=True)
    seen: list[str] = []
    sess = _sess(project, be, gate_rounds=0)
    sess.progress = lambda e: seen.append(e.get("delta", "")) if e.get("type") == "agent_chunk" else None
    writeloop.run_chapter(sess)
    shown = "".join(seen)
    assert "马上写" in shown
    assert "用:" not in shown and "产物:" not in shown


def test_提交被打回后把原因回喂给模型(project):
    """§4 第一行的另一半:非空闸不再中断整章,而是把原因回喂——模型要真的看得到它。"""
    from conftest import ScriptedBackend
    be = ScriptedBackend([
        _submit("本章终稿", ""),          # 空稿,必被打回
        _submit("本章终稿", _稿),          # 改好重交
    ])
    sess = _sess(project, be, gate_rounds=0)
    assert writeloop.run_chapter(sess) == _稿
    assert "返回空" in be.calls[1][1], "第二轮的 prompt 里要带上被打回的原因"


def test_顺跑一章的调用账_与五个头像都点亮(project):
    """§9 第一风险是成本:今天流水线一章 = 5 次调用 + gate,自主循环不能悄悄翻倍。

    这条钉两件事:
    ① **循环不额外烧轮次**——工具执行/回喂不各自多花一次 complete,顺跑一章的调用数
      恰好等于模型的回复数(12),拿到终稿立刻停。哪天有人改动让它多转一圈,这里先红。
    ② **五个头像照旧一个个点亮**(§3.2 承诺:角色降级为人格是内部重构,对外还是那五个人)。
    """
    from conftest import ScriptedBackend
    replies = [
        "先看看这本书的设定该怎么立。\n用:取人格\n角色:设定师",
        "用:查硬设定",
        _submit("本章设定锚点", "灵气复苏第三年,主角觉醒逆息体质,濒死才能爆发。"),
        "用:取人格\n角色:大纲师",
        _submit("本章场景骨头(分镜细纲)", "一(约400字):验伤。二(约400字):遇敌。三(约400字):爆发。"),
        "用:取人格\n角色:写手",
        _submit("本章初稿", _稿),
        "用:取人格\n角色:编辑",
        _submit("本章改稿", _稿),
        _submit("本章改动留痕", "删了两处套话,情绪点名改成动作。"),
        "用:取人格\n角色:润色师",
        _submit("本章终稿", _稿),
    ]
    be = ScriptedBackend(list(replies))
    lit: list[str] = []
    sess = _sess(project, be, gate_rounds=0)
    sess.progress = lambda e: lit.append(e["role"]) if e.get("type") == "agent_start" else None
    assert writeloop.run_chapter(sess) == _稿
    assert len(be.calls) == len(replies), "工具执行不该各自多烧一次 complete"
    assert lit == ["设定师", "大纲师", "写手", "编辑", "润色师"]


def test_只读工具的结果完整回喂_不许截断(project):
    """真机实测 2026-08-16:回喂时把工具结果截到 400 字,agent **连取了 4 次「设定师」人格**
    ——它根本没看见人格内容,只好一遍遍再要。取数工具的结果被截断 = 这个工具等于不存在。
    """
    from conftest import ScriptedBackend
    from loom.agents import load_agent
    be = ScriptedBackend(["先取人格。\n用:取人格\n角色:写手", _submit("本章终稿", _稿)])
    sess = _sess(project, be, gate_rounds=0)
    writeloop.run_chapter(sess)
    next_prompt = be.calls[1][1]
    tail = load_agent(project, "写手").system_prompt.strip()[-40:]
    assert tail in next_prompt, "人格的尾巴也得在回喂里——截断就等于没给"


def test_撞轮数上界报错而不是无限跑(project):
    """§9 第一风险:自主循环的成本上界必须定死。跑满仍没有终稿 = 这次失败,
    明确报错让作者看见,绝不静默交一章空的。"""
    from conftest import ScriptedBackend
    be = ScriptedBackend(["再想想。"] * 40)
    sess = _sess(project, be, gate_rounds=0)
    with pytest.raises(LoomBackendError):
        writeloop.run_chapter(sess, max_rounds=3)
    assert len(be.calls) <= 3


def _seed_outline(project, n: int = 1) -> None:
    """铺一份细纲。正文稿的提交前置条件(篇幅结构闸)要求它在先——除非这条测试测的正是那个条件。"""
    from loom import paths
    p = paths.outline_path(project, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("一(约600字):验伤。二(约600字):遇敌。", encoding="utf-8")
