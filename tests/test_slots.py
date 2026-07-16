"""槽位扫描器:把外置大脑骨架行读成可寻址槽位。纯派生、零模型。"""
from loom.journey import STAGES, _stage_spec


def test_stagespec_has_slot_order():
    world = _stage_spec("世界观")
    assert world.slot_order == ("一句话定位", "力量体系", "金手指", "地理与势力", "冰山真相")
    assert _stage_spec("voice").slot_order == ()


def test_template_card_has_arc_line(project):
    text = (project / "外置大脑/卡章纲.md").read_text(encoding="utf-8")
    assert "- 大弧:" in text
    assert text.index("- 第5章:") < text.index("- 大弧:")   # 大弧在五章之后


from loom.slots import stage_slots, Slot


def _ids(slots): return [s.id for s in slots]


def test_project_stage_slots_line_and_h2(project):
    slots = stage_slots(project, _stage_spec("立项"))
    d = {s.key: s for s in slots}
    assert d["平台"].at == "line" and d["平台"].filled is True       # 模板预填「起点」
    assert d["题材"].at == "h2" and d["题材"].filled is False        # 占位不算实质
    assert d["题材"].container == "外置大脑/立项卡.md"


def test_row_slots_carry_hint_and_fill(project):
    # 金手指 8 行 row,hint 取括注原文,填了才 filled
    p = project / "外置大脑/世界观/金手指.md"
    slots = [s for s in stage_slots(project, _stage_spec("世界观")) if s.container.endswith("金手指.md")]
    cost = next(s for s in slots if "代价" in s.key)
    assert cost.at == "row"
    assert "硬代价" in cost.hint          # 括注原文进 hint
    assert cost.filled is False
    p.write_text(p.read_text(encoding="utf-8").replace(
        "- 代价·限制(至少一种硬代价,不能无敌到没冲突):",
        "- 代价·限制(至少一种硬代价,不能无敌到没冲突):每用一次折寿三天"), encoding="utf-8")
    cost2 = next(s for s in stage_slots(project, _stage_spec("世界观"))
                 if s.container.endswith("金手指.md") and "代价" in s.key)
    assert cost2.filled is True
    assert "折寿三天" in cost2.preview
