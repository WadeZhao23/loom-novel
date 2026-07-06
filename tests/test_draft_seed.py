"""draft 起草:空 idea 回退读建书时存的 Config.idea;prompt 按题材自适应(历史题材不硬凑力量体系)。"""
from loom.config import load_config, save_config
from loom.draft import _DRAFT_SYSTEM, draft_brain
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
