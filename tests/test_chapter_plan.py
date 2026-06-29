from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from conftest import FakeBackend
from loom.chapter_plan import card_outline_path, outline_path, plan_chapters


def outline_text(chapter: int) -> str:
    return f"第{chapter}章：目标、冲突、反转、章末钩子都清楚。"


def backend_for_chapters() -> FakeBackend:
    def respond(system: str, user: str) -> str:
        match = re.search(r"当前任务：为第\s*(\d+)\s*章", user)
        if match:
            return outline_text(int(match.group(1)))
        return "第X章：备用细纲。"

    return FakeBackend(respond)


def test_plan_chapters_writes_each_outline_and_emits_events(project: Path) -> None:
    events: list[dict] = []

    result = plan_chapters(project, total=3, backend=backend_for_chapters(), progress=events.append)

    assert result == {"planned": 3, "skipped": 0, "chapters": [1, 2, 3]}
    assert outline_path(project, 1).read_text(encoding="utf-8").strip() == outline_text(1)
    assert outline_path(project, 2).read_text(encoding="utf-8").strip() == outline_text(2)
    assert outline_path(project, 3).read_text(encoding="utf-8").strip() == outline_text(3)
    assert [e["type"] for e in events] == [
        "progress",
        "done",
        "progress",
        "done",
        "progress",
        "done",
        "complete",
    ]
    assert events[-1] == {"type": "complete", "planned": 3, "skipped": 0}


def test_plan_chapters_starts_from_requested_chapter(project: Path) -> None:
    events: list[dict] = []

    result = plan_chapters(
        project,
        total=5,
        start_from=3,
        backend=backend_for_chapters(),
        progress=events.append,
    )

    assert result["chapters"] == [3, 4, 5]
    assert not outline_path(project, 2).exists()
    assert outline_path(project, 3).read_text(encoding="utf-8").strip() == outline_text(3)
    assert [e["chapter"] for e in events if e["type"] == "done"] == [3, 4, 5]


def test_plan_chapters_includes_selected_genre_context_in_prompt(project: Path) -> None:
    genre_dir = project / "skills" / "题材"
    genre_dir.mkdir(parents=True, exist_ok=True)
    (genre_dir / "修仙.md").write_text("修仙题材规则：灵根、宗门、境界推进。\n", encoding="utf-8")
    (genre_dir / "README.md").write_text("README 不应进入规划提示词。\n", encoding="utf-8")
    backend = backend_for_chapters()

    plan_chapters(project, total=1, backend=backend)

    user_prompt = backend.calls[0][1]
    assert "修仙题材规则：灵根、宗门、境界推进。" in user_prompt
    assert "README 不应进入规划提示词。" not in user_prompt


def test_prompt_preserves_original_chapter_phrasing_from_context(project: Path) -> None:
    (project / "外置大脑" / "世界观.md").write_text(
        "第1章发生在旧矿洞，后续章节必须承接这个钩子。\n",
        encoding="utf-8",
    )
    backend = backend_for_chapters()

    plan_chapters(project, total=2, start_from=2, backend=backend)

    user_prompt = backend.calls[0][1]
    assert "第1章发生在旧矿洞" in user_prompt
    assert "第1节发生在旧矿洞" not in user_prompt


def test_progress_none_succeeds(project: Path) -> None:
    result = plan_chapters(project, total=1, backend=backend_for_chapters(), progress=None)

    assert result == {"planned": 1, "skipped": 0, "chapters": [1]}


def test_existing_outline_is_skipped_without_force(project: Path) -> None:
    existing = outline_path(project, 2)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("作者手写的第2章细纲\n", encoding="utf-8")
    card_outline_path(project).write_text("人工卡章纲\n", encoding="utf-8")
    events: list[dict] = []

    result = plan_chapters(project, total=2, backend=backend_for_chapters(), progress=events.append)

    assert result == {"planned": 1, "skipped": 1, "chapters": [1]}
    assert existing.read_text(encoding="utf-8") == "作者手写的第2章细纲\n"
    card_outline = card_outline_path(project).read_text(encoding="utf-8")
    assert "### 第1章" in card_outline
    assert "### 第2章" in card_outline
    assert any(e["type"] == "skip" and e["chapter"] == 2 for e in events)


def test_same_project_planning_is_serialized_and_preserves_all_card_blocks(project: Path) -> None:
    active = 0
    max_active = 0
    state_lock = threading.Lock()
    start = threading.Barrier(3)
    errors: list[BaseException] = []

    class SlowBackend:
        def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
            nonlocal active, max_active
            match = re.search(r"当前任务：为第\s*(\d+)\s*章", user)
            assert match is not None
            chapter_n = int(match.group(1))
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.1)
                return outline_text(chapter_n)
            finally:
                with state_lock:
                    active -= 1

    backend = SlowBackend()

    def run(*, total: int, start_from: int) -> None:
        try:
            start.wait()
            plan_chapters(project, total=total, start_from=start_from, backend=backend)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=run, kwargs={"total": 1, "start_from": 1}),
        threading.Thread(target=run, kwargs={"total": 2, "start_from": 2}),
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert errors == []
    assert max_active == 1
    card = card_outline_path(project).read_text(encoding="utf-8")
    assert "### 第1章\n" + outline_text(1) in card
    assert "### 第2章\n" + outline_text(2) in card


def test_skipped_outline_repairs_missing_card_block_without_backend_call(project: Path) -> None:
    existing_outline = outline_text(1)
    path = outline_path(project, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing_outline + "\n", encoding="utf-8")
    card_outline_path(project).write_text("人工卡章纲\n", encoding="utf-8")

    class ForbiddenBackend:
        def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
            raise AssertionError("backend must not be called for an existing outline")

    result = plan_chapters(project, total=1, backend=ForbiddenBackend())

    assert result == {"planned": 0, "skipped": 1, "chapters": []}
    card = card_outline_path(project).read_text(encoding="utf-8")
    assert "### 第1章\n" + existing_outline in card


def test_generated_outlines_sync_to_card_outline_and_force_replaces_managed_block(project: Path) -> None:
    card = card_outline_path(project)
    card.write_text("人工卡章纲\n", encoding="utf-8")

    plan_chapters(project, total=2, backend=backend_for_chapters())

    first = card.read_text(encoding="utf-8")
    assert first.startswith("人工卡章纲\n")
    assert "<!-- LOOM:CHAPTER-PLAN:START -->" in first
    assert "<!-- LOOM:CHAPTER-PLAN:END -->" in first
    assert "### 第1章\n" + outline_text(1) in first
    assert "### 第2章\n" + outline_text(2) in first

    plan_chapters(
        project,
        total=1,
        backend=FakeBackend(lambda system, user: "第1章：新版目标、冲突、反转、章末钩子。"),
        force=True,
    )

    updated = card.read_text(encoding="utf-8")
    assert updated.startswith("人工卡章纲\n")
    assert updated.count("### 第1章") == 1
    assert "第1章：新版目标、冲突、反转、章末钩子。" in updated
    assert outline_text(1) not in updated
    assert "### 第2章\n" + outline_text(2) in updated


def test_malformed_card_start_without_end_preserves_existing_text_across_runs(project: Path) -> None:
    malformed = (
        "人工卡章纲\n"
        "<!-- LOOM:CHAPTER-PLAN:START -->\n"
        "未闭合的人工笔记\n"
        "### 第8章\n"
        "这段不是 AI 托管区，不能丢。\n"
    )
    card = card_outline_path(project)
    card.write_text(malformed, encoding="utf-8")

    plan_chapters(project, total=1, backend=backend_for_chapters())
    plan_chapters(
        project,
        total=1,
        backend=FakeBackend(lambda system, user: "第1章：第二版目标、冲突、反转、章末钩子。"),
        force=True,
    )

    updated = card.read_text(encoding="utf-8")
    assert malformed in updated
    assert updated.count("未闭合的人工笔记") == 1
    assert "第1章：第二版目标、冲突、反转、章末钩子。" in updated


def test_malformed_chapter_block_inside_valid_managed_section_is_preserved(project: Path) -> None:
    damaged = (
        "<!-- LOOM:CHAPTER-PLAN:CHAPTER:4:START -->\n"
        "### 第4章\n"
        "人工修补中的托管块，缺了结束标记，但内容不能丢。\n"
    )
    card_outline_path(project).write_text(
        "\n\n".join(
            [
                "<!-- LOOM:CHAPTER-PLAN:START -->",
                "## AI 批量章节规划",
                damaged.rstrip(),
                "<!-- LOOM:CHAPTER-PLAN:END -->",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    plan_chapters(project, total=2, start_from=2, backend=backend_for_chapters())
    plan_chapters(
        project,
        total=2,
        start_from=2,
        backend=FakeBackend(lambda system, user: "第2章：第二版目标、冲突、反转、章末钩子。"),
        force=True,
    )

    updated = card_outline_path(project).read_text(encoding="utf-8")
    assert "人工修补中的托管块，缺了结束标记，但内容不能丢。" in updated
    assert updated.count("人工修补中的托管块") == 1
    assert "第2章：第二版目标、冲突、反转、章末钩子。" in updated


def test_malformed_same_chapter_block_survives_repeated_force_regeneration(project: Path) -> None:
    human_text = "人工保留的第2章托管残块，连续重生第2章也不能丢。"
    card_outline_path(project).write_text(
        "\n\n".join(
            [
                "<!-- LOOM:CHAPTER-PLAN:START -->",
                "## AI 批量章节规划",
                "<!-- LOOM:CHAPTER-PLAN:CHAPTER:2:START -->",
                "### 第2章",
                human_text,
                "<!-- LOOM:CHAPTER-PLAN:END -->",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    plan_chapters(
        project,
        total=2,
        start_from=2,
        backend=FakeBackend(lambda system, user: "第2章：第一次强制重生。"),
        force=True,
    )
    plan_chapters(
        project,
        total=2,
        start_from=2,
        backend=FakeBackend(lambda system, user: "第2章：第二次强制重生。"),
        force=True,
    )

    updated = card_outline_path(project).read_text(encoding="utf-8")
    assert human_text in updated
    assert updated.count(human_text) == 1
    assert "第2章：第二次强制重生。" in updated
    assert "第2章：第一次强制重生。" not in updated


def test_outline_headings_that_look_like_chapters_stay_inside_their_chapter_block(project: Path) -> None:
    nested = "第1章：主线目标。\n### 第9章\n这是章内误导标题，仍属于第一章。"

    plan_chapters(project, total=1, backend=FakeBackend(lambda system, user: nested))
    plan_chapters(project, total=2, start_from=2, backend=backend_for_chapters())

    card = card_outline_path(project).read_text(encoding="utf-8")
    assert card.index("### 第9章") < card.index("### 第2章")
    assert "<!-- LOOM:CHAPTER-PLAN:CHAPTER:9:START -->" not in card


def test_existing_outline_is_overwritten_with_force(project: Path) -> None:
    existing = outline_path(project, 1)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("旧细纲\n", encoding="utf-8")

    plan_chapters(project, total=1, backend=backend_for_chapters(), force=True)

    assert existing.read_text(encoding="utf-8").strip() == outline_text(1)


@pytest.mark.parametrize(
    ("total", "start_from"),
    [(0, 1), (1, 0), (2, 3)],
)
def test_invalid_ranges_raise_value_error(project: Path, total: int, start_from: int) -> None:
    with pytest.raises(ValueError):
        plan_chapters(project, total=total, start_from=start_from, backend=backend_for_chapters())
