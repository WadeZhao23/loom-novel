"""证据喂给模型的是【算好的 diff】,不是两份原文。

真机 2026-08-26(DeepSeek V4-flash,样例书真跑三章、逐章手改细纲)实测:
作者在 3 章里一共删了 5 处「情绪:」行、2 处「许的承诺」行——重复得不能再明显的模式。
旧写法把两份各 1400 字的原文丢给模型、让它自己「逐章比对两份原文」,refine 回的是【无】。
只把证据换成确定性的行级 diff(同一模型、同一批证据、其余不变),它当场归纳出了两条:
  - 不写「情绪：」开头的直接情绪标注,情绪靠场景和行动显现。
  - 不写任何形式的「承诺/预告」句,只写本章要做到的事。

v0.3.7「字数五螺丝」的教训原样适用:**LLM 自己数不准 = 授权无牙**。diff 是确定性的,
difflib 三行就算得出来,没有理由让模型在 40 行里大海捞针。
"""
from __future__ import annotations

from loom import evolve, persona, trail
from loom.evolve import _diff_lines


def test_删掉的行被算出来(project):
    dropped, added, changed = _diff_lines("一\n情绪：紧张。\n二\n", "一\n二\n")
    assert dropped == ["情绪：紧张。"] and added == [] and changed == []


def test_加上的行被算出来(project):
    dropped, added, _ = _diff_lines("一\n二\n", "一\n他把刀收回鞘里。\n二\n")
    assert added == ["他把刀收回鞘里。"] and dropped == []


def test_改写成对_不谎报成一删一加(project):
    """一次改写就是一次改写。拆成「删一行 + 加一行」会让模型以为作者做了两件事。"""
    dropped, added, changed = _diff_lines("一\n约600字\n三\n", "一\n约400字\n三\n")
    assert changed == [("约600字", "约400字")] and dropped == [] and added == []


def test_空白行不算差异(project):
    """落盘补的空行不是「作者改了它」——同 `_norm` 那道闸的口径。"""
    assert _diff_lines("一\n二\n", "\n一\n\n二\n\n") == ([], [], [])


def test_长的一侧落单时归到删或加(project):
    """replace 段两侧行数不等:配对的算改写,落单的老实归类,别丢。"""
    dropped, added, changed = _diff_lines("甲\n乙\n丙\n", "甲改\n")
    assert changed == [("甲", "甲改")]
    assert dropped == ["乙", "丙"] and added == []


def _lay(project, n: int, ai: str, author: str) -> None:
    from loom import paths
    trail.record_commit(project, n, "本章场景骨头(分镜细纲)", ai, f"v2:sig{n}")
    p = paths.outline_path(project, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(author, encoding="utf-8")


def test_prompt里进的是diff不是两份原文(project):
    """核心契约:模型看到的是「作者删掉的行」,而不是两份原文让它自己找。"""
    from conftest import FakeBackend, const
    for n in (1, 2, 3):
        _lay(project, n, f"场景{n}\n情绪：紧张。\n收尾\n", f"场景{n}\n收尾\n")
    be = FakeBackend(const("- 不写情绪行。"))
    evolve.refine(project, "大纲师", be, min_edits=3)
    _sys, user = be.calls[0]
    assert "作者删掉的行" in user
    assert "情绪：紧张。" in user
    assert "作者加上的行" in user
    # 两份原文不该整块塞进去(它们是 diff 的来源,不是给模型的作业)
    assert "【AI 交的】" not in user and "【作者改成的】" not in user


def test_行尾空白被削掉(project):
    """模型爱在行尾留两个空格(markdown 换行),原样落进 agents/<角色>.md 是噪声。"""
    from conftest import FakeBackend, const
    for n in (1, 2, 3):
        _lay(project, n, f"场景{n}\n情绪：紧张。\n", f"场景{n}\n")
    out = evolve.refine(project, "大纲师", FakeBackend(const("- 甲。  \n- 乙。\t")), min_edits=3)
    assert out == "- 甲。\n- 乙。"


def test_现有增补照旧进prompt_增量并入没被这次改动弄丢(project):
    from conftest import FakeBackend, const
    for n in (1, 2, 3):
        _lay(project, n, f"场景{n}\n情绪：紧张。\n", f"场景{n}\n")
    persona.write_extra(project, "大纲师", "- 已经学到的一条老规则。")
    be = FakeBackend(const("- 老规则。\n- 新规则。"))
    evolve.refine(project, "大纲师", be, min_edits=3)
    assert "已经学到的一条老规则" in be.calls[0][1]
