"""创作旅程状态机:阶段谓词/游标推进/跳段回跳/坏游标降级(ADR 0013:游标可丢弃、文件现状为准)。"""
from pathlib import Path

from loom import journey
from loom.paths import CARD_REL, PROJECT_CARD_REL


def test_fresh_project_stages_and_current(project):
    s = journey.journey_state(project)
    assert [x["key"] for x in s["stages"]] == ["立项", "世界观", "人物", "卡章纲", "voice"]
    assert all(not x["done"] for x in s["stages"])   # 模板书:占位不算内容
    assert s["current"] == "立项"
    assert s["card"] is None


def test_filled_worldview_marks_done(project):
    (project / "外置大脑/世界观/金手指.md").write_text(
        "# 金手指\n\n吞噬万物的胃袋,吃什么长什么,代价是饭量与寿命挂钩。\n", encoding="utf-8")
    s = journey.journey_state(project)
    world = next(x for x in s["stages"] if x["key"] == "世界观")
    assert world["done"] is True


def test_card_line_with_content_marks_done(project):
    p = project / CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:主角雪夜被逐出宗门,捡到会说话的鼎"),
                 encoding="utf-8")
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "卡章纲")["done"] is True


def test_project_card_platform_line_alone_not_done(project):
    # 模板自带「平台:起点」,不能算立项已完成
    assert next(x for x in journey.journey_state(project)["stages"] if x["key"] == "立项")["done"] is False


def test_skip_advances_current(project):
    s = journey.goto(project, "立项", skip=True)
    assert next(x for x in s["stages"] if x["key"] == "立项")["skipped"] is True
    assert s["current"] == "世界观"


def test_goto_refocuses_and_resets_budget(project):
    journey.goto(project, "立项", skip=True)
    s = journey.goto(project, "立项")           # 回头改
    assert s["current"] == "立项"
    assert next(x for x in s["stages"] if x["key"] == "立项")["skipped"] is False


def test_goto_unknown_stage_raises(project):
    import pytest
    with pytest.raises(ValueError):
        journey.goto(project, "不存在的段")


def test_broken_cursor_falls_back(project):
    (project / ".loom_state.json").write_text("{烂掉的json", encoding="utf-8")
    s = journey.journey_state(project)          # load_state 容错 → 当无游标
    assert s["current"] == "立项"
