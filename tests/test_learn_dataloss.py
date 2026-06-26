"""用户实报的数据丢失:换模型 → learn 返回空 → 指纹被擦。这里钉死「绝不再发生」。"""
from __future__ import annotations

import pytest

from loom.backends import LoomBackendError
from loom.fingerprint import FINGERPRINT_REL, learn
from loom.state import load_state

from conftest import FakeBackend, const

VALID_FP = ("# 写作指纹\n\n## 句式偏好\n- 短句为主,单句成段,动作收尾。\n"
            "- 对白只留半句,潜台词留给读者。\n\n## 节奏\n- 紧处短句快切。\n\n"
            "## anchor 例句\n> 风停了。他把刀收回鞘里,没回头。\n")


def _seed_chapter(project, snapshot: str, edited: str) -> None:
    (project / "正文" / ".原稿").mkdir(parents=True, exist_ok=True)
    (project / "正文" / ".原稿" / "第1章.md").write_text(snapshot, encoding="utf-8")
    (project / "正文" / "第1章.md").write_text(edited, encoding="utf-8")


def test_empty_learn_output_does_not_destroy_fingerprint(project):
    fp = project / FINGERPRINT_REL
    before = fp.read_text(encoding="utf-8")
    _seed_chapter(project, "原始的一句话。", "我手改后的一句话。")

    with pytest.raises(LoomBackendError) as e:
        learn(project, 1, FakeBackend(const("")))          # 模型返回空

    assert e.value.code == "model_output_invalid"
    assert fp.read_text(encoding="utf-8") == before        # 指纹一字未动!
    assert 1 not in set(load_state(project).get("learned", []))   # 没被标记「已学」


def test_garbage_learn_output_is_rejected(project):
    fp = project / FINGERPRINT_REL
    before = fp.read_text(encoding="utf-8")
    _seed_chapter(project, "原始的一句话。", "我手改后的一句话。")

    with pytest.raises(LoomBackendError):
        learn(project, 1, FakeBackend(const("好的,我明白了。")))   # 无小节结构的废话

    assert fp.read_text(encoding="utf-8") == before


def test_valid_learn_output_is_written(project):
    fp = project / FINGERPRINT_REL
    _seed_chapter(project, "原始的一句话。", "我手改后的、更像我的一句话。")

    learn(project, 1, FakeBackend(const(VALID_FP)))

    assert "潜台词留给读者" in fp.read_text(encoding="utf-8")    # 新指纹写进去了
    assert 1 in set(load_state(project).get("learned", []))
    backup = project / "外置大脑" / ".指纹历史" / "第1章-learn前.md"
    assert backup.exists()                                       # learn 前的旧指纹有备份可撤销


def test_title_only_change_is_not_a_hand_edit(project):
    # 只改了标题、正文体没动 → 没有「你的改动」可学,learn 该明确拒绝(而非学到标题)
    _seed_chapter(project, "# 旧标题\n\n一样的正文内容。", "# 新标题\n\n一样的正文内容。")
    with pytest.raises(LoomBackendError) as e:
        learn(project, 1, FakeBackend(const(VALID_FP)))
    assert "一个字都还没改" in str(e.value)


def test_drastic_shrink_warns_but_still_writes(project):
    # 软闸:新指纹合法但明显变短/丢光 anchor → 仍写入(尊重 ADR0001 人兜),但给可撤销提示
    fp = project / FINGERPRINT_REL
    long_fp = ("# 写作指纹\n\n## 句式偏好\n" + "- 一条攒下来的偏好。\n" * 20 +
               "\n## anchor 例句\n> 例句一。\n> 例句二。\n> 例句三。\n")
    fp.write_text(long_fp, encoding="utf-8")
    _seed_chapter(project, "原始的一句话。", "我手改后的一句话。")
    short_valid = "# 写作指纹\n\n## 句式偏好\n- 短句为主,动作收尾,对白只留半句。\n- 不解释情绪。\n"
    events: list = []
    learn(project, 1, FakeBackend(const(short_valid)), events.append)
    assert "对白只留半句" in fp.read_text(encoding="utf-8")          # 仍写入(软闸不拦)
    done = next(e for e in events if e["type"] == "learn_done")
    assert done["shrink_warning"]                                    # 但给了可撤销提示


def test_title_change_not_learned_as_voice(project):
    # 正文体真改了、标题也改了 → 能 learn,但喂给模型的 diff 不含标题行(标题不进文风)
    _seed_chapter(project, "# 旧标题\n\n原始的一句话。", "# 新标题\n\n我手改后的、更像我的一句话。")
    fake = FakeBackend(const(VALID_FP))
    learn(project, 1, fake)
    learn_call = fake.calls[0][1]          # 第一次调用就是 learn 主调用的 user prompt
    assert "旧标题" not in learn_call and "新标题" not in learn_call
