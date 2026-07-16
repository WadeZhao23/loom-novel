"""draft 起草:空 idea 回退读建书时存的 Config.idea;prompt 按题材自适应(历史题材不硬凑力量体系)。"""
from loom.config import load_config, save_config
from loom.draft import _DRAFT_SYSTEM, _is_blank_or_template, draft_brain
from loom.paths import CARD_REL
from conftest import FakeBackend, const

_OK = ("===世界观===\n## 一句话定位\n末代皇帝的翻盘局。\n===人物卡===\n## 主角 · 朱由检\n- 核心欲望:活下去。\n"
       "===卡章纲===\n- 第1章:睁眼,杀魏忠贤,章末锦衣卫围殿。")


def test_empty_idea_falls_back_to_config(project):
    cfg = load_config(project)
    cfg.idea = "重生成崇祯,开局砍魏忠贤"
    save_config(project, cfg)
    be = FakeBackend(const(_OK))
    draft_brain(project, "", be)
    assert "重生成崇祯,开局砍魏忠贤" in be.calls[0][1]


def test_explicit_idea_wins(project):
    cfg = load_config(project)
    cfg.idea = "存的旧设定"
    save_config(project, cfg)
    be = FakeBackend(const(_OK))
    draft_brain(project, "现填的新设定", be)
    assert "现填的新设定" in be.calls[0][1]
    assert "存的旧设定" not in be.calls[0][1]


def test_prompt_is_genre_adaptive():
    # 系统提示词不再把「力量体系/金手指」焊死为必填——历史/都市题材有替代小节
    assert "时代格局" in _DRAFT_SYSTEM
    assert "主角优势" in _DRAFT_SYSTEM


def test_blank_or_template_respects_filled_rows(tmp_path):
    # 引导行自带「占位示例」但作者已填真内容 → 不可覆盖;纯骨架 → 可覆盖
    p = tmp_path / "卡章纲.md"
    p.write_text("> (占位示例,换成你自己的。)\n\n- 第1章:主角雪夜被逐出宗门\n- 第2章:\n", encoding="utf-8")
    assert _is_blank_or_template(p) is False
    p.write_text("> (占位示例,换成你自己的。)\n\n- 第1章:\n- 第2章:\n", encoding="utf-8")
    assert _is_blank_or_template(p) is True


def test_filled_rows_survive_draft_brain(project):
    # 复现静默覆盖:作者答题填了章行 → 点「AI 铺设定底稿」→ 拍板的行必须还在,整段必须 skipped
    card = project / CARD_REL
    card.write_text(card.read_text(encoding="utf-8").replace(
        "- 第1章:", "- 第1章:主角雪夜被逐出宗门,捡到会说话的鼎"), encoding="utf-8")
    out = draft_brain(project, "一句话设定", FakeBackend(const(_OK)))
    text = card.read_text(encoding="utf-8")
    assert "主角雪夜被逐出宗门" in text
    assert "卡章纲" in out["skipped"]
