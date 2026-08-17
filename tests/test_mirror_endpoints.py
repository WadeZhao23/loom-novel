"""镜台的两个出口:HTTP 端点 + CLI 摘要。"""
from __future__ import annotations

from conftest import require_http_transport


def _client():
    from fastapi.testclient import TestClient
    from loom.server import app
    # base_url 必须给 127.0.0.1:app 挂了 TrustedHostMiddleware(挡 DNS rebinding),
    # TestClient 默认的 host 是 testserver,过不了这道闸——全仓其余端点测试都这么写。
    return TestClient(app, base_url="http://127.0.0.1")


def test_端点返回四块(project):
    require_http_transport()
    r = _client().get("/api/mirror", params={"root": str(project)})
    assert r.status_code == 200
    assert set(r.json()) == {"曲线", "指纹", "人格", "覆盖"}


def test_不存在的路径回空投影而不是报错():
    """镜台每一块都自己兜底(缺文件=跳过),所以坏路径的结果是**确定的**:
    200 + 四块全空。断言 `in (200, 400)` 等于什么都没钉住。"""
    require_http_transport()
    r = _client().get("/api/mirror", params={"root": "/不存在的路径/xxx"})
    assert r.status_code == 200
    got = r.json()
    assert got["曲线"] == [] and got["人格"] == []
    assert got["覆盖"] == {"已学": 0, "有稿": 0, "总章": 0}
    assert got["指纹"]["规则数"] == 0


def test_status命令打出镜台摘要(project, monkeypatch):
    """`find_project_root` 是从 cwd 往上找的,所以要 chdir 进项目里跑——
    传 env 没用(没有那个环境变量),那样只能钉住「没崩」,等于没测。"""
    from typer.testing import CliRunner
    from loom import paths
    from loom.cli import app
    from loom.state import mark_learned
    paths.snapshot_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.chapter_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.snapshot_path(project, 1).write_text("# 标题\n一。二。三。四。", encoding="utf-8")
    paths.chapter_path(project, 1).write_text("# 标题\n壹。二。三。四。", encoding="utf-8")
    mark_learned(project, 1)
    monkeypatch.chdir(project)
    res = CliRunner().invoke(app, ["status"], catch_exceptions=False)
    assert res.exit_code == 0
    assert "镜台" in res.stdout and "改写" in res.stdout


def test_摘要在没数据时不打印(project):
    from loom import mirror
    assert mirror.summary_line(project) == ""
