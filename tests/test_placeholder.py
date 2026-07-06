"""占位判定/剥离:出厂模板的「填写说明」不冒充书的设定(立项即铺底 §1)。"""
from loom.parse import PLACEHOLDER_MARKS, is_substantive, strip_placeholder_hints


def test_strip_drops_fullline_hints_keeps_content():
    text = "## 分区\n（占位示例:玄幻 · 东方玄幻。填你投稿的那个分区。）\n平台:起点\n(占位示例,换成你自己的。)"
    out = strip_placeholder_hints(text)
    assert "占位示例" not in out
    assert "平台:起点" in out
    assert "## 分区" in out


def test_strip_keeps_inline_mentions():
    # 作者正文里恰好写到「占位示例」四个字(非整行括注)→ 不是提示行,不许剥
    text = "他说这只是个占位示例罢了。"
    assert strip_placeholder_hints(text) == text


def test_substantive_false_for_template_like_text():
    # 出厂模板剥完只剩 标题/引用注释/空章行 → 无实质
    text = "# 卡章纲\n\n> 一章一句话的脊柱。\n> (占位示例,换成你自己的。)\n\n- 第1章:\n- 第2章:\n"
    assert is_substantive(text) is False


def test_substantive_true_when_row_filled():
    text = "# 卡章纲\n\n- 第1章:崇祯睁眼,先杀魏忠贤,章末锦衣卫围殿。\n- 第2章:\n"
    assert is_substantive(text) is True


def test_substantive_true_for_plain_line():
    assert is_substantive("平台:起点") is True


def test_marks_cover_draft_side():
    # draft 写侧防覆盖与读侧过滤共用同一份标记
    assert "占位示例" in PLACEHOLDER_MARKS and "待填充" in PLACEHOLDER_MARKS
