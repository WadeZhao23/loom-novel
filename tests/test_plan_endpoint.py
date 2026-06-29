from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import FakeBackend
from loom.chapter_plan import outline_path
from loom.server import app


def _parse_ndjson(text: str) -> list[dict]:
    lines = [line for line in text.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_plan_generate_streams_two_chapters_and_writes_two_files(project, monkeypatch) -> None:
    def respond(system: str, user: str) -> str:
        match = re.search(r"当前任务：为第\s*(\d+)\s*章", user)
        chapter = int(match.group(1)) if match else 0
        return f"第{chapter}章：目标、冲突、反转、章末钩子都清楚。"

    backend = FakeBackend(respond)
    monkeypatch.setattr("loom.server.get_backend", lambda cfg: backend)

    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    response = client.post(
        "/api/plan/generate",
        json={"root": str(project), "total_chapters": 2, "start_from": 1, "force": False},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")

    events = _parse_ndjson(response.text)
    assert [event["type"] for event in events] == [
        "progress",
        "done",
        "progress",
        "done",
        "complete",
    ]
    assert events[-1] == {"type": "complete", "planned": 2, "skipped": 0}
    assert outline_path(project, 1).read_text(encoding="utf-8").strip() == "第1章：目标、冲突、反转、章末钩子都清楚。"
    assert outline_path(project, 2).read_text(encoding="utf-8").strip() == "第2章：目标、冲突、反转、章末钩子都清楚。"


def test_plan_generate_reports_error_for_invalid_root(tmp_path: Path) -> None:
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)

    response = client.post(
        "/api/plan/generate",
        json={"root": str(tmp_path / "missing"), "total_chapters": 1},
    )

    assert response.status_code == 200
    events = _parse_ndjson(response.text)
    assert events[-1]["type"] == "error"
