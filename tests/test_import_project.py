from __future__ import annotations

from pathlib import Path

import pytest

from loom.import_jobs import ImportJobStore
from loom.import_project import materialize_import, safe_chapter_filename


@pytest.fixture
def store(tmp_path: Path) -> ImportJobStore:
    return ImportJobStore(tmp_path / "imports")


@pytest.fixture
def completed_task(store: ImportJobStore) -> str:
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
    task = store.create("book.txt", b"x", "x", "utf-8", chapters, "high")
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

    with pytest.raises(ValueError, match="invalid project") as exc_info:
        materialize(
            store,
            completed_task,
            tmp_path,
            name=destination.name,
            state_loader=lambda root: (_ for _ in ()).throw(
                ValueError("invalid project")
            ),
            register=lambda root: registered.append(root),
        )

    assert registered == []
    assert destination.is_dir()
    assert str(destination) in str(exc_info.value)
    assert store.get(completed_task)["status"] == "completed"


def test_materialize_rejects_existing_destination(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    destination = tmp_path / "已存在"
    destination.mkdir()

    with pytest.raises(FileExistsError, match="已存在"):
        materialize(store, completed_task, tmp_path, name=destination.name)

    assert list(destination.iterdir()) == []
    assert store.get(completed_task)["status"] == "completed"


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


def test_completed_task_can_only_create_one_project(
    tmp_path: Path, store: ImportJobStore, completed_task: str
) -> None:
    materialize(store, completed_task, tmp_path, name="第一次")

    with pytest.raises(ValueError, match="created|status"):
        materialize(store, completed_task, tmp_path, name="第二次")

    assert (tmp_path / "第一次").is_dir()
    assert not (tmp_path / "第二次").exists()
