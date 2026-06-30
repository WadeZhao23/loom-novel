from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import UUID

import pytest

from conftest import FakeBackend
from loom.import_jobs import ImportJobConflict, ImportJobStore
from loom.reverse_parse import PHASES, chunk_chapters, run_parse


@pytest.fixture
def store(tmp_path: Path) -> ImportJobStore:
    return ImportJobStore(tmp_path / "imports")


def chapters() -> list[dict]:
    return [
        {"id": "c1", "order": 1, "title": "第一章", "content": "甲" * 6, "selected": True},
        {"id": "c2", "order": 2, "title": "第二章", "content": "乙" * 6, "selected": False},
        {"id": "c3", "order": 3, "title": "第三章", "content": "丙" * 6, "selected": True},
    ]


def create_ready_job(store: ImportJobStore, rows: list[dict] | None = None) -> str:
    task = store.create(
        "book.txt",
        b"book",
        "normalized",
        "utf-8",
        rows or chapters(),
        "high",
    )
    store.update(task["id"], status="ready")
    return task["id"]


def phase_responder(system: str, user: str) -> str:
    for phase in PHASES:
        if f"phase={phase}" in system:
            return f"{phase}:{user[:24]}"
    raise AssertionError(f"missing phase marker: {system}")


def test_chunk_chapters_honors_budget_without_splitting_chapters() -> None:
    rows = chapters()

    chunks = chunk_chapters(rows, char_budget=20)

    assert chunks == [[rows[0]], [rows[1]], [rows[2]]]
    assert all(chunk[0] is rows[index] for index, chunk in enumerate(chunks))


def test_chunk_chapters_rejects_rendered_chapter_over_budget() -> None:
    chapter = {**chapters()[0], "title": "T", "content": "xxxxx"}
    rendered_size = len("# T\n\nxxxxx")

    assert chunk_chapters([chapter], char_budget=rendered_size) == [[chapter]]
    with pytest.raises(ValueError, match="(?i)chapter.*budget"):
        chunk_chapters([chapter], char_budget=rendered_size - 1)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_chunk_chapters_rejects_invalid_budget(budget: object) -> None:
    with pytest.raises(ValueError):
        chunk_chapters(chapters(), char_budget=budget)  # type: ignore[arg-type]


def test_chunk_chapters_returns_empty_for_empty_input() -> None:
    assert chunk_chapters([], char_budget=10) == []


def test_pipeline_completes_all_phases_persists_results_and_events(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)
    events: list[dict] = []

    results = run_parse(
        store,
        task_id,
        FakeBackend(phase_responder),
        progress=events.append,
        char_budget=20,
    )

    assert set(results) == set(PHASES)
    assert store.get_results(task_id) == results
    task = store.get(task_id)
    assert task["status"] == "completed"
    assert task["result_revision"] == task["chapter_revision"]
    assert task["run_id"] is None
    assert [event["phase"] for event in events if event["type"] == "phase"] == list(PHASES)
    assert [event["phase"] for event in events if event["type"] == "phase_done"] == list(PHASES)
    assert [event["type"] for event in events].count("progress") == 11
    assert events[-1] == {"type": "complete", "completed": 11, "total": 11}
    assert all(
        event["completed"] <= event["total"] == 11
        for event in events
        if "completed" in event
    )


@pytest.mark.parametrize("event_type", ["phase", "progress", "phase_done", "complete"])
def test_progress_callback_failure_does_not_change_successful_completion(
    store: ImportJobStore, event_type: str
) -> None:
    task_id = create_ready_job(store)

    def fail_on_event(event: dict) -> None:
        if event["type"] == event_type:
            raise RuntimeError(f"callback failed on {event_type}")

    results = run_parse(
        store,
        task_id,
        FakeBackend(phase_responder),
        progress=fail_on_event,
        char_budget=100,
    )

    task = store.get(task_id)
    assert task["status"] == "completed"
    assert task["result_revision"] == task["chapter_revision"]
    assert store.get_results(task_id) == results


def test_pipeline_sends_only_selected_chapter_titles_and_content(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)
    backend = FakeBackend(phase_responder)

    run_parse(store, task_id, backend, char_budget=100)

    payload = "\n".join(user for _, user in backend.calls)
    assert "第一章" in payload and "甲甲甲" in payload
    assert "第三章" in payload and "丙丙丙" in payload
    assert "第二章" not in payload and "乙乙乙" not in payload


def test_pipeline_rejects_oversized_chapter_before_running(
    store: ImportJobStore,
) -> None:
    row = {
        "id": "large",
        "order": 1,
        "title": "Large chapter",
        "content": "x" * 20,
        "selected": True,
    }
    task_id = create_ready_job(store, [row])
    backend = FakeBackend(phase_responder)

    with pytest.raises(ValueError, match="(?i)chapter.*budget"):
        run_parse(store, task_id, backend, char_budget=20)

    task = store.get(task_id)
    assert task["status"] == "ready"
    assert task.get("run_id") is None
    assert backend.calls == []


def test_pipeline_resumes_completed_chunks_after_later_call_fails(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)
    call_count = 0

    def fail_worldview_merge(system: str, user: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("merge failed")
        return phase_responder(system, user)

    with pytest.raises(RuntimeError, match="merge failed"):
        run_parse(store, task_id, FakeBackend(fail_worldview_merge), char_budget=20)

    resumed = FakeBackend(phase_responder)
    run_parse(store, task_id, resumed, char_budget=20)

    assert "merge" in resumed.calls[0][0].lower()
    assert len(resumed.calls) == 9


@pytest.mark.parametrize("stale_kind", ["hash", "revision", "selected_ids", "chunk_text"])
def test_stale_checkpoint_is_rejected_and_recomputed(
    store: ImportJobStore, stale_kind: str
) -> None:
    task_id = create_ready_job(store)
    calls = 0

    def fail_merge(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("stop after chunks")
        return phase_responder(system, user)

    with pytest.raises(RuntimeError):
        run_parse(store, task_id, FakeBackend(fail_merge), char_budget=20)

    checkpoint_path = store.checkpoint_path(task_id, "worldview")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if stale_kind == "hash":
        checkpoint["chunks"][0]["input_hash"] = "stale"
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    elif stale_kind == "revision":
        checkpoint["revision"] += 1
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    elif stale_kind == "selected_ids":
        chapters_path = store.root / task_id / "chapters.json"
        persisted = json.loads(chapters_path.read_text(encoding="utf-8"))
        persisted[0]["id"] = "changed-c1"
        chapters_path.write_text(json.dumps(persisted, ensure_ascii=False), encoding="utf-8")
    else:
        chapters_path = store.root / task_id / "chapters.json"
        persisted = json.loads(chapters_path.read_text(encoding="utf-8"))
        persisted[0]["content"] += "已修改"
        chapters_path.write_text(json.dumps(persisted, ensure_ascii=False), encoding="utf-8")

    resumed = FakeBackend(phase_responder)
    run_parse(store, task_id, resumed, char_budget=20)

    assert "merge" not in resumed.calls[0][0].lower()


def test_checkpoints_have_exact_schema(store: ImportJobStore) -> None:
    task_id = create_ready_job(store)

    run_parse(store, task_id, FakeBackend(phase_responder), char_budget=20)

    for phase in PHASES:
        checkpoint = json.loads(store.checkpoint_path(task_id, phase).read_text(encoding="utf-8"))
        assert set(checkpoint) == {"phase", "revision", "chunks", "merged"}
        assert checkpoint["phase"] == phase
        assert checkpoint["revision"] == store.get(task_id)["chapter_revision"]
        assert all(set(chunk) == {"index", "input_hash", "output"} for chunk in checkpoint["chunks"])
        assert checkpoint["merged"] == store.get_results(task_id)[phase]


def test_running_task_rejects_second_caller(store: ImportJobStore) -> None:
    task_id = create_ready_job(store)
    first_call_started = Event()
    release_first_call = Event()

    def blocking_responder(system: str, user: str) -> str:
        first_call_started.set()
        assert release_first_call.wait(timeout=5)
        return phase_responder(system, user)

    first_backend = FakeBackend(blocking_responder)
    second_backend = FakeBackend(phase_responder)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run_parse, store, task_id, first_backend)
        assert first_call_started.wait(timeout=5)
        try:
            with pytest.raises(ImportJobConflict):
                run_parse(store, task_id, second_backend)
        finally:
            release_first_call.set()
        assert set(first.result(timeout=5)) == set(PHASES)

    assert first_backend.calls
    assert second_backend.calls == []


def test_stale_worker_cannot_write_after_chapters_change(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)
    backend_started = Event()
    release_backend = Event()

    def blocking_responder(system: str, user: str) -> str:
        backend_started.set()
        assert release_backend.wait(timeout=5)
        return phase_responder(system, user)

    with ThreadPoolExecutor(max_workers=1) as pool:
        parsing = pool.submit(
            run_parse, store, task_id, FakeBackend(blocking_responder), char_budget=100
        )
        assert backend_started.wait(timeout=5)
        try:
            running = store.get(task_id)
            assert str(UUID(running["run_id"])) == running["run_id"]

            revised = [dict(chapter) for chapter in store.get_chapters(task_id)]
            revised[0]["content"] = "new revision content"
            store.save_chapters(task_id, revised)
        finally:
            release_backend.set()

        with pytest.raises(ImportJobConflict, match="ownership"):
            parsing.result(timeout=5)

    task = store.get(task_id)
    assert task["status"] == "ready"
    assert task["chapter_revision"] == 2
    assert task["result_revision"] is None
    assert store.get_results(task_id) == {}
    assert list((store.root / task_id / "checkpoints").iterdir()) == []


def test_stale_worker_cannot_overwrite_newer_run_owner(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)
    backend_started = Event()
    release_backend = Event()

    def blocking_responder(system: str, user: str) -> str:
        backend_started.set()
        assert release_backend.wait(timeout=5)
        return phase_responder(system, user)

    with ThreadPoolExecutor(max_workers=1) as pool:
        parsing = pool.submit(
            run_parse, store, task_id, FakeBackend(blocking_responder), char_budget=100
        )
        assert backend_started.wait(timeout=5)
        try:
            store.update(task_id, status="running", run_id="newer-owner")
        finally:
            release_backend.set()

        with pytest.raises(ImportJobConflict, match="ownership"):
            parsing.result(timeout=5)

    task = store.get(task_id)
    assert task["status"] == "running"
    assert task["run_id"] == "newer-owner"
    assert task["error"] is None
    assert store.get_results(task_id) == {}
    assert list((store.root / task_id / "checkpoints").iterdir()) == []


def test_chapter_loading_does_not_hold_task_lock(store: ImportJobStore) -> None:
    task_id = create_ready_job(store)
    chapter_read_started = Event()
    release_chapter_read = Event()
    lock_acquired = Event()

    class BlockingChapterStore(ImportJobStore):
        def get_chapters(self, requested_task_id: str) -> list[dict]:
            chapter_read_started.set()
            assert release_chapter_read.wait(timeout=5)
            return super().get_chapters(requested_task_id)

    worker_store = BlockingChapterStore(store.root)

    def acquire_task_lock() -> None:
        with store.lock(task_id):
            lock_acquired.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        parsing = pool.submit(
            run_parse, worker_store, task_id, FakeBackend(phase_responder)
        )
        assert chapter_read_started.wait(timeout=5)
        checking_lock = pool.submit(acquire_task_lock)
        try:
            assert lock_acquired.wait(timeout=1)
        finally:
            release_chapter_read.set()
        checking_lock.result(timeout=5)
        assert set(parsing.result(timeout=5)) == set(PHASES)


def test_checkpoint_read_does_not_hold_task_lock(
    store: ImportJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = create_ready_job(store)
    checkpoint = store.checkpoint_path(task_id, "worldview")
    checkpoint.write_text("{}", encoding="utf-8")
    checkpoint_read_started = Event()
    release_checkpoint_read = Event()
    lock_acquired = Event()
    original_read_text = Path.read_text

    def blocking_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == checkpoint:
            checkpoint_read_started.set()
            assert release_checkpoint_read.wait(timeout=5)
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", blocking_read_text)

    def acquire_task_lock() -> None:
        with store.lock(task_id):
            lock_acquired.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        parsing = pool.submit(run_parse, store, task_id, FakeBackend(phase_responder))
        assert checkpoint_read_started.wait(timeout=5)
        checking_lock = pool.submit(acquire_task_lock)
        try:
            assert lock_acquired.wait(timeout=1)
        finally:
            release_checkpoint_read.set()
        checking_lock.result(timeout=5)
        assert set(parsing.result(timeout=5)) == set(PHASES)


def test_revision_change_during_preparation_retries_with_new_chapters(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)

    class RevisionChangingStore(ImportJobStore):
        chapter_reads = 0

        def get_chapters(self, requested_task_id: str) -> list[dict]:
            rows = super().get_chapters(requested_task_id)
            self.chapter_reads += 1
            if self.chapter_reads == 1:
                revised = [dict(chapter) for chapter in rows]
                revised[0]["content"] = "revision-two-content"
                self.save_chapters(requested_task_id, revised)
            return rows

    worker_store = RevisionChangingStore(store.root)
    backend = FakeBackend(phase_responder)

    run_parse(worker_store, task_id, backend, char_budget=100)

    task = store.get(task_id)
    assert worker_store.chapter_reads == 2
    assert task["chapter_revision"] == 2
    assert task["result_revision"] == 2
    assert "revision-two-content" in "\n".join(user for _, user in backend.calls)


def test_failure_persists_phase_and_error_emits_event_and_reraises(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)
    events: list[dict] = []

    def fail_system(system: str, user: str) -> str:
        if "phase=system" in system:
            raise RuntimeError("system exploded")
        return phase_responder(system, user)

    with pytest.raises(RuntimeError, match="system exploded"):
        run_parse(store, task_id, FakeBackend(fail_system), progress=events.append)

    task = store.get(task_id)
    assert task["status"] == "failed"
    assert task["phase"] == "system"
    assert task["error"] == {"message": "system exploded"}
    assert task["run_id"] is None
    assert events[-1] == {"type": "error", "phase": "system", "message": "system exploded"}


def test_error_callback_failure_does_not_mask_backend_failure(
    store: ImportJobStore,
) -> None:
    task_id = create_ready_job(store)

    def backend_failure(system: str, user: str) -> str:
        raise RuntimeError("backend exploded")

    def callback_failure(event: dict) -> None:
        if event["type"] == "error":
            raise RuntimeError("callback exploded")

    with pytest.raises(RuntimeError, match="backend exploded"):
        run_parse(
            store,
            task_id,
            FakeBackend(backend_failure),
            progress=callback_failure,
            char_budget=100,
        )

    task = store.get(task_id)
    assert task["status"] == "failed"
    assert task["error"] == {"message": "backend exploded"}


@pytest.mark.parametrize(
    ("status", "result_revision", "error_type"),
    [
        ("reviewing", None, ValueError),
        ("completed", 1, ImportJobConflict),
        ("completed", None, ImportJobConflict),
        ("running", None, ImportJobConflict),
    ],
)
def test_pipeline_rejects_ineligible_statuses(
    store: ImportJobStore,
    status: str,
    result_revision: int | None,
    error_type: type[Exception],
) -> None:
    task_id = create_ready_job(store)
    store.update(task_id, status=status, result_revision=result_revision)

    with pytest.raises(error_type):
        run_parse(store, task_id, FakeBackend(phase_responder))


def test_pipeline_rejects_empty_selection(store: ImportJobStore) -> None:
    task_id = create_ready_job(store)
    chapters_path = store.root / task_id / "chapters.json"
    persisted = json.loads(chapters_path.read_text(encoding="utf-8"))
    for chapter in persisted:
        chapter["selected"] = False
    chapters_path.write_text(json.dumps(persisted, ensure_ascii=False), encoding="utf-8")
    store.update(task_id, selected_chapter_ids=[])

    with pytest.raises(ValueError, match="selected"):
        run_parse(store, task_id, FakeBackend(phase_responder))
