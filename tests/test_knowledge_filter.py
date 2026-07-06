"""knowledge 组装的占位过滤:占位模板是写给作者的填写说明,不是书的设定(立项即铺底 §1)。"""
from loom.agents import _knowledge_items
from loom.fsutil import atomic_write_text


def test_fresh_project_card_not_fed_to_outliner(project):
    # 新书卡章纲还是空骨架 → 大纲师读不到它(否则空行/注释冒充章纲)
    _, items = _knowledge_items(project, 1, "大纲师")
    assert all("卡章纲" not in rel for rel, _ in items)


def test_filled_card_is_fed(project):
    card = project / "外置大脑/卡章纲.md"
    text = card.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:崇祯睁眼,先杀魏忠贤,章末锦衣卫围殿。")
    atomic_write_text(card, text)
    _, items = _knowledge_items(project, 1, "大纲师")
    got = {rel: t for rel, t in items}
    assert "外置大脑/卡章纲.md" in got
    assert "魏忠贤" in got["外置大脑/卡章纲.md"]


def test_project_card_hints_stripped_but_platform_kept(project):
    # 立项卡真内容(平台行)与占位括注混排:括注剥掉、平台行保留,不许整份误杀
    _, items = _knowledge_items(project, 1, "设定师")
    got = {rel: t for rel, t in items}
    assert "外置大脑/立项卡.md" in got
    assert "占位示例" not in got["外置大脑/立项卡.md"]
    assert "平台:起点" in got["外置大脑/立项卡.md"]


def test_writer_still_gets_fingerprint(project):
    # 中性默认指纹是真内容(写手的灵魂),过滤绝不能把它剥没
    _, items = _knowledge_items(project, 1, "写手")
    assert any(rel.endswith("写作指纹.md") for rel, _ in items)
