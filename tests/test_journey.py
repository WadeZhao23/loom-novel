"""创作旅程状态机:阶段谓词/游标推进/跳段回跳/坏游标降级(ADR 0013:游标可丢弃、文件现状为准)。"""
from pathlib import Path

from loom import journey
from loom.paths import CARD_REL, PROJECT_CARD_REL
from conftest import FakeBackend, const


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


def test_navigator_loads_from_project(project):
    text = journey._navigator_system(project)
    assert "问题卡" in text and "绝不" in text     # 职责 + 红线都在系统提示词里


def test_navigator_falls_back_to_package_template(project):
    (project / "agents/领航员.md").unlink(missing_ok=True)        # 老书没有这个文件
    text = journey._navigator_system(project)
    assert "问题卡" in text                        # 包内模板兜底,不抛 FileNotFoundError


# ---- 出题(Task 4) ----

_CARD_RAW = "问:主角的金手指是什么?\n- 吞噬胃袋\n- 时间回溯"


def test_next_card_generates_and_caches(project):
    fake = FakeBackend(const(_CARD_RAW))
    out = journey.next_card(project, fake)
    assert out["card"]["question"] == "主角的金手指是什么?"
    assert out["card"]["stage"] == "立项"
    assert len(fake.calls) == 1
    out2 = journey.next_card(project, fake)      # 源文件没动 → 吃缓存,零计费
    assert len(fake.calls) == 1
    assert out2["card"]["question"] == out["card"]["question"]


def test_next_card_regenerates_when_files_change(project):
    fake = FakeBackend(const(_CARD_RAW))
    journey.next_card(project, fake)
    p = project / PROJECT_CARD_REL               # 用户外改文件 → 签名变 → 重出题
    p.write_text(p.read_text(encoding="utf-8") + "\n手补一行定位\n", encoding="utf-8")
    journey.next_card(project, fake)
    assert len(fake.calls) == 2


def test_next_card_counts_budget(project):
    fake = FakeBackend(const(_CARD_RAW))
    journey.next_card(project, fake)
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "立项")["asked"] == 1


def test_exhausted_chain_advances_to_voice(project):
    fake = FakeBackend(const("【无题】"))         # 每段都答无题 → 设计内的连锁问尽
    out = journey.next_card(project, fake)
    s = out["state"]
    assert next(x for x in s["stages"] if x["key"] == "立项")["skipped"] is True
    assert out["card"] == {"stage": "voice", "static": "seed"}   # 四段跳完停在 voice 静态卡


def test_garbage_degrades_without_burning_budget(project):
    fake = FakeBackend(const("我觉得这本书应该……(不成卡的闲聊)"))
    out = journey.next_card(project, fake)
    assert out["card"]["degraded"] is True
    assert out["card"]["options"] == []
    s = journey.journey_state(project)
    assert next(x for x in s["stages"] if x["key"] == "立项")["asked"] == 0


def test_voice_stage_static_card(project):
    for k in ("立项", "世界观", "人物", "卡章纲"):
        journey.goto(project, k, skip=True)
    out = journey.next_card(project, FakeBackend(const("不该被调用")))
    assert out["card"] == {"stage": "voice", "static": "seed"}
