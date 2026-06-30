from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import loom.config
import loom.import_jobs
import loom.projects
import loom.server as server
from conftest import FakeBackend


RESULTS = {
    "worldview": "world",
    "system": "system",
    "characters": "characters",
    "outlines": "outlines",
}


def frames(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(loom.config.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(loom.import_jobs.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(loom.projects.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(server, "_import_recovery_done", False, raising=False)
    monkeypatch.setattr(
        server,
        "get_backend",
        lambda config: FakeBackend(lambda system, user: "parsed result"),
    )
    with TestClient(
        server.app,
        base_url="http://127.0.0.1",
        raise_server_exceptions=False,
    ) as value:
        yield value


def upload_bytes(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "book.txt",
    content_type: str = "text/plain",
):
    return client.post(
        "/api/imports",
        files={"file": (filename, content, content_type)},
    )


def upload(client: TestClient) -> dict:
    response = upload_bytes(client, "第1章 开始\n正文".encode())
    assert response.status_code == 201, response.text
    return response.json()


def ready_task(client: TestClient) -> dict:
    task = upload(client)
    detail = client.get(f"/api/imports/{task['id']}").json()
    response = client.put(
        f"/api/imports/{task['id']}/chapters",
        json={"chapters": detail["chapters"]},
    )
    assert response.status_code == 200, response.text
    return task


def completed_task(client: TestClient) -> dict:
    task = ready_task(client)
    response = client.post(f"/api/imports/{task['id']}/parse")
    assert response.status_code == 200, response.text
    assert frames(response)[-1]["type"] == "complete"
    return task


def test_upload_list_get_and_delete(client: TestClient) -> None:
    task = upload(client)

    listed = client.get("/api/imports")
    detail = client.get(f"/api/imports/{task['id']}")
    deleted = client.delete(f"/api/imports/{task['id']}")

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task["id"]
    assert detail.status_code == 200
    assert detail.json()["chapters"][0]["title"] == "第1章 开始"
    assert detail.json()["results"] == {}
    assert deleted.status_code == 204
    assert client.get(f"/api/imports/{task['id']}").status_code == 404


def test_parse_returns_ndjson_and_persists_results(client: TestClient) -> None:
    task = ready_task(client)

    response = client.post(f"/api/imports/{task['id']}/parse")

    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert frames(response)[-1]["type"] == "complete"
    detail = client.get(f"/api/imports/{task['id']}").json()
    assert detail["status"] == "completed"
    assert set(detail["results"]) == set(RESULTS)
    assert detail["result_revision"] == detail["chapter_revision"]


def test_upload_enforces_byte_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "MAX_IMPORT_BYTES", 4)

    response = upload_bytes(client, b"12345")

    assert response.status_code == 413
    assert "error" in response.json()
    assert client.get("/api/imports").json() == []


def test_upload_rejects_non_txt_filename(client: TestClient) -> None:
    response = upload_bytes(client, b"plain text", filename="book.md")

    assert response.status_code == 400
    assert "error" in response.json()


def test_upload_rejects_invalid_encoding(client: TestClient) -> None:
    response = upload_bytes(client, b"\x00" * 100)

    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("put", "/chapters", {"chapters": []}),
        ("post", "/parse", None),
        ("put", "/results", RESULTS),
        (
            "post",
            "/create-project",
            {"name": "Missing", "parent_dir": "."},
        ),
        ("delete", "", None),
    ],
)
def test_missing_task_ids_return_404(
    client: TestClient, method: str, suffix: str, body: dict | None
) -> None:
    task_id = str(uuid4())

    response = client.request(
        method, f"/api/imports/{task_id}{suffix}", json=body
    )

    assert response.status_code == 404, response.text
    assert "error" in response.json()


@pytest.mark.parametrize(
    "chapters",
    [
        [],
        [
            {
                "id": "c1",
                "order": 1,
                "title": "Chapter",
                "content": "body",
                "selected": False,
            }
        ],
        [
            {
                "order": 1,
                "title": "Chapter",
                "content": "body",
                "selected": True,
            }
        ],
        [
            {
                "id": "c1",
                "order": 1,
                "title": "Chapter",
                "selected": True,
            }
        ],
    ],
)
def test_invalid_chapter_payloads_return_400(
    client: TestClient, chapters: list[dict]
) -> None:
    task = upload(client)

    response = client.put(
        f"/api/imports/{task['id']}/chapters", json={"chapters": chapters}
    )

    assert response.status_code == 400, response.text
    assert "error" in response.json()


def test_duplicate_parse_returns_conflict(client: TestClient) -> None:
    task = ready_task(client)
    server._import_store().update(task["id"], status="running")

    response = client.post(f"/api/imports/{task['id']}/parse")

    assert response.status_code == 409, response.text
    assert response.json()["task"]["status"] == "running"


@pytest.mark.parametrize("operation", ["delete", "chapters", "results", "create"])
def test_running_task_rejects_mutations(
    client: TestClient, tmp_path: Path, operation: str
) -> None:
    task = upload(client)
    detail = client.get(f"/api/imports/{task['id']}").json()
    server._import_store().update(task["id"], status="running")

    if operation == "delete":
        response = client.delete(f"/api/imports/{task['id']}")
    elif operation == "chapters":
        response = client.put(
            f"/api/imports/{task['id']}/chapters",
            json={"chapters": detail["chapters"]},
        )
    elif operation == "results":
        response = client.put(
            f"/api/imports/{task['id']}/results", json=RESULTS
        )
    else:
        response = client.post(
            f"/api/imports/{task['id']}/create-project",
            json={"name": "Running", "parent_dir": str(tmp_path)},
        )

    assert response.status_code == 409, response.text
    assert "error" in response.json()


def test_saved_result_edits_are_returned(client: TestClient) -> None:
    task = completed_task(client)
    edited = {name: f"edited {name}" for name in RESULTS}

    response = client.put(f"/api/imports/{task['id']}/results", json=edited)

    assert response.status_code == 200, response.text
    assert response.json() == edited
    assert client.get(f"/api/imports/{task['id']}").json()["results"] == edited


def test_parse_streams_error_frame_and_persists_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = ready_task(client)

    def fail(system: str, user: str) -> str:
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(server, "get_backend", lambda config: FakeBackend(fail))

    response = client.post(f"/api/imports/{task['id']}/parse")

    assert response.status_code == 200
    assert frames(response)[-1]["type"] == "error"
    assert frames(response)[-1]["message"] == "backend exploded"
    detail = client.get(f"/api/imports/{task['id']}").json()
    assert detail["status"] == "failed"
    assert detail["error"] == {"message": "backend exploded"}


def test_parse_maps_runtime_config_failures_before_stream(client: TestClient) -> None:
    task = ready_task(client)
    runtime = server._import_store().runtime_root(task["id"])
    (runtime / "loom.toml").write_text("not = [valid", encoding="utf-8")

    response = client.post(f"/api/imports/{task['id']}/parse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert "error" in response.json()


def test_startup_recovers_running_tasks_once_per_process(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = upload(client)
    store = server._import_store()
    store.update(task["id"], status="running", phase="worldview")
    calls = 0
    original = loom.import_jobs.ImportJobStore.recover_interrupted

    def recover_once(self) -> int:
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(
        loom.import_jobs.ImportJobStore, "recover_interrupted", recover_once
    )
    monkeypatch.setattr(server, "_import_recovery_done", False)

    with TestClient(server.app, base_url="http://127.0.0.1"):
        pass
    with TestClient(server.app, base_url="http://127.0.0.1"):
        pass

    recovered = store.get(task["id"])
    assert calls == 1
    assert recovered["status"] == "interrupted"
    assert recovered["phase"] == "worldview"


def test_create_project_rejects_existing_destination(
    client: TestClient, tmp_path: Path
) -> None:
    task = completed_task(client)
    (tmp_path / "Existing").mkdir()

    response = client.post(
        f"/api/imports/{task['id']}/create-project",
        json={"name": "Existing", "parent_dir": str(tmp_path)},
    )

    assert response.status_code == 409, response.text
    assert "error" in response.json()


def test_create_project_returns_state_and_registers_project(
    client: TestClient, tmp_path: Path
) -> None:
    task = completed_task(client)

    response = client.post(
        f"/api/imports/{task['id']}/create-project",
        json={
            "name": "Imported",
            "parent_dir": str(tmp_path),
            "include_source_chapters": True,
        },
    )

    assert response.status_code == 200, response.text
    state = response.json()
    assert Path(state["root"]) == tmp_path / "Imported"
    registry = loom.projects.list_all()
    assert Path(registry["projects"]["Imported"]["path"]) == (
        tmp_path / "Imported"
    ).resolve()
    assert list((tmp_path / "Imported" / "正文" / ".原稿").glob("*.md"))


def test_unexpected_create_failure_returns_500_and_destination(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = completed_task(client)

    def fail(*args, **kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(server, "materialize_import", fail)

    response = client.post(
        f"/api/imports/{task['id']}/create-project",
        json={"name": "Broken", "parent_dir": str(tmp_path)},
    )

    assert response.status_code == 500, response.text
    assert response.json()["error"] == "registry unavailable"
    assert Path(response.json()["path"]) == tmp_path / "Broken"
