from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

import pytest

from loom import import_project, scaffold, server
from loom.doctor import BRAIN_FILES
from loom.import_jobs import ImportJobStore
from loom.import_project import materialize_import, safe_chapter_filename


@pytest.fixture
def store(tmp_path: Path) -> ImportJobStore:
    return ImportJobStore(tmp_path / "imports")


def create_completed_task(store: ImportJobStore, filename: str = "book.txt") -> str:
    chapters = [
        {
            "id": "c1",
            "order": 1,
            "title": "第一章:开始",
            "content": "正文一",
            "selected": True,
        },
        {
            "id": "c2",
            "order": 2,
            "title": "第二章",
            "content": "正文二",
            "selected": True,
        },
    ]
    task = store.create(filename, b"x", "x", "utf-8", chapters, "high")
    store.update(task["id"], status="completed", result_revision=1)
    store.save_results(
        task["id"],
        {
            "worldview": "世界观结果",
            "system": "体系结果",
            "characters": "人物结果",
            "outlines": "章纲结果",
        },
    )
    return task["id"]


@pytest.fixture
def completed_task(store: ImportJobStore) -> str:
    return create_completed_task(store)


def materialize(
    store: ImportJobStore,
    task_id: str,
    parent_dir: Path,
    *,
    name: str = "导入书",
    include_source_chapters: bool = False,
    state_loader=lambda root: {"root": str(root)},
    register=lambda root: {},
) -> dict:
    return materialize_import(
        store,
        task_id,
        name=name,
        parent_dir=parent_dir,
        genre=None,
        include_source_chapters=include_source_chapters,
        state_loader=state_loader,
        register=register,
    )


def test_materialize_writes_four_result_brain_files(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    state = materialize(store, completed_task, tmp_path)
    root = Path(state["root"])

    assert {
        path.name: path.read_text(encoding="utf-8")
        for path in (root / "外置大脑").glob("*.md")
        if path.name in {"世界观.md", "修炼体系.md", "人物卡.md", "卡章纲.md"}
    } == {
        "世界观.md": "世界观结果\n",
        "修炼体系.md": "体系结果\n",
        "人物卡.md": "人物结果\n",
        "卡章纲.md": "章纲结果\n",
    }
    assert store.get(completed_task)["status"] == "created"


def test_materialize_writes_only_selected_source_chapters(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    chapters = store.get_chapters(completed_task)
    chapters[1]["selected"] = False
    store.save_chapters(completed_task, chapters)
    store.update(completed_task, status="completed", result_revision=2)
    store.save_results(
        completed_task,
        {"worldview": "w", "system": "s", "characters": "c", "outlines": "o"},
    )

    state = materialize(
        store, completed_task, tmp_path, include_source_chapters=True
    )
    source_dir = Path(state["root"]) / "正文" / ".原稿"

    assert [path.name for path in source_dir.glob("*.md")] == [
        "0001-第一章-开始.md"
    ]
    assert (source_dir / "0001-第一章-开始.md").read_text(
        encoding="utf-8"
    ) == "# 第一章:开始\n\n正文一\n"


def test_materialize_can_skip_source_chapters(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    state = materialize(store, completed_task, tmp_path)

    assert list((Path(state["root"]) / "正文" / ".原稿").glob("*.md")) == []


def test_validation_failure_never_registers_and_preserves_destination(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    registered: list[Path] = []
    destination = tmp_path / "失败项目"
    original = ValueError("invalid project")

    with pytest.raises(ValueError, match="invalid project") as exc_info:
        materialize(
            store,
            completed_task,
            tmp_path,
            name=destination.name,
            state_loader=lambda root: (_ for _ in ()).throw(original),
            register=lambda root: registered.append(root),
        )

    assert registered == []
    assert destination.is_dir()
    assert str(destination) in str(exc_info.value)
    assert exc_info.value.__cause__ is original
    assert store.get(completed_task)["status"] == "completed"


def test_unicode_decode_validation_error_is_wrapped_without_reconstruction(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    destination = tmp_path / "解码失败"
    original = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")

    with pytest.raises(ValueError) as exc_info:
        materialize(
            store,
            completed_task,
            tmp_path,
            name=destination.name,
            state_loader=lambda root: (_ for _ in ()).throw(original),
        )

    assert type(exc_info.value) is ValueError
    assert exc_info.value.__cause__ is original
    assert str(destination) in str(exc_info.value)
    assert destination.is_dir()


def test_materialize_rejects_existing_destination(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    destination = tmp_path / "已存在"
    destination.mkdir()

    with pytest.raises(FileExistsError, match="已存在"):
        materialize(store, completed_task, tmp_path, name=destination.name)

    assert list(destination.iterdir()) == []
    assert store.get(completed_task)["status"] == "completed"


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "whitespace",
        "dot",
        "dotdot",
        "separator",
        "backslash",
        "traversal",
        "absolute",
    ],
)
def test_materialize_rejects_invalid_project_names_without_creating_paths(
    case: str, tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    escaped = tmp_path.parent / f"{tmp_path.name}-{case}-escape"
    names = {
        "empty": "",
        "whitespace": "   ",
        "dot": ".",
        "dotdot": "..",
        "separator": "nested/project",
        "backslash": "nested\\project",
        "traversal": f"../{escaped.name}",
        "absolute": str(escaped.resolve()),
    }
    before = set(tmp_path.iterdir())

    with pytest.raises(ValueError, match="name|component|path"):
        materialize(store, completed_task, tmp_path, name=names[case])

    assert set(tmp_path.iterdir()) == before
    assert not escaped.exists()


def test_destination_reservation_allows_only_one_task_to_own_path(
    tmp_path: Path,
    store: ImportJobStore,
    completed_task: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other_task = create_completed_task(store, "other.txt")
    destination = tmp_path / "争用项目"
    first_entered_scaffold = Event()
    release_first = Event()
    call_lock = Lock()
    call_count = 0
    real_init = scaffold.init

    def controlled_init(name: str, parent: Path, genre: str | None) -> Path:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_entered_scaffold.set()
            assert release_first.wait(5)
        return real_init(name, parent, genre)

    monkeypatch.setattr(import_project.scaffold, "init", controlled_init)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            materialize, store, completed_task, tmp_path, name=destination.name
        )
        assert first_entered_scaffold.wait(5)
        try:
            with pytest.raises(FileExistsError):
                materialize(store, other_task, tmp_path, name=destination.name)
        finally:
            release_first.set()
        first_state = first.result(timeout=5)

    assert Path(first_state["root"]) == destination
    assert call_count == 1
    assert store.get(completed_task)["status"] == "created"
    assert store.get(other_task)["status"] == "completed"


def test_materialize_rejects_stale_results(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    store.update(completed_task, chapter_revision=2)

    with pytest.raises(ValueError, match="stale|revision"):
        materialize(store, completed_task, tmp_path)

    assert not (tmp_path / "导入书").exists()


def test_materialize_rejects_missing_result_file(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    (store.root / completed_task / "results" / "system.md").unlink()

    with pytest.raises(ValueError, match="incomplete|missing"):
        materialize(store, completed_task, tmp_path)

    assert not (tmp_path / "导入书").exists()


@pytest.mark.parametrize(
    ("order", "title", "expected"),
    [
        (1, "第一章:开始", "0001-第一章-开始.md"),
        (12, 'bad<>:"/\\|?* name. ', "0012-bad--------- name.md"),
    ],
)
def test_safe_chapter_filename_replaces_unsafe_characters(
    order: int, title: str, expected: str
) -> None:
    assert safe_chapter_filename(order, title) == expected


def test_safe_chapter_filename_bounds_long_titles() -> None:
    filename = safe_chapter_filename(7, "章" * 500)

    assert len(filename.encode("utf-8")) <= 120
    assert filename.startswith("0007-")
    assert filename.endswith(".md")


def test_completed_task_can_create_multiple_projects(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    materialize(store, completed_task, tmp_path, name="第一次")
    materialize(store, completed_task, tmp_path, name="第二次")

    assert (tmp_path / "第一次").is_dir()
    assert (tmp_path / "第二次").is_dir()
    assert store.get(completed_task)["status"] == "created"


@pytest.mark.parametrize("initial_status", ["completed", "created"])
def test_registration_failure_preserves_project_task_status_and_cause(
    initial_status: str,
    tmp_path: Path,
    store: ImportJobStore,
    completed_task: str,
) -> None:
    store.update(completed_task, status=initial_status)
    destination = tmp_path / f"注册失败-{initial_status}"
    original = LookupError("registry unavailable")

    with pytest.raises(RuntimeError, match="registry unavailable") as exc_info:
        materialize(
            store,
            completed_task,
            tmp_path,
            name=destination.name,
            register=lambda root: (_ for _ in ()).throw(original),
        )

    assert destination.is_dir()
    assert str(destination) in str(exc_info.value)
    assert exc_info.value.__cause__ is original
    assert store.get(completed_task)["status"] == initial_status


def test_server_state_lists_system_brain_only_when_file_exists(tmp_path: Path) -> None:
    root = scaffold.init("状态项目", tmp_path)
    system_file = root / "外置大脑" / "修炼体系.md"
    system_file.unlink()

    without_system = {brain["name"] for brain in server._state(root)["brain"]}
    system_file.write_text("# 修炼体系\n", encoding="utf-8")
    with_system = {brain["name"] for brain in server._state(root)["brain"]}

    assert "修炼体系" not in BRAIN_FILES
    assert "修炼体系" not in without_system
    assert "修炼体系" in with_system
