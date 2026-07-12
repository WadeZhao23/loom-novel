"""起书完整性谓词:立项/章纲放宽救导入、主角硬判、writing_unlocked 四项。"""
from pathlib import Path

from loom import journey
from loom.paths import PROJECT_CARD_REL, CARD_REL


def test_fresh_template_book_locked(project):
    ok, missing = journey.writing_unlocked(project)
    assert ok is False
    assert missing == ["立项", "世界观", "人物", "卡章纲"]   # 模板书四项全缺、voice 不算


def test_kaczhang_prose_form_unlocks(project):
    # 段落式章纲(导入形态,无「- 第N章:」行)也算达标
    (project / CARD_REL).write_text("# 卡章纲\n\n开局主角雪夜被逐出宗门,捡到会说话的青铜鼎,立誓复仇。\n", encoding="utf-8")
    assert "卡章纲" not in journey.writing_unlocked(project)[1]


def test_project_card_imported_heading_unlocks(project):
    # 导入立项卡内容拼在「## 来自:xxx」头下,四格谓词抓不到,但整卡有实质→算达标
    (project / PROJECT_CARD_REL).write_text(
        "# 立项卡\n\n## 来自:我的设定.md\n番茄男频,重生权谋朝堂争斗流,对标《庆余年》。\n", encoding="utf-8")
    assert "立项" not in journey.writing_unlocked(project)[1]


def test_only_villain_card_does_not_pass_protagonist(project):
    (project / "外置大脑/人物/反派·魔尊.md").write_text("# 反派\n\n手段狠辣的魔道尊主。\n", encoding="utf-8")
    assert journey._protagonist_done(project) is False
    assert "人物" in journey.writing_unlocked(project)[1]


def test_protagonist_card_passes(project):
    (project / "外置大脑/人物/主角·林潜.md").write_text("# 主角\n\n废柴出身,吞噬万物的胃袋金手指。\n", encoding="utf-8")
    assert journey._protagonist_done(project) is True


def test_all_four_unlocks(project):
    (project / PROJECT_CARD_REL).write_text("# 立项卡\n\n## 题材\n重生权谋\n", encoding="utf-8")
    (project / "外置大脑/世界观/金手指.md").write_text("# 金手指\n\n吞噬胃袋,代价挂寿命。\n", encoding="utf-8")
    (project / "外置大脑/人物/主角·林潜.md").write_text("# 主角\n\n废柴逆袭。\n", encoding="utf-8")
    p = project / CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:雪夜被逐,捡到鼎"), encoding="utf-8")
    ok, missing = journey.writing_unlocked(project)
    assert ok is True and missing == []
