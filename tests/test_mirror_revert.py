"""镜台的撤销:后端要告诉前端「这一条还撤不撤得回去」,别让按钮点了才说没有备份。

0.5.0 发版审计逮到的空头承诺:发行说明写「随时能一键撤销」,后端链完整、`POST /api/evolve/revert`
实打 200,但 webui/CLI 零调用方——作者在客户端里根本够不着它(而 brainedit.check_rel 只放行
世界观/人物,连手改 agents/*.md 都做不到)。0.5.1 把入口接上,这里钉住它依赖的后端契约。
"""
from __future__ import annotations

from loom import evolve, mirror, persona

_稿 = "- 场次里必须写清故事内时刻。"


def test_学到的写法带可撤销标记(project):
    """`evolve.confirm` 落盘时会留一份快照 → 这一条可撤销。"""
    evolve.confirm(project, "大纲师", _稿)
    row = next(r for r in mirror.persona_view(project) if r["角色"] == "大纲师")
    assert row["可撤销"] is True
    assert row["增补条数"] == 1


def test_作者手写的增补没有快照_按钮该灰着(project):
    """`persona.write_extra` 是直接写(手改/迁移),没经过 confirm → 没有快照可撤。
    灰着按钮,比点了才弹「没有可撤销的备份」诚实。"""
    persona.write_extra(project, "大纲师", _稿)
    row = next(r for r in mirror.persona_view(project) if r["角色"] == "大纲师")
    assert row["增补条数"] == 1 and row["可撤销"] is False


def test_撤销之后标记跟着落回去(project):
    """快照是一次性的(撤完即清),不是回退栈——撤过一次就该灰掉。"""
    evolve.confirm(project, "大纲师", _稿)
    assert evolve.has_snapshot(project, "大纲师") is True
    evolve.revert(project, "大纲师")
    assert evolve.has_snapshot(project, "大纲师") is False
    assert [r for r in mirror.persona_view(project) if r["角色"] == "大纲师"] == []   # 增补空了,整行不再列


def test_人格名不合法时只读投影不抛穿(project):
    """镜台是只读投影,`绝不抛` 是它的红线——谓词遇到坏名字要回 False,不是炸掉整屏。"""
    assert evolve.has_snapshot(project, "../../别处/我的日记") is False


def test_端点回的就是这个契约(project):
    from conftest import require_http_transport
    require_http_transport()
    from fastapi.testclient import TestClient

    from loom.server import app
    evolve.confirm(project, "大纲师", _稿)
    c = TestClient(app, base_url="http://127.0.0.1")
    row = next(r for r in c.get(f"/api/mirror?root={project}").json()["人格"] if r["角色"] == "大纲师")
    assert row["可撤销"] is True
    assert c.post("/api/evolve/revert", json={"root": str(project), "角色": "大纲师"}).json()["ok"] is True
    assert c.get(f"/api/mirror?root={project}").json()["人格"] == []


def test_撤销不碰基座(project):
    """整条链最要紧的那条红线,再钉一次。"""
    base_before = persona.split(project, "大纲师")[0]
    evolve.confirm(project, "大纲师", _稿)
    evolve.revert(project, "大纲师")
    assert persona.split(project, "大纲师")[0] == base_before
