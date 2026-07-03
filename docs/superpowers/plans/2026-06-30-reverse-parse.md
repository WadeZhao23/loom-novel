# Reverse Parse Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resumable TXT novel imports that let users review chapter boundaries, parse selected chapters with AI, edit extracted knowledge, and create a registered Loom project.

**Architecture:** Store every import as an atomic file-backed job under `~/.loom/imports/<task_id>`. Keep text/chapter operations, AI checkpoint orchestration, project materialization, HTTP transport, and web UI in separate units. Reuse the existing backend abstraction, project scaffold/registry, NDJSON conventions, and vanilla web UI patterns.

**Tech Stack:** Python 3.11, FastAPI, `python-multipart`, pytest, existing Loom backend abstraction, vanilla HTML/CSS/JavaScript.

---

## File Structure

- Create `loom/import_jobs.py`: file-backed job repository, atomic byte/JSON writes, task locks, status transitions, chapter/result persistence.
- Create `loom/reverse_parse.py`: TXT decoding, chapter detection/edit helpers, chunking, AI extraction, checkpoint reuse, progress events.
- Create `loom/import_project.py`: materialize validated results into a scaffolded project and register only after validation.
- Create `loom/templates/外置大脑/修炼体系.md`: default power-system knowledge file.
- Modify `loom/server.py`: optional brain-file state, import CRUD, upload, parse stream, result update, and project creation endpoints.
- Modify `pyproject.toml`: add `python-multipart`.
- Modify `loom/webui/index.html`: import entry, history list, and four-step import overlay.
- Modify `loom/webui/app.js`: import state, chapter editing, NDJSON parsing, recovery, result editing, creation, deletion.
- Modify `loom/webui/style.css`: dense import workflow layout and responsive rules.
- Create `tests/test_import_jobs.py`: repository, revisions, path safety, interruption, and locking tests.
- Create `tests/test_reverse_parse.py`: decoding, splitting, editing, and selection tests.
- Create `tests/test_reverse_parse_pipeline.py`: chunking, checkpoints, failures, and resume tests.
- Create `tests/test_import_project.py`: output layout, source modes, registration ordering, and failure tests.
- Create `tests/test_import_api.py`: multipart, CRUD, conflicts, NDJSON, recovery, and project endpoint tests.

---

### Task 1: File-Backed Import Job Repository

**Files:**
- Create: `loom/import_jobs.py`
- Create: `tests/test_import_jobs.py`

- [ ] **Step 1: Write failing repository lifecycle and safety tests**

Create `tests/test_import_jobs.py` with fixtures isolated from the real home directory and these core cases:

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loom.import_jobs import ImportJobStore


@pytest.fixture
def store(tmp_path: Path) -> ImportJobStore:
    return ImportJobStore(tmp_path / "imports")


def sample_chapters() -> list[dict]:
    return [
        {"id": "c1", "order": 1, "title": "第一章", "content": "开端", "selected": True},
        {"id": "c2", "order": 2, "title": "第二章", "content": "发展", "selected": True},
    ]


def test_create_persists_source_metadata_and_chapters(store: ImportJobStore) -> None:
    task = store.create(
        original_filename="book.txt",
        raw=b"book bytes",
        normalized_text="正文",
        encoding="utf-8",
        chapters=sample_chapters(),
        split_confidence="high",
    )

    loaded = store.get(task["id"])
    assert loaded["status"] == "reviewing"
    assert loaded["chapter_revision"] == 1
    assert loaded["result_revision"] is None
    assert store.source_path(task["id"], normalized=False).read_bytes() == b"book bytes"
    assert store.source_path(task["id"], normalized=True).read_text(encoding="utf-8") == "正文"
    assert store.get_chapters(task["id"])[1]["title"] == "第二章"


def test_invalid_task_id_cannot_escape_store(store: ImportJobStore) -> None:
    with pytest.raises(ValueError):
        store.get("../outside")


def test_reading_running_task_marks_it_interrupted(store: ImportJobStore) -> None:
    task = store.create("book.txt", b"x", "x", "utf-8", sample_chapters(), "high")
    store.update(task["id"], status="running", phase="worldview")

    restarted = ImportJobStore(store.root)
    assert restarted.recover_interrupted() == 1
    loaded = restarted.get(task["id"])

    assert loaded["status"] == "interrupted"
    assert loaded["phase"] == "worldview"


def test_chapter_update_invalidates_results(store: ImportJobStore) -> None:
    task = store.create("book.txt", b"x", "x", "utf-8", sample_chapters(), "high")
    store.update(task["id"], status="completed", result_revision=1)

    saved = store.save_chapters(task["id"], sample_chapters())

    assert saved["chapter_revision"] == 2
    assert saved["result_revision"] is None
    assert saved["status"] == "ready"


def test_task_lock_serializes_updates(store: ImportJobStore) -> None:
    task = store.create("book.txt", b"x", "x", "utf-8", sample_chapters(), "high")

    def bump() -> None:
        with store.lock(task["id"]):
            current = store.get(task["id"], recover_running=False)
            store.update(task["id"], progress={"completed": current["progress"]["completed"] + 1, "total": 2})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: bump(), range(2)))

    assert store.get(task["id"])["progress"]["completed"] == 2
```

Also test `list()`, `delete()`, missing task errors, refusal to delete `running`, result writes, and selected-chapter validation.

- [ ] **Step 2: Run the repository tests and verify the import failure**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_import_jobs.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'loom.import_jobs'`.

- [ ] **Step 3: Implement the repository API**

Create `loom/import_jobs.py` with these exception types:

```python
from __future__ import annotations


class ImportJobError(ValueError):
    pass


class ImportJobNotFound(ImportJobError):
    pass


class ImportJobConflict(ImportJobError):
    pass
```

Implement `ImportJobStore` with these exact public signatures:

- `__init__(self, root: Path | None = None) -> None`
- `create(self, original_filename: str, raw: bytes, normalized_text: str, encoding: str, chapters: list[dict], split_confidence: str) -> dict`
- `list(self) -> list[dict]`
- `get(self, task_id: str) -> dict`
- `recover_interrupted(self) -> int`
- `get_chapters(self, task_id: str) -> list[dict]`
- `update(self, task_id: str, **changes: object) -> dict`
- `save_chapters(self, task_id: str, chapters: list[dict]) -> dict`
- `save_results(self, task_id: str, results: dict[str, str]) -> dict`
- `get_results(self, task_id: str) -> dict[str, str]`
- `delete(self, task_id: str) -> None`
- `source_path(self, task_id: str, *, normalized: bool) -> Path`
- `runtime_root(self, task_id: str) -> Path`
- `checkpoint_path(self, task_id: str, phase: str) -> Path`
- `lock(self, task_id: str) -> AbstractContextManager[None]`

Implementation rules:

- Generate task IDs with `uuid.uuid4()` and validate incoming IDs by parsing UUID plus checking resolved containment.
- Use module-level `dict[tuple[str, str], RLock]` keyed by resolved store root and task ID, guarded by one registry lock.
- Implement `_atomic_write_bytes()`, `_write_json()`, and `_read_json()` using same-directory temporary files and `os.replace()`.
- Copy `loom/templates/loom.toml` to `runtime/loom.toml` during creation.
- Validate chapter IDs/order/titles, exactly one row per order, and at least one selected chapter.
- `save_chapters()` increments `chapter_revision`, clears `result_revision`, removes stale checkpoint/result files, and sets `status="ready"`.
- `save_results()` accepts internal writes in `running` plus user edits in `completed` or `created`, writes exactly `worldview`, `system`, `characters`, and `outlines`, and preserves `result_revision`. The HTTP result-edit endpoint separately rejects `running`.
- `recover_interrupted()` changes every persisted `running` task to `interrupted` and returns the number changed; normal `get()` calls never change status.
- `delete()` raises `ImportJobConflict` while status is `running`.

- [ ] **Step 4: Run focused tests and inspect failures**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_import_jobs.py -q
```

Expected: all repository tests pass.

- [ ] **Step 5: Commit the repository**

```powershell
git add loom/import_jobs.py tests/test_import_jobs.py
git commit -m "feat: add persistent import jobs"
```

---

### Task 2: TXT Decoding, Chapter Detection, and Editing

**Files:**
- Create: `loom/reverse_parse.py`
- Create: `tests/test_reverse_parse.py`

- [ ] **Step 1: Write failing decoding and chapter tests**

Create `tests/test_reverse_parse.py` around the public value object and helpers:

```python
from __future__ import annotations

import pytest

from loom.reverse_parse import (
    ChapterSplit,
    decode_txt,
    merge_chapters,
    move_chapter,
    select_chapter_range,
    split_chapter,
    split_chapters,
)


TEXT = "第1章 初见\n甲。\n\n第2章 冲突\n乙。\n"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "gb18030"])
def test_decode_supported_encodings(encoding: str) -> None:
    raw = "第一章\r\n正文".encode(encoding)
    text, detected = decode_txt(raw)
    assert text == "第一章\n正文"
    assert detected in {"utf-8-sig", "utf-8", "gb18030"}


def test_decode_rejects_binary_and_empty_files() -> None:
    with pytest.raises(ValueError, match="空"):
        decode_txt(b"")
    with pytest.raises(ValueError, match="文本"):
        decode_txt(b"\x00\x01\x00\x02")


def test_split_chapters_detects_common_headings() -> None:
    result = split_chapters(TEXT)
    assert isinstance(result, ChapterSplit)
    assert result.confidence == "high"
    assert [chapter["title"] for chapter in result.chapters] == ["第1章 初见", "第2章 冲突"]
    assert all(chapter["selected"] for chapter in result.chapters)


def test_heading_free_text_uses_low_confidence_chunks() -> None:
    result = split_chapters(("第一段内容。\n\n" * 200).strip(), fallback_chars=400)
    assert result.confidence == "low"
    assert len(result.chapters) > 1


def test_split_merge_move_and_select_range() -> None:
    chapters = split_chapters(TEXT).chapters
    split = split_chapter(chapters, chapters[0]["id"], 2)
    merged = merge_chapters(split, split[1]["id"], direction="previous")
    moved = move_chapter(merged, merged[1]["id"], offset=-1)
    selected = select_chapter_range(moved, start=2, end=2)

    assert [chapter["order"] for chapter in selected] == [1, 2]
    assert [chapter["selected"] for chapter in selected] == [False, True]
```

Add cases for `第十二章`, `第12回`, `卷一`, `序章`, `楔子`, `后记`, split offsets outside content, merging first/last chapters, duplicate IDs, empty titles, and invalid ranges.

- [ ] **Step 2: Run the focused tests and verify failure**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_reverse_parse.py -q
```

Expected: import failure for `loom.reverse_parse`.

- [ ] **Step 3: Implement deterministic text and chapter operations**

Create `loom/reverse_parse.py` with these signatures:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterSplit:
    chapters: list[dict]
    confidence: str


```

Implement these exact function signatures:

- `decode_txt(raw: bytes) -> tuple[str, str]`
- `split_chapters(text: str, *, fallback_chars: int = 12_000) -> ChapterSplit`
- `validate_chapters(chapters: list[dict]) -> None`
- `split_chapter(chapters: list[dict], chapter_id: str, offset: int) -> list[dict]`
- `merge_chapters(chapters: list[dict], chapter_id: str, *, direction: str) -> list[dict]`
- `move_chapter(chapters: list[dict], chapter_id: str, *, offset: int) -> list[dict]`
- `select_chapter_range(chapters: list[dict], *, start: int, end: int) -> list[dict]`



Use strict decoding in this order: `utf-8-sig`, `utf-8`, `gb18030`. Normalize CRLF/CR to LF. Reject empty decoded text and raw data whose NUL ratio exceeds 1%. Match chapter headings only at line starts. Preserve preface text as a `序章` chapter when it contains non-whitespace content. Generate stable new UUIDs only for newly split/fallback chapters, then renumber all `order` fields after every operation.

- [ ] **Step 4: Run decoding and chapter tests**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_reverse_parse.py tests\test_import_jobs.py -q
```

Expected: all tests in both files pass.

- [ ] **Step 5: Commit deterministic parsing**

```powershell
git add loom/reverse_parse.py tests/test_reverse_parse.py
git commit -m "feat: split and edit imported chapters"
```

---

### Task 3: AI Pipeline, Checkpoints, and Resume

**Files:**
- Modify: `loom/reverse_parse.py`
- Create: `tests/test_reverse_parse_pipeline.py`

- [ ] **Step 1: Write failing pipeline and checkpoint tests**

Create `tests/test_reverse_parse_pipeline.py` using `FakeBackend` and a real temporary `ImportJobStore`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from loom.import_jobs import ImportJobStore
from loom.reverse_parse import chunk_chapters, run_parse
from tests.conftest import FakeBackend


def make_task(store: ImportJobStore) -> str:
    chapters = [
        {"id": "c1", "order": 1, "title": "第一章", "content": "甲" * 40, "selected": True},
        {"id": "c2", "order": 2, "title": "第二章", "content": "乙" * 40, "selected": True},
    ]
    return store.create("book.txt", b"x", "x", "utf-8", chapters, "high")["id"]


def test_chunk_chapters_honors_budget() -> None:
    chunks = chunk_chapters(
        [
            {"id": "c1", "order": 1, "title": "一", "content": "甲" * 10, "selected": True},
            {"id": "c2", "order": 2, "title": "二", "content": "乙" * 10, "selected": True},
        ],
        char_budget=15,
    )
    assert [len(chunk) for chunk in chunks] == [1, 1]


def test_pipeline_emits_ordered_phases_and_persists_results(tmp_path: Path) -> None:
    store = ImportJobStore(tmp_path / "imports")
    task_id = make_task(store)
    events: list[dict] = []
    backend = FakeBackend(lambda system, user: f"结果:{user[:16]}")

    result = run_parse(store, task_id, backend, progress=events.append, char_budget=60)

    assert result["status"] == "completed"
    assert [event["phase"] for event in events if event["type"] == "phase"] == [
        "worldview", "system", "characters", "outlines"
    ]
    assert set(store.get_results(task_id)) == {"worldview", "system", "characters", "outlines"}
    assert store.get(task_id)["result_revision"] == store.get(task_id)["chapter_revision"]


def test_resume_reuses_matching_checkpoint(tmp_path: Path) -> None:
    store = ImportJobStore(tmp_path / "imports")
    task_id = make_task(store)
    calls = 0

    def flaky(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("network down")
        return "ok"

    with pytest.raises(RuntimeError, match="network down"):
        run_parse(store, task_id, FakeBackend(flaky), char_budget=60)
    calls_after_failure = calls

    run_parse(store, task_id, FakeBackend(lambda system, user: "ok"), char_budget=60)

    assert calls_after_failure > 0
    assert store.get(task_id)["status"] == "completed"
    assert store.checkpoint_path(task_id, "worldview").exists()
```

Add tests for: only selected chapters are sent, checkpoint input hashes reject stale data, a second caller gets `ImportJobConflict`, errors persist `phase/message`, and progress totals remain deterministic.

- [ ] **Step 2: Run pipeline tests and verify missing functions**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_reverse_parse_pipeline.py -q
```

Expected: import failure for `chunk_chapters` or `run_parse`.

- [ ] **Step 3: Implement the checkpointed pipeline**

Extend `loom/reverse_parse.py` with:

```python
from collections.abc import Callable

from .backends import Backend
from .import_jobs import ImportJobConflict, ImportJobStore

Progress = Callable[[dict], None]
PHASES = ("worldview", "system", "characters", "outlines")


```

Implement `chunk_chapters(chapters: list[dict], *, char_budget: int = 12_000) -> list[list[dict]]` and `run_parse(store: ImportJobStore, task_id: str, backend: Backend, *, progress: Progress | None = None, char_budget: int = 12_000) -> dict` with the rules below.

Implement these exact rules:

- Acquire `store.lock(task_id)` only for status checks/updates and checkpoint commits, not during network calls. Read status with `store.get(task_id)`; recovery is never invoked from a worker.
- Accept `ready`, `failed`, or `interrupted`; reject `running`, `reviewing`, stale completed results, and empty selection.
- Set `running` before the first backend call and persist `phase` before each phase.
- Build SHA-256 hashes from phase name, chapter revision, selected IDs, and exact chunk text.
- Store checkpoint JSON as `{phase, revision, chunks: [{index, input_hash, output}], merged}`.
- Reuse a chunk only when phase, revision, index, and hash all match.
- Use focused Chinese system prompts with JSON-free Markdown output. For worldview/system/characters, extract each chunk then merge outputs in bounded batches. For outlines, call once per chapter and join under `## <title>` headings.
- Emit `phase`, `progress`, `phase_done`, and final `complete` events. On exception, persist `failed`, phase, and `error={"message": str(exc)}`, emit `error`, then re-raise.
- Write all four final Markdown files before setting `result_revision=chapter_revision` and `status="completed"`.

- [ ] **Step 4: Run pipeline and regression tests**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_reverse_parse_pipeline.py tests\test_reverse_parse.py tests\test_import_jobs.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the AI pipeline**

```powershell
git add loom/reverse_parse.py tests/test_reverse_parse_pipeline.py
git commit -m "feat: add resumable reverse parse pipeline"
```

---

### Task 4: Project Materialization and Optional Source Chapters

**Files:**
- Create: `loom/import_project.py`
- Create: `loom/templates/外置大脑/修炼体系.md`
- Create: `tests/test_import_project.py`
- Modify: `loom/server.py:67-91`

- [ ] **Step 1: Write failing project materialization tests**

Create `tests/test_import_project.py` with dependency injection for validation and registration:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from loom.import_jobs import ImportJobStore
from loom.import_project import materialize_import


def completed_task(store: ImportJobStore) -> str:
    chapters = [
        {"id": "c1", "order": 1, "title": "第一章:开始", "content": "正文一", "selected": True},
        {"id": "c2", "order": 2, "title": "第二章", "content": "正文二", "selected": True},
    ]
    task = store.create("book.txt", b"x", "x", "utf-8", chapters, "high")
    store.update(task["id"], status="completed", result_revision=1)
    store.save_results(task["id"], {
        "worldview": "世界观结果",
        "system": "体系结果",
        "characters": "人物结果",
        "outlines": "章纲结果",
    })
    return task["id"]


def test_materialize_writes_results_and_optional_source(tmp_path: Path) -> None:
    store = ImportJobStore(tmp_path / "imports")
    task_id = completed_task(store)
    registered: list[Path] = []

    state = materialize_import(
        store,
        task_id,
        name="导入书",
        parent_dir=tmp_path / "projects",
        genre=None,
        include_source_chapters=True,
        state_loader=lambda root: {"root": str(root)},
        register=lambda root: registered.append(root) or {"path": str(root)},
    )

    root = Path(state["root"])
    assert (root / "外置大脑" / "世界观.md").read_text(encoding="utf-8") == "世界观结果\n"
    assert (root / "外置大脑" / "修炼体系.md").read_text(encoding="utf-8") == "体系结果\n"
    assert (root / "正文" / ".原稿" / "0001-第一章-开始.md").exists()
    assert registered == [root]


def test_materialize_can_skip_source_chapters(tmp_path: Path) -> None:
    store = ImportJobStore(tmp_path / "imports")
    task_id = completed_task(store)
    state = materialize_import(
        store, task_id, name="只要设定", parent_dir=tmp_path,
        genre=None, include_source_chapters=False,
        state_loader=lambda root: {"root": str(root)}, register=lambda root: {},
    )
    assert list((Path(state["root"]) / "正文" / ".原稿").glob("*.md")) == []


def test_validation_failure_never_registers(tmp_path: Path) -> None:
    store = ImportJobStore(tmp_path / "imports")
    task_id = completed_task(store)
    registered: list[Path] = []
    with pytest.raises(ValueError, match="invalid project"):
        materialize_import(
            store, task_id, name="失败项目", parent_dir=tmp_path,
            genre=None, include_source_chapters=False,
            state_loader=lambda root: (_ for _ in ()).throw(ValueError("invalid project")),
            register=lambda root: registered.append(root),
        )
    assert registered == []
```

Add tests for existing destination conflict, stale results, missing result file, safe filename replacement, and repeated creation from one task.

- [ ] **Step 2: Run materialization tests and verify failure**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_import_project.py -q
```

Expected: import failure for `loom.import_project`.

- [ ] **Step 3: Implement project materialization and template**

Create `loom/import_project.py` with:

Implement these exact signatures in `loom/import_project.py`:

- `safe_chapter_filename(order: int, title: str) -> str`
- `materialize_import(store: ImportJobStore, task_id: str, *, name: str, parent_dir: Path, genre: str | None, include_source_chapters: bool, state_loader: Callable[[Path], dict], register: Callable[[Path], dict]) -> dict`

Implementation order is mandatory: lock and validate task/revision/results, reject existing destination, call `scaffold.init`, atomically write four brain files, optionally write selected source chapters, call `state_loader`, call `register`, then mark task `created`. Never call `register` before `state_loader` succeeds. Preserve a failed destination and include its path in the raised error.

Create `loom/templates/外置大脑/修炼体系.md` containing a short neutral Markdown structure with headings for levels, resources, advancement, limits, and costs. Do not add it to `doctor.BRAIN_FILES`, because existing projects must remain valid.

Update `_state()` in `loom/server.py` so its `brains` list appends `修炼体系` only when `外置大脑/修炼体系.md` exists:

```python
brain_names = list(BRAIN_FILES)
if (root / "外置大脑" / "修炼体系.md").is_file():
    brain_names.append("修炼体系")
brains = [{"name": n, "path": f"外置大脑/{n}.md"} for n in brain_names]
```

- [ ] **Step 4: Run project and existing registry tests**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_import_project.py tests\test_project_registry.py -q
```

Expected: all tests pass and existing-project tests still see the original required brain files.

- [ ] **Step 5: Commit project materialization**

```powershell
git add loom/import_project.py loom/templates/外置大脑/修炼体系.md loom/server.py tests/test_import_project.py
git commit -m "feat: create projects from import results"
```

---

### Task 5: Import HTTP API and Background Parse Stream

**Files:**
- Modify: `pyproject.toml:9-17`
- Modify: `loom/server.py:13-16,593`
- Create: `tests/test_import_api.py`

- [ ] **Step 1: Add multipart dependency and install the editable project**

Add this dependency beside FastAPI in `pyproject.toml`:

```toml
"python-multipart>=0.0.9",
```

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pip install -e .
```

Expected: editable install succeeds and `python-multipart` is importable.

- [ ] **Step 2: Write failing API contract tests**

Create `tests/test_import_api.py` with isolated `Path.home`, patched backend, and local `TestClient`:

```python
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import loom.config
import loom.import_jobs
import loom.server as server
from tests.conftest import FakeBackend


def frames(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(loom.config.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(loom.import_jobs.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(server, "get_backend", lambda config: FakeBackend(lambda system, user: "结果"))
    with TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False) as value:
        yield value


def upload(client: TestClient) -> dict:
    response = client.post(
        "/api/imports",
        files={"file": ("book.txt", "第1章 开始\n正文".encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()


def test_upload_list_get_and_delete(client: TestClient) -> None:
    task = upload(client)
    assert client.get("/api/imports").json()[0]["id"] == task["id"]
    assert client.get(f"/api/imports/{task['id']}").status_code == 200
    assert client.delete(f"/api/imports/{task['id']}").status_code == 204


def test_parse_returns_ndjson_and_persists_results(client: TestClient) -> None:
    task = upload(client)
    chapters = client.get(f"/api/imports/{task['id']}").json()["chapters"]
    assert client.put(f"/api/imports/{task['id']}/chapters", json={"chapters": chapters}).status_code == 200

    response = client.post(f"/api/imports/{task['id']}/parse")

    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert frames(response)[-1]["type"] == "complete"
    assert client.get(f"/api/imports/{task['id']}").json()["status"] == "completed"
```

Add tests for 50 MiB enforcement using a patched small limit, non-TXT rejection, invalid encoding, missing IDs, invalid chapter payloads, duplicate parse conflict, running delete/edit/create conflicts, saved result edits, stream error frames, restart recovery, existing destination 409, and successful create-project response.

- [ ] **Step 3: Run API tests and verify missing routes**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_import_api.py -q
```

Expected: upload returns 404 before routes are implemented.

- [ ] **Step 4: Implement API models, helpers, and routes before static mounting**

Add FastAPI imports for `File`, `UploadFile`, and keep `StreamingResponse`. Add these models:

```python
class ImportChaptersBody(BaseModel):
    chapters: list[dict]


class ImportResultsBody(BaseModel):
    worldview: str
    system: str
    characters: str
    outlines: str


class ImportCreateBody(BaseModel):
    name: str
    parent_dir: str
    genre: str | None = None
    include_source_chapters: bool = True
```

Add helpers and routes:

Add `MAX_IMPORT_BYTES = 50 * 1024 * 1024`, `_import_store() -> ImportJobStore`, and a FastAPI startup handler that calls `_import_store().recover_interrupted()` exactly once per process. Then implement these exact route signatures before the static mount:

- `create_import(file: UploadFile = File(...)) -> dict`
- `list_imports() -> list[dict]`
- `get_import(task_id: str) -> dict`
- `put_import_chapters(task_id: str, body: ImportChaptersBody) -> dict`
- `parse_import(task_id: str) -> StreamingResponse`
- `put_import_results(task_id: str, body: ImportResultsBody) -> dict`
- `create_import_project(task_id: str, body: ImportCreateBody) -> dict`
- `delete_import(task_id: str) -> Response`

Upload in 1 MiB chunks and reject once the accumulated bytes exceed `MAX_IMPORT_BYTES`. Require `.txt`; do not trust the MIME type alone. Call `decode_txt` and `split_chapters` before `store.create`.

For parsing, validate configuration and construct the backend from `load_config(store.runtime_root(task_id))` before starting the response, mapping configuration failures to 400. Then create an unbounded `queue.Queue`, start a daemon thread, and return a generator that drains JSON frames. The thread passes the queue callback to `run_parse`; `run_parse` alone persists and emits pipeline error frames, while the thread catches the re-raised exception only to reach its `finally` block and write a `None` sentinel. Because task state/checkpoints are persisted independently of the queue, client disconnect does not cancel work.

Map `ImportJobNotFound` to 404, `ImportJobConflict` and existing destinations to 409, validation errors to 400, and unexpected create failures to 500 with an `error` string and optional `path` string. Keep all routes above `app.mount("/", StaticFiles(directory=str(WEBUI_DIR), html=True), name="ui")`.

- [ ] **Step 5: Run API, service, and registry tests**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_import_api.py tests\test_import_project.py tests\test_reverse_parse_pipeline.py tests\test_project_registry.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the API**

```powershell
git add pyproject.toml loom/server.py tests/test_import_api.py
git commit -m "feat: expose resumable import api"
```

---

### Task 6: Four-Step Import Web UI

**Files:**
- Modify: `loom/webui/index.html:12-68,318`
- Modify: `loom/webui/app.js:3-14,93-116,243-286,1158-1180,1524`
- Modify: `loom/webui/style.css:180,522,682`

- [ ] **Step 1: Add stable HTML structure for entry, history, and overlay**

Add an icon button with label “导入小说” near the welcome-page create/open commands, an unframed `#import-history` list, and one `#import-overlay` after existing workflow overlays. The overlay must contain these stable IDs:

```html
<section id="import-overlay" class="overlay hidden" aria-label="导入小说">
  <div class="run-card import-workflow">
    <header class="import-head">
      <h2 id="import-title">导入小说</h2>
      <button id="import-close" class="icon-btn" title="关闭" aria-label="关闭">×</button>
    </header>
    <nav id="import-steps" class="segmented" aria-label="导入步骤">
      <button data-step="upload">上传</button>
      <button data-step="chapters">章节</button>
      <button data-step="parse">解析</button>
      <button data-step="results">结果</button>
    </nav>
    <section id="import-step-upload" class="import-step"></section>
    <section id="import-step-chapters" class="import-step hidden"></section>
    <section id="import-step-parse" class="import-step hidden"></section>
    <section id="import-step-results" class="import-step hidden"></section>
  </div>
</section>
```

Populate the upload step with a `.txt` file input and drop target; the chapter step with range inputs, per-row checkboxes, and a table body whose active row expands to a chapter-content textarea; the parse step with four phase rows and a progress element; and the results step with four tabs/textareas plus project name, parent directory, genre, and a two-option segmented source mode. The split command uses the active textarea's `selectionStart` as its exact offset. Use existing button/icon classes and no nested cards.

- [ ] **Step 2: Add import state and transport helpers**

At the top of `app.js`, define:

```javascript
let IMPORTS = [];
let IMPORT_TASK = null;
let IMPORT_CHAPTERS = [];

async function importRequest(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `请求失败 (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function readNdjson(response, onEvent) {
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    if (done) break;
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}
```

Call `loadImports()` from the existing startup path and bind all import controls from the existing event-binding section.

- [ ] **Step 3: Implement task history, upload, and chapter editing**

Add these functions with direct DOM rendering and no `innerHTML` interpolation of user content:

Add `loadImports`, `renderImportHistory`, `uploadNovel`, `openImport`, `showImportStep`, `renderImportChapters`, `splitImportChapter`, `mergeImportChapter`, `moveImportChapter`, `selectImportRange`, and `saveImportChapters`.

`uploadNovel` sends `FormData` without setting `Content-Type`. Chapter operations edit the in-memory array, always renumber rows, and require `saveImportChapters()` before parsing. Render user titles/content through `textContent` or form `.value` only.

- [ ] **Step 4: Implement parsing, recovery, result edits, creation, and deletion**

Add:

Add `runImportParse`, `applyImportEvent`, `renderImportResults`, `saveImportResults`, `createImportedProject`, and `deleteImportTask`.

`runImportParse()` disables chapter controls, calls `/api/imports/{id}/parse`, feeds `readNdjson`, and reloads the task in `finally`. `openImport()` chooses the correct step from status: `reviewing/ready` → chapters, `running/interrupted/failed` → parse, `completed/created` → results. Poll a running task every two seconds while the overlay is open. On project creation, call existing `enterProject(state)`. Require a confirmation dialog before deletion.

- [ ] **Step 5: Add responsive, work-focused styling**

Add CSS with fixed layout tracks so dynamic content does not resize controls:

```css
.import-workflow { width: min(1080px, calc(100vw - 32px)); height: min(760px, calc(100vh - 32px)); }
.import-head { display: flex; align-items: center; justify-content: space-between; }
.import-step { min-height: 0; overflow: auto; }
.import-chapter-table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.import-chapter-title { width: 100%; min-width: 0; }
.import-results { display: grid; grid-template-columns: 160px minmax(0, 1fr); min-height: 0; }
.import-results textarea { width: 100%; min-height: 320px; resize: vertical; }

@media (max-width: 720px) {
  .import-workflow { width: 100vw; height: 100vh; }
  .import-results { grid-template-columns: 1fr; }
  .import-chapter-actions { display: grid; grid-template-columns: repeat(2, 36px); }
}
```

Use the existing neutral palette plus status colors already present in the stylesheet. Keep card radii at the existing system value and ensure no card is nested inside another card.

- [ ] **Step 6: Run static checks**

```powershell
node --check loom\webui\app.js
& '..\..\.venv\Scripts\python.exe' -m compileall loom tests
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit the web UI**

```powershell
git add loom/webui/index.html loom/webui/app.js loom/webui/style.css
git commit -m "feat: add novel import workflow"
```

---

### Task 7: End-to-End Recovery, Browser Verification, and Final Review

**Files:**
- Modify only if a verification exposes a defect in files owned by Tasks 1-6.

- [ ] **Step 1: Run the full Python suite**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q
```

Expected: all tests pass with only the existing Starlette/httpx deprecation warning.

- [ ] **Step 2: Run compile, JavaScript, and whitespace checks**

```powershell
& '..\..\.venv\Scripts\python.exe' -m compileall loom tests
node --check loom\webui\app.js
git diff --check main..HEAD
```

Expected: all commands exit 0 with no output from `git diff --check`.

- [ ] **Step 3: Start the local app from this worktree**

```powershell
& '..\..\.venv\Scripts\python.exe' -m uvicorn loom.server:app --host 127.0.0.1 --port 8766
```

Expected: the app responds at `http://127.0.0.1:8766/`.

- [ ] **Step 4: Verify the complete browser workflow**

Use the in-app browser at desktop and narrow viewports to verify:

1. Upload a UTF-8 TXT and inspect detected chapters before any AI call.
2. Rename, split, merge, reorder, and select a chapter range.
3. Start parsing, refresh during parsing, reopen the task, and observe persisted progress.
4. Run `pytest tests/test_reverse_parse_pipeline.py::test_resume_reuses_matching_checkpoint -q` and confirm completed checkpoints are not repeated after a backend failure.
5. Edit each result tab and create one project with source chapters.
6. Create another project from the same task without source chapters.
7. Confirm both projects open, the first has sanitized original chapter files, and the second does not.
8. Delete the task only after confirmation.
9. Check that no text, buttons, table cells, or overlays overlap at 1280x800 and 390x844.

- [ ] **Step 5: Request spec compliance and code quality reviews**

Dispatch a fresh spec reviewer against `docs/superpowers/specs/2026-06-30-reverse-parse-design.md`, then a separate code quality reviewer after every spec issue is fixed. Re-run the focused tests for any touched area and repeat each review until approved.

- [ ] **Step 6: Commit verification fixes only if needed**

If review or browser verification required code changes, stage only those changes and commit:

```powershell
git add loom tests pyproject.toml
git commit -m "fix: harden reverse parse imports"
```

If no files changed, do not create an empty commit.

- [ ] **Step 7: Re-run final gates and confirm a clean worktree**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q
& '..\..\.venv\Scripts\python.exe' -m compileall loom tests
node --check loom\webui\app.js
git diff --check main..HEAD
git status --short
```

Expected: tests pass, static checks exit 0, diff check is empty, and `git status --short` is empty.
