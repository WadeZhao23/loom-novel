"""人格名是拼进 `agents/<角色>.md` 的路径片段——必须挡住穿越。

终审(2026-08-24 发版审计)实测:`POST /api/evolve/revert` 的「角色」是全仓接受路径片段的写端点里
唯一没过 `fsutil.safe_join` 的一个。`{"角色": "../../别处/我的日记"}` 能改写并回显书目录外的任意 .md。
不是 blocker(只监听 127.0.0.1 + CSRF/Host 双闸 + 零调用方,攻击者只能是本机同用户进程,权限增量为零),
但全仓其余写端点都守着,没有理由单留这一个口子。
"""
from __future__ import annotations

import pytest

from loom import evolve, persona


@pytest.mark.parametrize("bad", [
    "../../别处/我的日记", "/etc/passwd", "..", ".", "", "   ",
    "子目录/大纲师", "大纲师\x00.md", "..\\..\\windows",
])
def test_穿越型人格名一律拒绝(project, bad):
    with pytest.raises(ValueError):
        persona.check_name(bad)


def test_正常人格名照常放行(project):
    for ok in ("大纲师", "写手", "领航员"):     # 领航员不在 artifacts.ARTIFACTS 里,别被枚举式白名单误伤
        assert persona.check_name(ok) == ok
    assert persona.check_name("  大纲师  ") == "大纲师"   # 两头空白只是手滑,不是攻击


def test_split与write_extra都过这道闸(project):
    with pytest.raises(ValueError):
        persona.split(project, "../../别处/我的日记")
    with pytest.raises(ValueError):
        persona.write_extra(project, "../../别处/我的日记", "- 学到的。")


def test_revert的快照路径也过闸_别绕过_path(project):
    """`revert` 只碰 `.进化/历史/<角色>-增补前.md`,不碰 `agents/`——单靠 `_path` 那道闸兜不住它。"""
    with pytest.raises(ValueError):
        evolve.revert(project, "../../别处/我的日记")
    with pytest.raises(ValueError):
        evolve.confirm(project, "../../别处/我的日记", "- 学到的。")


def test_端点回可读400而不是500(project):
    from conftest import require_http_transport
    require_http_transport()
    from fastapi.testclient import TestClient

    from loom.server import app
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.post("/api/evolve/revert", json={"root": str(project), "角色": "../../别处/我的日记"})
    assert r.status_code == 400 and "error" in r.json()


def test_书目录外的文件一个字节都没被碰过(project, tmp_path):
    """这条才是真正的收口:证明挡住之后,越界目标文件原样未动。"""
    outsider = tmp_path / "我的日记.md"
    outsider.write_text("# 我的日记\n今天不想写小说。\n", encoding="utf-8")
    before = outsider.read_bytes()
    rel = "../" * 12 + str(outsider.with_suffix("")).lstrip("/")
    for call in (lambda: evolve.confirm(project, rel, "- 覆盖你。"),
                 lambda: evolve.revert(project, rel),
                 lambda: persona.write_extra(project, rel, "- 覆盖你。")):
        with pytest.raises(ValueError):
            call()
    assert outsider.read_bytes() == before
