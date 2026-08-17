"""提议 → 拍板 → 落增补 → 可撤销。

spec 2026-08-16 §5.4 + §7.1。红线:**绝不替作者做决定**——refine 蒸出来的东西是候选,
作者点了才落。落盘前留快照,一键还原(同 `.指纹历史/` 给 learn 的待遇)。

为什么不自动落:改了提示词,下一章出稿就变了,而作者不知道为什么。可见性 + 可撤销,
是这条自进化链唯一让人放心的形状。
"""
from __future__ import annotations

from loom import evolve, paths, persona, trail


def _ripe(project) -> None:
    for n in (1, 2, 3):
        trail.record_commit(project, n, "本章场景骨头(分镜细纲)", f"一。二。三。四。(第{n}章)", f"v2:s{n}")
        p = paths.outline_path(project, n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"一。二。三。(第{n}章 作者删成三场)", encoding="utf-8")


def test_提议只出候选不落盘(project):
    from conftest import FakeBackend, const
    _ripe(project)
    before = (project / "agents/大纲师.md").read_text(encoding="utf-8")
    prop = evolve.propose(project, "大纲师", FakeBackend(const("- 默认拆三场。")), min_edits=3)
    assert prop and "拆三场" in prop["内容"] and prop["角色"] == "大纲师"
    assert prop["证据章数"] == 3
    assert (project / "agents/大纲师.md").read_text(encoding="utf-8") == before, "提议阶段一个字都不许落"


def test_拍板才落进增补区(project):
    from conftest import FakeBackend, const
    _ripe(project)
    prop = evolve.propose(project, "大纲师", FakeBackend(const("- 默认拆三场。")), min_edits=3)
    base_before = persona.split(project, "大纲师")[0]
    evolve.confirm(project, "大纲师", prop["内容"])
    base, extra = persona.split(project, "大纲师")
    assert "拆三场" in extra
    assert base == base_before, "基座一个字不许动"


def test_落盘前留快照_可一键还原(project):
    from conftest import FakeBackend, const
    _ripe(project)
    persona.write_extra(project, "大纲师", "- 原来那条。")
    evolve.confirm(project, "大纲师", "- 新学的那条。")
    assert "新学的" in persona.split(project, "大纲师")[1]
    assert evolve.revert(project, "大纲师") is not None
    assert persona.split(project, "大纲师")[1] == "- 原来那条。"


def test_撤销是一次性的(project):
    """撤完即清快照——同 fingerprint.revert_learn:只撤一层,不做无限回退栈。"""
    evolve.confirm(project, "大纲师", "- 一条。")
    assert evolve.revert(project, "大纲师") is not None
    assert evolve.revert(project, "大纲师") is None


def test_快照落在进化目录_不进外置大脑(project):
    """§5.1 红线:进化相关的东西一律不进外置大脑——进了会被人格当设定读到。"""
    evolve.confirm(project, "大纲师", "- 一条。")
    assert (project / paths.EVOLVE_DIR).is_dir()
    assert not (project / paths.BRAIN_DIR / ".进化").exists()


def test_整个进化目录删掉书完好无损(project):
    import shutil
    evolve.confirm(project, "大纲师", "- 一条。")
    shutil.rmtree(project / paths.EVOLVE_DIR)
    assert evolve.revert(project, "大纲师") is None      # 撤不了了,仅此而已
    assert "一条" in persona.split(project, "大纲师")[1]  # 已落的增补还在,书没坏
    assert (project / "loom.toml").is_file()


def test_证据不够时不提议(project):
    from conftest import FakeBackend, const
    assert evolve.propose(project, "大纲师", FakeBackend(const("x")), min_edits=3) is None
