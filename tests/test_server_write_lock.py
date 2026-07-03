"""落盘端点互斥:同一本书 write 在跑时,再点 write/learn 直接 409「正在写作中」;跑完锁释放。
进程内 per-project 锁,挡双击/并发同写一章(单用户本地应用,不做跨进程锁)。"""
from __future__ import annotations

import threading

import pytest

pytest.importorskip("httpx")   # starlette TestClient 依赖 httpx(随 openai 一起装)
from starlette.testclient import TestClient  # noqa: E402

import loom.server as server  # noqa: E402
import loom.usecases as usecases  # noqa: E402


def test_write_mutex_blocks_concurrent_write_and_learn(project, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def fake_pipeline(root, chapter_n, backend, cfg, progress, **kw):
        started.set()
        assert release.wait(5), "测试超时:主线程没放行"
        progress({"type": "chapter_done", "chapter": chapter_n})
        return root, "x"

    # 编排(锁 + pipeline 调用)已下沉 usecases;server 只在 learn 端点建后端 → 两处都补桩
    monkeypatch.setattr(usecases, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(usecases, "get_backend", lambda cfg: object())
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: None)
    monkeypatch.setattr(server, "get_backend", lambda cfg: object())
    monkeypatch.setattr(server, "cheap_backend", lambda cfg: None)

    body = {"root": str(project), "chapter": 1}
    first: dict = {}

    def run_first():
        with TestClient(server.app, base_url="http://127.0.0.1") as c:
            first["resp"] = c.post("/api/write", json=body)

    t = threading.Thread(target=run_first)
    t.start()
    try:
        assert started.wait(5), "write worker 没启动"

        # 第一次 write 还在跑:再点 write / learn 都被 409 挡住
        client = TestClient(server.app, base_url="http://127.0.0.1")
        r2 = client.post("/api/write", json=body)
        assert r2.status_code == 409
        assert "正在写作中" in r2.json()["error"]
        r3 = client.post("/api/learn", json=body)
        assert r3.status_code == 409
    finally:
        release.set()
        t.join(5)

    assert first["resp"].status_code == 200
    assert "chapter_done" in first["resp"].text

    # 跑完锁已释放:learn 不再被 409 挡(本例缺原稿快照 → 业务 400,不是 project_busy)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r4 = client.post("/api/learn", json=body)
    assert r4.status_code != 409
