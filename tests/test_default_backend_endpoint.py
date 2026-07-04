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
