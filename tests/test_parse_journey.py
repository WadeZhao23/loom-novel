"""领航员问题卡解析:行式宽容(问:/- 选项/格:/【无题】),烂输出返 None 走降级。"""
from loom.parse import parse_journey_card


def test_normal_card():
    raw = "问:主角的金手指是什么?\n- 吞噬万物的胃袋:吃什么长什么\n- 时间回溯十秒:代价折寿\n- 说书成真:讲的故事会应验"
    card = parse_journey_card(raw)
    assert card["question"] == "主角的金手指是什么?"
    assert len(card["options"]) == 3
    assert "field" not in card


def test_card_with_field_line():
    raw = "格:题材\n问:这本书的核心题材标签?\n- 重生+复仇+宗门流\n- 无敌流+日常"
    card = parse_journey_card(raw)
    assert card["field"] == "题材"
    assert len(card["options"]) == 2


def test_exhausted_sentinel():
    assert parse_journey_card("【无题】") == {"exhausted": True}


def test_garbage_returns_none():
    assert parse_journey_card("好的!我来帮你分析一下这本书……") is None


def test_options_capped_at_four():
    raw = "问:选一个?\n" + "\n".join(f"- 选项{i}" for i in range(6))
    assert len(parse_journey_card(raw)["options"]) == 4


def test_fullwidth_colon_tolerated():
    card = parse_journey_card("问：主角叫什么？\n- 林潜\n- 你自己起")
    assert card["question"] == "主角叫什么？"


def test_preamble_bullets_not_leaked_into_options():
    raw = "- 已确认三个候选题材\n问:选哪个作主线?\n- 重生流\n- 无敌流"
    card = parse_journey_card(raw)
    assert card["options"] == ["重生流", "无敌流"]
