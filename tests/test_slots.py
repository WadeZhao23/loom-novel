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
