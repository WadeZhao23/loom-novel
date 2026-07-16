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


def test_emptied_platform_line_not_filled(project):
    # 作者删空平台值 → filled=False,preview 不抓下一行标题(防跨行吞噬)
    p = project / "外置大脑/立项卡.md"
    p.write_text(p.read_text(encoding="utf-8").replace("平台:起点", "平台:"), encoding="utf-8")
    plat = next(s for s in stage_slots(project, _stage_spec("立项")) if s.key == "平台")
    assert plat.filled is False
    assert plat.preview == ""


def test_parens_in_user_value_not_taken_as_hint(project):
    # 模板本无括注的行,用户值里的括号不能被当 hint
    p = project / "外置大脑/世界观/力量体系.md"
    p.write_text(p.read_text(encoding="utf-8").replace("- 体系名称:", "- 体系名称:五行(金木水火土)"), encoding="utf-8")
    slot = next(s for s in stage_slots(project, _stage_spec("世界观")) if s.key == "体系名称")
    assert slot.hint == ""
    assert slot.filled is True


def test_unnamed_protagonist_yields_filename_slot(project):
    # 未命名主角:出一个 @name 槽,压住 5 个 row 槽
    slots = [s for s in stage_slots(project, _stage_spec("人物")) if "主角" in s.container]
    assert len(slots) == 1 and slots[0].at == "filename" and slots[0].key == "@name"


def test_named_protagonist_yields_row_slots(project):
    d = project / "外置大脑/人物"
    (d / "主角·未命名.md").rename(d / "主角·林潜.md")
    slots = [s for s in stage_slots(project, _stage_spec("人物")) if "林潜" in s.container]
    assert all(s.at == "row" for s in slots) and len(slots) >= 4
    assert any("林潜" in s.label for s in slots)     # 实体容器 label 带前缀


def test_headerless_file_yields_file_slot(project):
    # 一句话定位.md 零骨架行 → 一个 @body file 槽
    slots = [s for s in stage_slots(project, _stage_spec("世界观")) if s.container.endswith("一句话定位.md")]
    assert len(slots) == 1 and slots[0].at == "file" and slots[0].key == "@body"
    assert slots[0].filled is False


def test_prose_rewrite_degrades_to_file_slot(project):
    # 作者把金手指改成一段散文 → 退化成 1 个 file 槽,不归零
    p = project / "外置大脑/世界观/金手指.md"
    p.write_text("# 金手指\n\n主角能吞噬万物,代价是每吞一次折寿。\n", encoding="utf-8")
    slots = [s for s in stage_slots(project, _stage_spec("世界观")) if s.container.endswith("金手指.md")]
    assert len(slots) == 1 and slots[0].at == "file" and slots[0].filled is True


def test_round_robin_interleaves_containers(project):
    # 前几个未填槽应跨容器交错,不是一个文件全排完
    unfilled = [s for s in stage_slots(project, _stage_spec("世界观")) if not s.filled][:4]
    containers = [s.container for s in unfilled]
    assert len(set(containers)) >= 2      # 前 4 个未填槽来自 ≥2 个文件
