from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path


class ImportJobError(ValueError):
    pass


class ImportJobNotFound(ImportJobError):
    pass


class ImportJobConflict(ImportJobError):
    pass


_RESULT_NAMES = ("worldview", "system", "characters", "outlines")
_LOCK_REGISTRY: dict[tuple[str, str], threading.RLock] = {}
_LOCK_REGISTRY_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write_bytes(path, payload)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImportJobNotFound(f"Import job data is missing: {path.name}") from exc


class ImportJobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.home() / ".loom" / "imports").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        original_filename: str,
        raw: bytes,
        normalized_text: str,
        encoding: str,
        chapters: list[dict],
        split_confidence: str,
    ) -> dict:
        checked_chapters = self._validate_chapters(chapters)
        task_id = str(uuid.uuid4())
        task_root = self._task_root(task_id)
        timestamp = _now()
        metadata = {
            "id": task_id,
            "original_filename": original_filename,
            "encoding": encoding,
            "split_confidence": split_confidence,
            "status": "reviewing",
            "phase": None,
            "chapter_revision": 1,
            "result_revision": None,
            "selected_chapter_ids": [row["id"] for row in checked_chapters if row["selected"]],
            "progress": {"completed": 0, "total": 0},
            "error": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

        with self.lock(task_id):
            try:
                (task_root / "source").mkdir(parents=True)
                (task_root / "runtime").mkdir()
                (task_root / "checkpoints").mkdir()
                (task_root / "results").mkdir()
                _atomic_write_bytes(task_root / "source" / "original.txt", raw)
                _atomic_write_bytes(
                    task_root / "source" / "normalized.txt",
                    normalized_text.encode("utf-8"),
                )
                template = Path(__file__).parent / "templates" / "loom.toml"
                _atomic_write_bytes(task_root / "runtime" / "loom.toml", template.read_bytes())
                _write_json(task_root / "chapters.json", checked_chapters)
                _write_json(task_root / "task.json", metadata)
            except Exception:
                shutil.rmtree(task_root, ignore_errors=True)
                raise
        return dict(metadata)

    def list(self) -> list[dict]:
        tasks: list[dict] = []
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                task_id = str(uuid.UUID(path.name))
                if task_id != path.name:
                    continue
                tasks.append(self.get(task_id))
            except (ImportJobError, OSError, json.JSONDecodeError):
                continue
        return sorted(tasks, key=lambda task: task.get("updated_at", ""), reverse=True)

    def get(self, task_id: str) -> dict:
        task_root = self._existing_task_root(task_id)
        value = _read_json(task_root / "task.json")
        if not isinstance(value, dict):
            raise ImportJobError("task.json must contain an object")
        return value

    def recover_interrupted(self) -> int:
        recovered = 0
        for task in self.list():
            if task.get("status") != "running":
                continue
            self.update(task["id"], status="interrupted")
            recovered += 1
        return recovered

    def get_chapters(self, task_id: str) -> list[dict]:
        task_root = self._existing_task_root(task_id)
        value = _read_json(task_root / "chapters.json")
        if not isinstance(value, list):
            raise ImportJobError("chapters.json must contain a list")
        return value

    def update(self, task_id: str, **changes: object) -> dict:
        with self.lock(task_id):
            task = self.get(task_id)
            task.update(changes)
            task["updated_at"] = _now()
            _write_json(self._task_root(task_id) / "task.json", task)
            return task

    def save_chapters(self, task_id: str, chapters: list[dict]) -> dict:
        checked_chapters = self._validate_chapters(chapters)
        with self.lock(task_id):
            task = self.get(task_id)
            _write_json(self._task_root(task_id) / "chapters.json", checked_chapters)
            self._clear_directory(self._task_root(task_id) / "checkpoints")
            self._clear_directory(self._task_root(task_id) / "results")
            task.update(
                {
                    "chapter_revision": int(task["chapter_revision"]) + 1,
                    "result_revision": None,
                    "selected_chapter_ids": [
                        row["id"] for row in checked_chapters if row["selected"]
                    ],
                    "status": "ready",
                    "phase": None,
                    "progress": {"completed": 0, "total": 0},
                    "error": None,
                    "updated_at": _now(),
                }
            )
            _write_json(self._task_root(task_id) / "task.json", task)
            return task

    def save_results(self, task_id: str, results: dict[str, str]) -> dict:
        if set(results) != set(_RESULT_NAMES):
            raise ImportJobError(f"Results must contain exactly: {', '.join(_RESULT_NAMES)}")
        if any(not isinstance(results[name], str) for name in _RESULT_NAMES):
            raise ImportJobError("Every result must be text")

        with self.lock(task_id):
            task = self.get(task_id)
            if task.get("status") not in {"running", "completed", "created"}:
                raise ImportJobConflict("Results cannot be saved in the current status")
            result_root = self._task_root(task_id) / "results"
            for name in _RESULT_NAMES:
                _atomic_write_bytes(result_root / f"{name}.md", results[name].encode("utf-8"))
        return dict(results)

    def get_results(self, task_id: str) -> dict[str, str]:
        result_root = self._existing_task_root(task_id) / "results"
        paths = {name: result_root / f"{name}.md" for name in _RESULT_NAMES}
        if not any(path.exists() for path in paths.values()):
            return {}
        if not all(path.is_file() for path in paths.values()):
            raise ImportJobError("Stored results are incomplete")
        return {name: path.read_text(encoding="utf-8") for name, path in paths.items()}

    def delete(self, task_id: str) -> None:
        with self.lock(task_id):
            task = self.get(task_id)
            if task.get("status") == "running":
                raise ImportJobConflict("A running import job cannot be deleted")
            shutil.rmtree(self._task_root(task_id))

    def source_path(self, task_id: str, *, normalized: bool) -> Path:
        task_root = self._existing_task_root(task_id)
        filename = "normalized.txt" if normalized else "original.txt"
        return task_root / "source" / filename

    def runtime_root(self, task_id: str) -> Path:
        return self._existing_task_root(task_id) / "runtime"

    def checkpoint_path(self, task_id: str, phase: str) -> Path:
        if not phase or Path(phase).name != phase or phase in {".", ".."}:
            raise ImportJobError("Invalid checkpoint phase")
        return self._existing_task_root(task_id) / "checkpoints" / f"{phase}.json"

    def lock(self, task_id: str) -> AbstractContextManager[None]:
        self._task_root(task_id)
        key = (str(self.root), task_id)
        with _LOCK_REGISTRY_GUARD:
            return _LOCK_REGISTRY.setdefault(key, threading.RLock())

    def _task_root(self, task_id: str) -> Path:
        try:
            parsed = uuid.UUID(task_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ImportJobError("Invalid import task ID") from exc
        if str(parsed) != task_id:
            raise ImportJobError("Invalid import task ID")
        candidate = (self.root / task_id).resolve()
        if not candidate.is_relative_to(self.root):
            raise ImportJobError("Import task path escapes the store")
        return candidate

    def _existing_task_root(self, task_id: str) -> Path:
        task_root = self._task_root(task_id)
        if not task_root.is_dir():
            raise ImportJobNotFound(f"Import job not found: {task_id}")
        return task_root

    @staticmethod
    def _validate_chapters(chapters: list[dict]) -> list[dict]:
        if not isinstance(chapters, list) or not chapters:
            raise ImportJobError("At least one chapter is required")
        checked = [dict(chapter) for chapter in chapters]
        ids = [chapter.get("id") for chapter in checked]
        orders = [chapter.get("order") for chapter in checked]
        if any(not isinstance(chapter_id, str) or not chapter_id for chapter_id in ids):
            raise ImportJobError("Every chapter needs an ID")
        if len(ids) != len(set(ids)):
            raise ImportJobError("Chapter IDs must be unique")
        if any(not isinstance(order, int) or isinstance(order, bool) for order in orders):
            raise ImportJobError("Chapter order must be an integer")
        if len(orders) != len(set(orders)) or sorted(orders) != list(range(1, len(checked) + 1)):
            raise ImportJobError("Chapter order must be unique and contiguous from 1")
        if any(not isinstance(chapter.get("title"), str) or not chapter["title"].strip() for chapter in checked):
            raise ImportJobError("Every chapter needs a nonempty title")
        if any(not isinstance(chapter.get("selected"), bool) for chapter in checked):
            raise ImportJobError("Every chapter needs a selected flag")
        if not any(chapter["selected"] for chapter in checked):
            raise ImportJobError("At least one chapter must be selected")
        return checked

    @staticmethod
    def _clear_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
