"""用户级默认后端的 HTTP 端点(走 TestClient,防「函数对但端点 500」的漏网,如 provider_catalog 未导入)。"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
from starlette.testclient import TestClient  # noqa: E402

from loom import server  # noqa: E402


def _client():
    return TestClient(server.app, base_url="http://127.0.0.1")


def test_get_default_backend_ok_when_unset():
    r = _client().get("/api/backend/default")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["has_default"] is False
    assert d["provider"] == "deepseek"
    assert isinstance(d["providers"], list) and len(d["providers"]) >= 9
    assert "keys_set" in d


def test_put_then_get_roundtrip():
    c = _client()
    r = c.put("/api/backend/default", json={"provider": "zhipu", "model": "glm-x", "api_key": "zp-1"})
    assert r.status_code == 200, r.text
    d = c.get("/api/backend/default").json()
    assert d["has_default"] and d["provider"] == "zhipu" and d["model"] == "glm-x"
    assert d["keys_set"]["zhipu"] is True


def test_put_custom_requires_base_url():
    r = _client().put("/api/backend/default", json={"provider": "openai_compat", "model": "x", "api_key": "k"})
    assert r.status_code == 400   # 自定义要先填 base_url


# ---- 项目书架(用户级注册表):新建/导入/样例自动入架,欢迎页点选 ----

def test_shelf_records_on_create_and_open(tmp_path):
    c = _client()
    r = c.post("/api/project/create", json={"name": "书架测试甲", "parent": str(tmp_path)})
    assert r.status_code == 200, r.text
    root = r.json()["root"]
    shelf = c.get("/api/projects").json()["projects"]
    assert shelf and shelf[0]["root"] == root and shelf[0]["exists"] is True
    assert shelf[0]["title"] == "书架测试甲" and shelf[0]["chapters"] == 0
    # 再开另一本 → 提到最前;重开第一本 → 又回到最前(最近优先)
    c.post("/api/project/create", json={"name": "书架测试乙", "parent": str(tmp_path)})
    assert c.get("/api/projects").json()["projects"][0]["title"] == "书架测试乙"
    c.post("/api/project/open", json={"root": root})
    assert c.get("/api/projects").json()["projects"][0]["root"] == root


def test_shelf_forget_and_missing_dir(tmp_path):
    import shutil
    c = _client()
    root = c.post("/api/project/create", json={"name": "要消失的书", "parent": str(tmp_path)}).json()["root"]
    shutil.rmtree(root)                                     # 用户手动删了文件夹
    row = next(p for p in c.get("/api/projects").json()["projects"] if p["root"] == root)
    assert row["exists"] is False                            # 书架如实标灰,不炸
    c.post("/api/projects/forget", json={"root": root})
    assert all(p["root"] != root for p in c.get("/api/projects").json()["projects"])
