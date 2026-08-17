"""refine:把证据蒸成人格的个人增补。

spec 2026-08-16 §5.3。纪律**照搬 fingerprint._LEARN_SYSTEM**(已在写作指纹上验证过十几版)
+ Prime Agent 的 `/refine`:增量并入、既有条目默认一条不删、只在直接矛盾时改写那一条、
**基座永不重写**、不打分。
"""
from __future__ import annotations

from loom import evolve, paths, persona, trail
from loom.backends import LoomBackendError

import pytest


def _evidence(project, n: int, ai: str, author: str) -> None:
    trail.record_commit(project, n, "本章场景骨头(分镜细纲)", ai, f"v2:s{n}")
    p = paths.outline_path(project, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(author, encoding="utf-8")


def _ripe(project) -> None:
    for n in (1, 2, 3):
        _evidence(project, n, f"一。二。三。四。(第{n}章 AI 拆四场)", f"一。二。三。(第{n}章 作者删成三场)")


def test_证据不够时不发任何调用(project):
    from conftest import FakeBackend, const
    _evidence(project, 1, "AI 的", "作者的")
    be = FakeBackend(const("不该被调到"))
    assert evolve.refine(project, "大纲师", be, min_edits=3) is None
    assert be.calls == [], "证据不够就不该花钱"


def test_证据够了蒸出增补(project):
    from conftest import FakeBackend, const
    _ripe(project)
    be = FakeBackend(const("- 这本书默认拆三场,不拆四场。"))
    got = evolve.refine(project, "大纲师", be, min_edits=3)
    assert got and "拆三场" in got


def test_prompt里带上作者两侧的原文(project):
    """判据是「作者实际改成了什么」——AI 那份和作者那份都要摆进去,模型才比得出改法。"""
    from conftest import FakeBackend, const
    _ripe(project)
    be = FakeBackend(const("- 拆三场。"))
    evolve.refine(project, "大纲师", be, min_edits=3)
    _, user = be.calls[0]
    assert "AI 拆四场" in user and "作者删成三场" in user


def test_现有增补随prompt一起进去_供增量并入(project):
    """§5.3 第一条:增量并入,不是推倒重写。模型得先看见现有增补才谈得上并入。"""
    from conftest import FakeBackend, const
    _ripe(project)
    persona.write_extra(project, "大纲师", "- 已经学到的一条老规则。")
    be = FakeBackend(const("- 老规则。\n- 新规则。"))
    evolve.refine(project, "大纲师", be, min_edits=3)
    assert "已经学到的一条老规则" in be.calls[0][1]


def test_基座绝不进可写范围(project):
    """红线:refine 只写增补区。这条测试确认 refine 的产物【不】被当成整份人格覆盖回去。"""
    from conftest import FakeBackend, const
    _ripe(project)
    base_before = persona.split(project, "大纲师")[0]
    be = FakeBackend(const("- 拆三场。"))
    got = evolve.refine(project, "大纲师", be, min_edits=3)
    persona.write_extra(project, "大纲师", got)
    assert persona.split(project, "大纲师")[0] == base_before


def test_空或残废的蒸馏结果被拦下(project):
    """同 guard 的老规矩:模型这次没产出,就别拿一坨空的去覆盖作者攒下的增补。"""
    from conftest import FakeBackend, const
    _ripe(project)
    with pytest.raises(LoomBackendError):
        evolve.refine(project, "大纲师", FakeBackend(const("   ")), min_edits=3)
