"""起书门禁:无 Loom 织章的新书拦第一章、force 不越门禁、有 Loom 织章的书豁免。"""
from pathlib import Path

from loom import usecases, paths, ledger


def _ready(project):
    (project / paths.PROJECT_CARD_REL).write_text("# 立项卡\n\n## 题材\n重生权谋\n", encoding="utf-8")
    (project / "外置大脑/世界观/金手指.md").write_text("# 金手指\n\n吞噬胃袋。\n", encoding="utf-8")
    (project / "外置大脑/人物/主角·林潜.md").write_text("# 主角\n\n废柴逆袭。\n", encoding="utf-8")
    p = project / paths.CARD_REL
    p.write_text(p.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:雪夜被逐"), encoding="utf-8")


def test_bare_book_blocks_with_brain_incomplete(project):
    rej = usecases.write_precheck(project, 1, False)
    assert rej["code"] == "brain_incomplete"
    assert rej["missing"] == ["立项", "世界观", "人物", "卡章纲"]
    assert rej["stage"] == "立项"


def test_force_does_not_bypass_gate(project):
    rej = usecases.write_precheck(project, 1, True)   # force 不越门禁
    assert rej["code"] == "brain_incomplete"


def test_ready_book_passes(project):
    _ready(project)
    assert usecases.write_precheck(project, 1, False) is None


def test_book_with_loom_chapter_is_exempt(project):
    # 有 Loom 织的章(有 .原稿 快照)→ 门禁豁免,回落原三态
    out = paths.chapter_path(project, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 第1章\n\n正文。\n", encoding="utf-8")
    snap = paths.snapshot_path(project, 1)
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")   # .原稿 快照(_has_loom_chapter 判据)
    ledger.record_snapshot(project, 1, out.read_text(encoding="utf-8"))
    assert usecases.write_precheck(project, 2, False) is None   # 写第2章:大脑空也豁免(书已在写)
