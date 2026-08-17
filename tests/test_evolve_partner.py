"""领航员这一侧:证据攒够时它知道、作者点头时它能落。

spec 2026-08-16 §5.4:证据攒够由领航员在对话里主动提,作者点了才落。
**复用已经真机验证过的候选卡形态**,不新建 UI 概念——同「提设定」一条路。
"""
from __future__ import annotations

from loom import evolve, partner_context, partner_tools, paths, persona, trail


def _ripe(project) -> None:
    for n in (1, 2, 3):
        trail.record_commit(project, n, "本章场景骨头(分镜细纲)", f"一。二。三。四。(第{n}章)", f"v2:s{n}")
        p = paths.outline_path(project, n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"一。二。三。(第{n}章 作者删成三场)", encoding="utf-8")


def test_证据没攒够时环境快照里不提这件事(project):
    """别让领航员对着一章的偶然差异就开口——那是噪声,不是习惯。"""
    assert "改法" not in partner_context.env_snapshot(project)


def test_证据攒够了环境快照告诉领航员(project):
    """领航员不会凭空知道该问什么。攒够证据这件事得进它的只读投影,它才开得了口。"""
    _ripe(project)
    snap = partner_context.env_snapshot(project)
    assert "大纲师" in snap and "3 章" in snap


def test_学改法工具产候选卡不落盘(project):
    """作者在对话里说「好啊」→ 领航员调这个工具 → 出候选卡。**仍然不落盘**,
    等作者在卡上拍板(同「提设定」的红线:没点的一个字不进书)。"""
    from conftest import FakeBackend, const
    _ripe(project)
    before = (project / "agents/大纲师.md").read_text(encoding="utf-8")
    ev = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t",
                                backend=FakeBackend(const("- 默认拆三场。")))
    assert ev["t"] == "proposal" and ev["kind"] == "人格增补"
    assert "拆三场" in ev["内容"] and ev["id"]
    assert (project / "agents/大纲师.md").read_text(encoding="utf-8") == before


def test_学改法在证据不够时给一句人话而不是空卡(project):
    from conftest import FakeBackend, const
    ev = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t",
                                backend=FakeBackend(const("x")))
    assert ev.get("error") and "证据" in ev["error"]


def test_没有后端时不假装能学(project):
    """伙伴通道的既有调用点不传 backend(读类工具用不着)。这条工具要发 LLM,
    拿不到后端就老实说,别静默返回空卡。"""
    _ripe(project)
    ev = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t")
    assert ev.get("error")


def test_工具契约段里有它(project):
    assert "学改法" in partner_tools.render_contract()


def test_拍板后落增补且可撤销(project):
    """整条链的收口:提议 → 拍板 → 落增补 → 撤销。"""
    from conftest import FakeBackend, const
    _ripe(project)
    ev = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t",
                                backend=FakeBackend(const("- 默认拆三场。")))
    base_before = persona.split(project, "大纲师")[0]
    evolve.confirm(project, ev["角色"], ev["内容"])
    assert "拆三场" in persona.split(project, "大纲师")[1]
    assert persona.split(project, "大纲师")[0] == base_before
    evolve.revert(project, "大纲师")
    assert persona.split(project, "大纲师")[1] == ""
