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


def test_empty_form_rows_not_substantive():
    # 世界观/人物 目录模板的空表单行与空章行同类:零书籍内容
    text = "# 力量体系\n> (占位示例,换成你自己的。)\n- 体系名称:\n- 等级(7-10 级,各级有可见的代价/异化):\n"
    assert is_substantive(text) is False


def test_filled_form_row_is_substantive():
    assert is_substantive("- 体系名称:玄元九阶") is True
    assert is_substantive("- 提刀护驾。") is True   # 无冒号的真内容行不受空表单行规则误伤


def test_paren_label_empty_row_not_substantive():
    # 标签括注里带冒号的空表单行(金手指/未命名卡模板):判空前剥括号段
    assert is_substantive("- 金手指(类型/核心功能;短板:资源):") is False


def test_no_colon_paren_row_stays_substantive():
    assert is_substantive("- 代价(每次折寿三年)") is True   # 无冒号真内容行不受括号剥离误伤


def test_marks_cover_draft_side():
    # draft 写侧防覆盖与读侧过滤共用同一份标记
    assert "占位示例" in PLACEHOLDER_MARKS and "待填充" in PLACEHOLDER_MARKS


def test_fresh_project_card_is_not_substantive(project):
    # 卡章纲模板去毒:预填的通用金手指示例行(会被大纲师当真纲执行)必须改空
    text = (project / "外置大脑/卡章纲.md").read_text(encoding="utf-8")
    assert is_substantive(text) is False
    assert "濒死" not in text   # 通用金手指剧本的预填行必须绝迹(写法示范只许住在 > 注释里)
