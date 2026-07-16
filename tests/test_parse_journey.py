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


def test_decorated_question_parses():
    # 模型爱加 markdown 装饰,这是今天降级的第一大来源
    card = parse_journey_card("**问**:金手指选哪个?\n- 吞噬胃袋\n- 时间回溯")
    assert card["question"] == "金手指选哪个?"


def test_question_word_and_numbered_bullets_parse():
    card = parse_journey_card("1. 问题:开局钩子走哪种?\n* 威胁逼近\n• 身世反转")
    assert card["question"] == "开局钩子走哪种?"
    assert card["options"] == ["威胁逼近", "身世反转"]


def test_rule_recitation_does_not_self_degrade():
    # 模型复述格式规则时句中出现「【无题】」——有题面就成卡,不算无题
    raw = "若无题可出,只输出【无题】。\n问:主角的软肋是什么?\n- 亲妹妹在敌方手里\n- 灵根残缺,大道无望"
    card = parse_journey_card(raw)
    assert card["question"] == "主角的软肋是什么?"


def test_bare_sentinel_line_still_exhausted():
    # 独占一行的哨兵(前面可有闲话)仍判无题——老书 prompt 还会这么输出
    assert parse_journey_card("这一段该问的都定好了。\n【无题】") == {"exhausted": True}


def test_whole_question_decoration_stripped():
    # 模型爱把整句问题加粗,不只是「问」字;前端 textContent 不解析 markdown,残留会糊在卡面上
    assert parse_journey_card("问：**整句加粗的问题？**\n- A\n- B")["question"] == "整句加粗的问题？"
    assert parse_journey_card("问:*斜体整句?*\n- A\n- B")["question"] == "斜体整句?"


def test_sentinel_inside_sentence_still_exhausted():
    # 哨兵嵌在句子里(模型没严格独占一行)也算无题——没问句才轮到哨兵
    assert parse_journey_card("本阶段暂时【无题】,无更多可问。") == {"exhausted": True}


def test_decorated_field_line_parses():
    # 格:行要跟问:行一起放宽,否则装饰过的立项卡会丢 field → 静默落错格还烧预算
    card = parse_journey_card("**格**:分区\n**问**:发哪个分区?\n- 玄幻\n- 都市")
    assert card["field"] == "分区"


def test_option_decoration_stripped():
    # 选项也要剥装饰:残留会糊在按钮上,点了还逐字写进作者的设定文件
    card = parse_journey_card("问:选哪个?\n- **加粗候选**\n- *斜体候选*")
    assert card["options"] == ["加粗候选", "斜体候选"]
