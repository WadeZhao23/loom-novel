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
