from loom.parse import parse_tool_block


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
