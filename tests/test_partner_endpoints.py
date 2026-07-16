"""/api/partner/* 端点:say 流式(独立轮锁,不碰书写锁)+ confirm/new/history。
锁裁量红线(spec §10):say 完全不碰书写锁——织章持写锁跑几分钟期间,say 照样能聊;
只挡两次并发 say 交错写同一 .伙伴对话/当前.jsonl。confirm/new 走真 write_lock。"""
from __future__ import annotations

import json
import threading

import pytest

pytest.importorskip("httpx")   # starlette TestClient 依赖 httpx(随 openai 一起装)
from starlette.testclient import TestClient  # noqa: E402

import loom.server as server  # noqa: E402
import loom.usecases as usecases  # noqa: E402
from loom import partner_store as ps  # noqa: E402
from loom.backends import LoomBackendError  # noqa: E402
from conftest import ScriptedBackend  # noqa: E402


def test_say_streams_events(project, monkeypatch):
    monkeypatch.setattr(server, "get_backend", lambda cfg: ScriptedBackend(["你好呀,我们从金手指聊起?"]))
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/partner/say", json={"root": str(project), "text": "你好"})
    assert r.status_code == 200
    lines = [json.loads(line) for line in r.text.strip().splitlines() if line]
    kinds = [e["t"] for e in lines]
    assert "user" in kinds and "assistant" in kinds
    assistant_ev = next(e for e in lines if e["t"] == "assistant")
    assert "金手指" in assistant_ev["text"]
    # 事件也落了盘(jsonl),不只是流过去
    assert [e["t"] for e in ps.read_events(project)] == ["user", "assistant"]


def test_say_error_event_uses_partner_envelope(project, monkeypatch):
    """backend 抛 LoomBackendError 时,error 事件走 partner 信封({"t":"error",...}),
    不是 /api/write 那套 type-keyed({"type":"error",...})——前端按 e["t"] 分派,信封错了会漏判。"""
    class BoomBackend:
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            raise LoomBackendError("后端炸了", code="rate_limited")

    monkeypatch.setattr(server, "get_backend", lambda cfg: BoomBackend())
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/partner/say", json={"root": str(project), "text": "你好"})
    assert r.status_code == 200
    lines = [json.loads(line) for line in r.text.strip().splitlines() if line]
    error_ev = next(e for e in lines if e.get("t") == "error")
    assert error_ev["t"] == "error"
    assert "type" not in error_ev
    assert error_ev["text"] == "后端炸了"
    assert error_ev["code"] == "rate_limited"
    assert "ts" in error_ev


def test_say_lock_blocks_concurrent_say_with_partner_busy(project, monkeypatch):
    """partner 轮锁互斥:第一次 say 还在跑时,第二次 say 直接 409 partner_busy。"""
    started, release = threading.Event(), threading.Event()

    class BlockingBackend:
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            started.set()
            assert release.wait(5), "测试超时:主线程没放行"
            return "好的,我们继续。"

    monkeypatch.setattr(server, "get_backend", lambda cfg: BlockingBackend())

    body = {"root": str(project), "text": "你好"}
    first: dict = {}

    def run_first():
        with TestClient(server.app, base_url="http://127.0.0.1") as c:
            first["resp"] = c.post("/api/partner/say", json=body)

    t = threading.Thread(target=run_first)
    t.start()
    try:
        assert started.wait(5), "say worker 没启动"

        client = TestClient(server.app, base_url="http://127.0.0.1")
        r2 = client.post("/api/partner/say", json=body)
        assert r2.status_code == 409
        assert r2.json()["code"] == "partner_busy"
    finally:
        release.set()
        t.join(5)

    assert first["resp"].status_code == 200

    # 跑完锁已释放:再次 say 不再被 409 挡
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r3 = client.post("/api/partner/say", json=body)
    assert r3.status_code == 200


def test_say_not_blocked_by_write_lock(project, monkeypatch):
    """锁裁量灵魂:织章持有书写锁(write_lock)期间,say 用的是独立轮锁,不受影响。"""
    monkeypatch.setattr(server, "get_backend", lambda cfg: ScriptedBackend(["还在呢,继续说。"]))
    lock = usecases.acquire_lock(project)   # 模拟织章正持有书写锁(不是伙伴轮锁)
    try:
        client = TestClient(server.app, base_url="http://127.0.0.1")
        r = client.post("/api/partner/say", json={"root": str(project), "text": "你好"})
        assert r.status_code == 200
        assert "assistant" in r.text
    finally:
        lock.release()


def test_confirm_endpoint_lands_proposal(project):
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                              "slot": "外置大脑/立项卡.md#平台", "content": "番茄"})
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/partner/confirm", json={"root": str(project), "id": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert body["landed"].endswith("立项卡.md")
    assert "平台:番茄" in (project / "外置大脑/立项卡.md").read_text(encoding="utf-8")


def test_confirm_endpoint_expired_proposal_returns_error_not_500(project):
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/partner/confirm", json={"root": str(project), "id": "no-such-id"})
    assert r.status_code == 200   # usecases.partner_confirm 内部已兜成 {"error": ...},非异常
    assert r.json() == {"error": "提案已过期,重新问一次"}


def test_new_endpoint_archives_conversation(project):
    ps.append_event(project, {"t": "user", "ts": "1", "text": "你好"})
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/partner/new", json={"root": str(project)})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert ps.read_events(project) == []


def test_history_endpoint_reads_events(project):
    ps.append_event(project, {"t": "user", "ts": "1", "text": "你好"})
    ps.append_event(project, {"t": "assistant", "ts": "2", "text": "在的"})
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.get("/api/partner/history", params={"root": str(project)})
    assert r.status_code == 200
    assert [e["t"] for e in r.json()["events"]] == ["user", "assistant"]
