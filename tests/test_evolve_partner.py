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
    """内部契约(handler 层面):`_handle_xuegaifa` 要发一次 LLM 调用,拿不到 backend 就该
    老实报错,不能静默返回空卡。这里直接调 `run_tool` 且不传 `backend`,钉的是 handler
    自身的防御——不是在断言「伙伴通道不传 backend」这件事本身(那是终审①的 bug,
    产品路径上 backend 确实该被传下去,见下面 `test_产品路径上backend被传给学改法`)。"""
    _ripe(project)
    ev = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t")
    assert ev.get("error")


def test_产品路径上backend被传给学改法(project):
    """终审①critical:`partner.run_turn` 调 `partner_tools.run_tool` 时若不传 `backend`,
    「学改法」handler 必抛 ValueError——领航员每次调它都失败,白烧一轮 tool_rounds,
    还给作者屏幕上留一条错误。这里走真正的产品入口 `partner.run_turn`(不是直接调
    `partner_tools.run_tool`),证明 backend 确实被传下去、工具能跑通到候选卡,
    且提议阶段 `agents/<角色>.md` 一个字没动。"""
    from conftest import ScriptedBackend
    from loom.partner import run_turn
    _ripe(project)
    before = (project / "agents/大纲师.md").read_text(encoding="utf-8")
    be = ScriptedBackend([
        "好,我来学一下大纲师的改法。\n用:学改法\n角色:大纲师",
        "- 默认拆三场。",   # 「学改法」handler 内部再调一次 backend.complete 蒸增补
    ])
    evs = []
    run_turn(project, "帮我学一下大纲师的改法", be, emit=evs.append, ts="t")
    assert not any(e["t"] == "result" and e.get("error") for e in evs)   # 没有因缺 backend 报错
    proposals = [e for e in evs if e["t"] == "proposal"]
    assert proposals and proposals[0]["kind"] == "人格增补"
    assert "拆三场" in proposals[0]["内容"]
    assert (project / "agents/大纲师.md").read_text(encoding="utf-8") == before   # 提议阶段一个字没动


def test_端到端_学改法候选卡经partner_confirm落盘且基座不变(project):
    """终审①收口:产品路径全链路——`partner.run_turn` 产候选卡 → `usecases.partner_confirm`
    拍板 → 落增补区、基座不变。用假后端,不真打网络。"""
    from conftest import ScriptedBackend
    from loom import usecases
    from loom.partner import run_turn
    _ripe(project)
    base_before = persona.split(project, "大纲师")[0]
    be = ScriptedBackend([
        "好,我来学一下大纲师的改法。\n用:学改法\n角色:大纲师",
        "- 默认拆三场。",
    ])
    evs = []
    run_turn(project, "帮我学一下大纲师的改法", be, emit=evs.append, ts="t")
    proposal = next(e for e in evs if e["t"] == "proposal")
    result = usecases.partner_confirm(project, proposal["id"], ts="t2")
    assert not result.get("error")
    assert "拆三场" in persona.split(project, "大纲师")[1]   # 增补区落了
    assert persona.split(project, "大纲师")[0] == base_before   # 基座一个字没变


def test_工具契约段里有它(project):
    assert "学改法" in partner_tools.render_contract()


def test_学改法候选卡带slot与content供webui渲染(project, monkeypatch):
    """终审③critical:webui 的 `pcProposal` 统一读 `slot`/`content` 渲染候选卡
    (`humanizeSlot(ev.slot)` 填落点行、`content.textContent = ev.content || ""` 填正文、
    「改一改」按钮填 `ev.content`)——「学改法」出的候选卡此前只有 kind/角色/内容/证据章数,
    没有 slot/content,candidate 卡会渲染成空白正文(作者盲签)。且 `slotTakenBySibling` 用
    `prop.slot === ev.slot` 判「这一格是否已被同伴占了」——两张卡的 slot 都是 undefined 时,
    `undefined === undefined` 恒真,第二张会被误灰成「这一格已选了其他方向」。

    这里直接 monkeypatch `evolve.ripe`/`evolve.propose`/`evolve.learnable_personas`,模拟两个
    不同人格各自出一张候选卡,断言两者的 slot 都指向各自的 `agents/<角色>.md` 且互不相等。

    **今天这是个将来态**:`evolve._COMPARABLE` 结构性只有大纲师一项(判据只能是「作者实际
    改成了什么」,那个人格就必须有一件盘上可比对的产物),所以真实运行时同屏只可能有一张卡,
    误灰不会发生。但 `_COMPARABLE` 加第二行的那天它就会发生——那一行不该同时是这道
    渲染闸的第一次真实曝光。故意用 monkeypatch 把将来态提前钉住。
    """
    from conftest import FakeBackend, const

    from loom import evolve

    def fake_propose(root, persona_name, backend, **kw):
        return {"t": "proposal", "kind": "人格增补", "角色": persona_name,
                "内容": f"- {persona_name}的改法。", "证据章数": 3}

    monkeypatch.setattr(evolve, "ripe", lambda root, persona, **kw: True)
    monkeypatch.setattr(evolve, "propose", fake_propose)
    # 连它一起模拟:真实的 learnable_personas() 今天只回 {"大纲师"},第二张卡根本出不来
    monkeypatch.setattr(evolve, "learnable_personas", lambda: {"大纲师", "写手"})

    ev1 = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t1",
                                 backend=FakeBackend(const("x")))
    ev2 = partner_tools.run_tool(project, "学改法", {"角色": "写手"}, ts="t2",
                                 backend=FakeBackend(const("x")))

    assert ev1["slot"] == "agents/大纲师.md"
    assert ev1["content"] == ev1["内容"]        # content 别名与 内容 同值
    assert ev2["slot"] == "agents/写手.md"
    assert ev1["slot"] != ev2["slot"]           # 防误灰:两张卡不再共享 undefined slot
    # 角色/内容 两个键仍保留——partner_confirm 的「人格增补」分支在用
    assert ev1["角色"] == "大纲师" and ev1["内容"]


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


def _http_client():
    from fastapi.testclient import TestClient

    from loom.server import app
    # base_url 必须给 127.0.0.1:app 挂了 TrustedHostMiddleware,TestClient 默认的 host 是
    # testserver,过不了这道闸——全仓其余端点测试都这么写(见 test_mirror_endpoints.py)。
    return TestClient(app, base_url="http://127.0.0.1")


def test_学改法拍板后可经接口一键撤销(project):
    """终审④important:`usecases.partner_confirm` 的「人格增补」分支 docstring 说
    `evolve.confirm`「自带『历史/』快照供一键撤销」,但 `evolve.revert` 此前全仓没有任何
    生产调用点(cli.py 没有、server.py 51 个路由里没有)——作者落盘后只能手工去编辑
    agents/<角色>.md。这里接一条 POST /api/evolve/revert,验证它真的能把落盘的增补撤空、
    基座不动。"""
    from conftest import FakeBackend, const, require_http_transport
    require_http_transport()
    _ripe(project)
    ev = partner_tools.run_tool(project, "学改法", {"角色": "大纲师"}, ts="t",
                                backend=FakeBackend(const("- 默认拆三场。")))
    base_before = persona.split(project, "大纲师")[0]
    evolve.confirm(project, ev["角色"], ev["内容"])
    assert "拆三场" in persona.split(project, "大纲师")[1]

    r = _http_client().post("/api/evolve/revert", json={"root": str(project), "角色": "大纲师"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert persona.split(project, "大纲师")[1] == ""            # 增补区撤空
    assert persona.split(project, "大纲师")[0] == base_before   # 基座一个字没动


def test_没有可撤销快照时接口回可读提示而不是崩掉(project):
    """撤不了(没落过 / 已撤过)是正常业务态,不是系统错误——回可读的 400,不是 500。"""
    from conftest import require_http_transport
    require_http_transport()
    r = _http_client().post("/api/evolve/revert", json={"root": str(project), "角色": "大纲师"})
    assert r.status_code == 400
    assert "撤销" in r.json()["error"]
