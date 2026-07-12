"""错误 code 贯通(S7b):events.error 可选 code / server 流式与非流式端点透传目录键。"""
from __future__ import annotations

import json

import pytest

from loom import events
from loom.backends import LoomBackendError
from loom.errors import author_errors, render


def test_error_event_code_optional():
    # 不带 code:键集合与旧契约逐字节一致(老消费端零感知)
    ev = events.error("出错了")
    assert ev == {"type": "error", "message": "出错了"}
    # 带 code:多一个 code 键,值为错误目录键
    ev2 = events.error("余额不足", code="deepseek_insufficient_balance")
    assert ev2 == {"type": "error", "message": "余额不足", "code": "deepseek_insufficient_balance"}
    assert "deepseek_insufficient_balance" in author_errors   # code 必须真在目录里


def test_error_event_none_code_emits_no_key():
    assert "code" not in events.error("出错了", code=None)


def test_write_stream_error_event_carries_code(project, monkeypatch):
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    import loom.server as server
    import loom.usecases as usecases
    from loom import ledger, paths

    def boom(root, chapter, progress, **kw):
        raise LoomBackendError(render("deepseek_insufficient_balance"),
                               code="deepseek_insufficient_balance")

    monkeypatch.setattr(usecases, "write_chapter", boom)

    # 预置一章 Loom 快照 → 起书门禁豁免(本测试意在验错误 code 透传,不是门禁;写第2章)
    c1 = paths.chapter_path(project, 1); c1.parent.mkdir(parents=True, exist_ok=True)
    c1.write_text("# 第1章\n\nx\n", encoding="utf-8")
    snap1 = paths.snapshot_path(project, 1); snap1.parent.mkdir(parents=True, exist_ok=True)
    snap1.write_text(c1.read_text(encoding="utf-8"), encoding="utf-8")
    ledger.record_snapshot(project, 1, c1.read_text(encoding="utf-8"))

    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/write", json={"root": str(project), "chapter": 2})
    assert r.status_code == 200
    evs = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    err = next(e for e in evs if e["type"] == "error")
    assert err["code"] == "deepseek_insufficient_balance"
    assert "余额" in err["message"]


def test_json_endpoint_carries_code(project, monkeypatch):
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    import loom.server as server

    def no_key(cfg):
        raise LoomBackendError(render("deepseek_key_missing"), code="deepseek_key_missing")

    monkeypatch.setattr(server, "get_backend", no_key)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/learn", json={"root": str(project), "chapter": 1})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "deepseek_key_missing"
    assert "key" in body["error"].lower() or "API" in body["error"]


def test_json_endpoint_without_code_has_no_code_key(project, monkeypatch):
    # ValueError 等无 code 的错误:响应形状不变,不凭空多出 code 键
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    import loom.server as server

    monkeypatch.setattr(server, "get_backend",
                        lambda cfg: (_ for _ in ()).throw(ValueError("普通业务错误")))
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/learn", json={"root": str(project), "chapter": 1})
    assert r.status_code == 400
    assert "code" not in r.json()
