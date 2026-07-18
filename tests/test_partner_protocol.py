from loom.parse import parse_tool_block, parse_tool_blocks


def test_multi_blocks_two_proposals():
    # FB-B:一条消息连发两个「提设定」→ 解析出两个工具(各自 params 到下一个用:止),say=引子
    say, tools = parse_tool_blocks(
        "我给你两个方向:\n\n用:提设定\n落点:立项卡#分区\n内容:玄幻\n\n用:提设定\n落点:立项卡#分区\n内容:都市",
        valid_names={"提设定"})
    assert say == "我给你两个方向:"
    assert [t["params"]["内容"] for t in tools] == ["玄幻", "都市"]


def test_multi_blocks_next_用_terminates_params():
    # 第二个「用:」行必须终止前一块的 params(否则被 _TOOL_KV_RE 当 用=提设定 吞掉)
    say, tools = parse_tool_blocks("用:提设定\n落点:a\n用:提设定\n落点:b", valid_names={"提设定"})
    assert len(tools) == 2
    assert tools[0]["params"] == {"落点": "a"} and "用" not in tools[0]["params"]
    assert tools[1]["params"] == {"落点": "b"}


def test_multi_blocks_filters_invalid_names():
    # 名字不在注册表的「用:」块不算,只收有效块
    _, tools = parse_tool_blocks("用:瞎编\n\n用:看地基", valid_names={"看地基", "提设定"})
    assert [t["name"] for t in tools] == ["看地基"]


def test_singular_wrapper_returns_first():
    # 薄兼容层:parse_tool_block 仍返回第一个(既有调用点/测试不受影响)
    _, tool = parse_tool_block("用:提设定\n落点:a\n\n用:提设定\n落点:b", valid_names={"提设定"})
    assert tool == {"name": "提设定", "params": {"落点": "a"}}


def test_parenthesized_trigger_still_parsed():
    # 真机:模型把 用:提设定 包进括号「(用:提设定)」(照抄历史叙述的括号壳)——parser 必须认,否则漏字不出卡
    _, tools = parse_tool_blocks(
        "好,给你:\n(用:提设定)\n落点:外置大脑/立项卡.md#分区\n内容:玄幻", valid_names={"提设定"})
    assert [t["name"] for t in tools] == ["提设定"]
    assert tools[0]["params"]["内容"] == "玄幻"


def test_bracketed_trigger_still_parsed():
    # 方括号/全角括号壳一样认
    _, t1 = parse_tool_blocks("【用:看地基】", valid_names={"看地基"})
    _, t2 = parse_tool_blocks("（用:看地基）", valid_names={"看地基"})
    assert [t["name"] for t in t1] == ["看地基"] and [t["name"] for t in t2] == ["看地基"]


def test_non_trigger_paren_prose_not_matched():
    # 「(用不着提设定)」这类散文不是触发(用后面不是冒号)——别误吞
    _, tools = parse_tool_blocks("(用不着提设定)吧", valid_names={"提设定", "看地基"})
    assert tools == []


def test_speech_only():
    say, tool = parse_tool_block("我觉得这本书的金手指可以走系统流。")
    assert say == "我觉得这本书的金手指可以走系统流。"
    assert tool is None


def test_tool_block():
    say, tool = parse_tool_block("我看看金手指定得怎么样。\n\n用:读文件\n路径:外置大脑/世界观/金手指.md")
    assert say == "我看看金手指定得怎么样。"
    assert tool == {"name": "读文件", "params": {"路径": "外置大脑/世界观/金手指.md"}}


def test_only_first_block_tail_dropped():
    say, tool = parse_tool_block("话\n\n用:看地基\n\n用:读文件\n路径:x")
    assert tool["name"] == "看地基"     # 第一个块
    assert "用:读文件" not in say        # 尾巴不进说话段


def test_decorated_tool_line_tolerated():
    _, tool = parse_tool_block("**用**:读文件\n**路径**:外置大脑/立项卡.md")
    assert tool == {"name": "读文件", "params": {"路径": "外置大脑/立项卡.md"}}


def test_fullwidth_colon():
    _, tool = parse_tool_block("用：看地基")
    assert tool == {"name": "看地基", "params": {}}


def test_valid_names_skips_false_trigger():
    # 说话行「用：xxx」名字不在注册表→跳过,真工具块被找到,说话行留在说话段
    say, tool = parse_tool_block("用:这是个例子\n\n用:读文件\n路径:x", valid_names={"读文件", "看地基", "提设定"})
    assert tool == {"name": "读文件", "params": {"路径": "x"}}
    assert "这是个例子" in say          # 误触发行留在说话段,没丢


def test_valid_names_all_unknown_is_speech():
    # 全是不认识的名字→当纯说话,tool=None
    say, tool = parse_tool_block("我用:一个比喻来说明", valid_names={"读文件"})
    assert tool is None
    assert "比喻" in say


def test_numbered_prefix_tolerated():
    say, tool = parse_tool_block("1. 用:看地基", valid_names={"看地基"})
    assert tool == {"name": "看地基", "params": {}}


def test_valid_names_none_keeps_legacy_first_block():
    # 不传 valid_names → 现状:认第一个块不校验名字(向后兼容)
    _, tool = parse_tool_block("用:随便什么\n参数:x")
    assert tool["name"] == "随便什么"
