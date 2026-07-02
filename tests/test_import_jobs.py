from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from loom.import_jobs import ImportJobConflict, ImportJobError, ImportJobNotFound, ImportJobStore


@pytest.fixture
def store(tmp_path: Path) -> ImportJobStore:
    return ImportJobStore(tmp_path / "imports")


def sample_chapters(*, selected: bool = True) -> list[dict]:
    return [
        {
            "id": "c1",
            "order": 1,
            "title": "First",
            "content": "Opening",
            "selected": selected,
        },
        {
            "id": "c2",
            "order": 2,
            "title": "Second",
            "content": "Development",
            "selected": selected,
        },
    ]


def create_job(store: ImportJobStore) -> dict:
    return store.create(
        original_filename="book.txt",
        raw=b"book bytes",
        normalized_text="Body",
        encoding="utf-8",
        chapters=sample_chapters(),
        split_confidence="high",
    )


def test_create_persists_source_metadata_chapters_and_runtime(store: ImportJobStore) -> None:
    task = create_job(store)

    loaded = store.get(task["id"])
    assert loaded["status"] == "reviewing"
    assert loaded["chapter_revision"] == 1
    assert loaded["result_revision"] is None
    assert loaded["original_filename"] == "book.txt"
    assert loaded["encoding"] == "utf-8"
    assert loaded["split_confidence"] == "high"
    assert loaded["progress"] == {"completed": 0, "total": 0}
    assert store.source_path(task["id"], normalized=False).read_bytes() == b"book bytes"
    assert store.source_path(task["id"], normalized=True).read_text(encoding="utf-8") == "Body"
    assert store.get_chapters(task["id"])[1]["title"] == "Second"
    assert (store.runtime_root(task["id"]) / "loom.toml").is_file()


def test_invalid_task_id_cannot_escape_store(store: ImportJobStore) -> None:
    with pytest.raises(ValueError):
        store.get("../outside")


def test_get_does_not_recover_running_task(store: ImportJobStore) -> None:
    task = create_job(store)
    store.update(task["id"], status="running", phase="worldview")

    assert store.get(task["id"])["status"] == "running"


def test_recover_interrupted_is_explicit_and_preserves_phase(store: ImportJobStore) -> None:
    task = create_job(store)
    store.update(task["id"], status="running", phase="worldview")

    restarted = ImportJobStore(store.root)
    assert restarted.recover_interrupted() == 1
    loaded = restarted.get(task["id"])
    assert loaded["status"] == "interrupted"
    assert loaded["phase"] == "worldview"
    assert restarted.recover_interrupted() == 0


def test_recover_interrupted_does_not_overwrite_concurrent_completion(
    store: ImportJobStore,
) -> None:
    task = create_job(store)
    store.update(task["id"], status="running", phase="worldview")
    listed = Event()
    resume_recovery = Event()

    class PausingImportJobStore(ImportJobStore):
        def list(self) -> list[dict]:
            tasks = super().list()
            listed.set()
            assert resume_recovery.wait(timeout=5)
            return tasks

    recovering = PausingImportJobStore(store.root)

    with ThreadPoolExecutor(max_workers=1) as pool:
        recovery = pool.submit(recovering.recover_interrupted)
        assert listed.wait(timeout=5)
        store.update(task["id"], status="completed")
        resume_recovery.set()
        assert recovery.result(timeout=5) == 0

    assert store.get(task["id"])["status"] == "completed"


def test_save_chapters_invalidates_stale_outputs(store: ImportJobStore) -> None:
    task = create_job(store)
    store.update(task["id"], status="completed", result_revision=1)
    checkpoint = store.checkpoint_path(task["id"], "worldview")
    checkpoint.write_text("checkpoint", encoding="utf-8")
    store.save_results(
        task["id"],
        {"worldview": "w", "system": "s", "characters": "c", "outlines": "o"},
    )

    saved = store.save_chapters(task["id"], sample_chapters())

    assert saved["chapter_revision"] == 2
    assert saved["result_revision"] is None
    assert saved["status"] == "ready"
    assert list(checkpoint.parent.iterdir()) == []
    assert store.get_results(task["id"]) == {}


def test_task_lock_serializes_updates(store: ImportJobStore) -> None:
    task = create_job(store)

    def bump() -> None:
        with store.lock(task["id"]):
            current = store.get(task["id"])
            completed = current["progress"]["completed"] + 1
            store.update(task["id"], progress={"completed": completed, "total": 2})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: bump(), range(2)))

    assert store.get(task["id"])["progress"]["completed"] == 2


def test_list_returns_newest_updated_first(store: ImportJobStore) -> None:
    first = create_job(store)
    second = create_job(store)
    store.update(first["id"], marker="newest")

    assert [task["id"] for task in store.list()] == [first["id"], second["id"]]


def test_chapter_count_does_not_deserialize_chapter_bodies(
    store: ImportJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = create_job(store)

    def fail_if_chapters_json_is_deserialized(path: Path) -> object:
        if path.name == "chapters.json":
            raise AssertionError("chapter_count should not load chapter bodies")
        return json.loads(path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "loom.import_jobs._read_json", fail_if_chapters_json_is_deserialized
    )

    assert store.chapter_count(task["id"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        "[{}{}]",
        "[{},,{}]",
        "[{foo}]",
        "[[{}]]",
    ],
)
def test_chapter_count_rejects_malformed_chapter_arrays(
    store: ImportJobStore, payload: str
) -> None:
    task = create_job(store)
    (store._task_root(task["id"]) / "chapters.json").write_text(
        payload, encoding="utf-8"
    )

    with pytest.raises(ImportJobError):
        store.chapter_count(task["id"])


@pytest.mark.parametrize("whitespace", ["\u00a0", "\u2028"])
def test_chapter_count_rejects_non_json_unicode_whitespace(
    store: ImportJobStore, whitespace: str
) -> None:
    task = create_job(store)
    (store._task_root(task["id"]) / "chapters.json").write_text(
        f"[{whitespace}{{}}]", encoding="utf-8"
    )

    with pytest.raises(ImportJobError):
        store.chapter_count(task["id"])


def test_chapter_count_rejects_unicode_digit_number_tokens(
    store: ImportJobStore,
) -> None:
    task = create_job(store)
    (store._task_root(task["id"]) / "chapters.json").write_text(
        '[{"count": \u0661}]', encoding="utf-8"
    )

    with pytest.raises(ImportJobError):
        store.chapter_count(task["id"])


def test_chapter_count_wraps_deep_recursion_as_import_error(
    store: ImportJobStore,
) -> None:
    task = create_job(store)
    nested_value = "[" * 2000 + "0" + "]" * 2000
    (store._task_root(task["id"]) / "chapters.json").write_text(
        f'[{{"nested": {nested_value}}}]', encoding="utf-8"
    )

    with pytest.raises(ImportJobError, match="deeply nested"):
        store.chapter_count(task["id"])


def test_missing_task_raises_domain_error(store: ImportJobStore) -> None:
    with pytest.raises(ImportJobNotFound):
        store.get("00000000-0000-0000-0000-000000000000")


def test_delete_removes_task_and_rejects_running(store: ImportJobStore) -> None:
    task = create_job(store)
    store.update(task["id"], status="running")
    with pytest.raises(ImportJobConflict):
        store.delete(task["id"])

    store.update(task["id"], status="completed")
    store.delete(task["id"])
    with pytest.raises(ImportJobNotFound):
        store.get(task["id"])


def test_results_require_exact_keys_and_allowed_status(store: ImportJobStore) -> None:
    task = create_job(store)
    results = {"worldview": "w", "system": "s", "characters": "c", "outlines": "o"}

    with pytest.raises(ValueError):
        store.save_results(task["id"], results)
    store.update(task["id"], status="running", result_revision=1)
    saved = store.save_results(task["id"], results)
    assert saved == results
    assert store.get_results(task["id"]) == results
    assert store.get(task["id"])["result_revision"] == 1
    with pytest.raises(ValueError):
        store.save_results(task["id"], {**results, "extra": "x"})


@pytest.mark.parametrize(
    "chapters",
    [
        [],
        [
            {"id": "same", "order": 1, "title": "First", "content": "x", "selected": True},
            {"id": "same", "order": 2, "title": "Second", "content": "y", "selected": True},
        ],
        [
            {"id": "c1", "order": 1, "title": "First", "content": "x", "selected": True},
            {"id": "c2", "order": 1, "title": "Second", "content": "y", "selected": True},
        ],
        [
            {"id": "c1", "order": 1, "title": "First", "content": "x", "selected": True},
            {"id": "c2", "order": 3, "title": "Second", "content": "y", "selected": True},
        ],
        [{"id": "c1", "order": 1, "title": " ", "content": "x", "selected": True}],
        [{"id": "c1", "order": 1, "title": "First", "selected": True}],
        [{"id": "c1", "order": 1, "title": "First", "content": None, "selected": True}],
        sample_chapters(selected=False),
    ],
    ids=[
        "empty",
        "duplicate-id",
        "duplicate-order",
        "noncontiguous",
        "blank-title",
        "missing-content",
        "non-string-content",
        "none-selected",
    ],
)
def test_create_validates_chapters(store: ImportJobStore, chapters: list[dict]) -> None:
    with pytest.raises(ValueError):
        store.create("book.txt", b"x", "x", "utf-8", chapters, "high")


def test_get_chapters_rejects_persisted_chapter_without_text_content(
    store: ImportJobStore,
) -> None:
    task = create_job(store)
    chapters = sample_chapters()
    del chapters[0]["content"]
    (store.root / task["id"] / "chapters.json").write_text(
        json.dumps(chapters), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="content"):
        store.get_chapters(task["id"])
