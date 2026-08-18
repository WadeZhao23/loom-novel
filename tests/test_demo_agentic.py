"""demo 后端要认写章 agent 协议——否则零 key 冒烟路径在 agent 模式下整条死掉。

evals 的 `generate --backend demo`、录屏、免 key 试玩全靠 DemoBackend。它按 system 里的
关键词分流(见 backends.DemoBackend._pick),而 writeloop 的系统提示词是全新的一段,
既有分支一条都不命中 → 返回「（demo 占位）」→ 解析不出工具块 → 循环空转到撞轮数上界。
"""
from __future__ import annotations

import dataclasses

from loom import backends, write_tools, writeloop
from loom.config import load_config
from loom.parse import parse_tool_blocks


def _demo_reply(project, trail_lines=None):
    cfg = dataclasses.replace(load_config(project), agentic=True)
    sess = write_tools.Session(root=project, chapter_n=1, config=cfg)
    system, user = writeloop._assemble(sess, trail_lines or [])
    return backends.DemoBackend(cfg).complete(system, user)


def test_demo认得写章协议并吐出可解析的工具块(project):
    raw = _demo_reply(project)
    _, tools = parse_tool_blocks(raw, valid_names=set(write_tools.REGISTRY))
    assert tools, f"demo 没吐出工具块,原样返回:{raw[:60]!r}"


def test_demo在agent模式下能把一章跑到终稿(project):
    """整条链的冒烟:免 key 也要能从头跑到「提交本章终稿」,不然录屏/试玩/evals 全断。"""
    import dataclasses as dc
    from loom import paths
    cfg = dc.replace(load_config(project), agentic=True, gate_rounds=0)
    # 细纲前置:正文稿要求它在先(篇幅结构闸)
    p = paths.outline_path(project, 1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("一(约400字):验伤。二(约400字):遇敌。", encoding="utf-8")
    sess = write_tools.Session(root=project, chapter_n=1, config=cfg,
                               backend=backends.DemoBackend(cfg))
    final = writeloop.run_chapter(sess)
    assert final.strip(), "demo 模式下没能跑出终稿"
    assert "(demo" in final or "demo" in final.lower() or len(final) > 40


def test_demo产出自报demo不冒充真实生成(project):
    """既有纪律(见 DemoBackend docstring):内容是占位,不代表真实生成质量,不许冒充。"""
    raw = _demo_reply(project)
    assert "demo" in raw.lower()
