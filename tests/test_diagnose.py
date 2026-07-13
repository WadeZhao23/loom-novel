"""整书诊断 scan:读采样正文,cheap LLM 出三段候选(带出处),不落盘。"""
from pathlib import Path

from loom import diagnose, paths
from conftest import FakeBackend, const

_CANDIDATE = (
    "===世界观===\n## 金手指\n重生带着前世记忆(第1章:「他记得三年后的那一刀」)。\n"
    "===人物卡===\n## 主角 · 沈砚\n矿场少年,重生复仇(第1章)。\n"
    "===卡章纲===\n- 第1章:雪夜矿场重生,记忆觉醒。\n"
)


def _seed_chapters(project, n=3):
    for i in range(1, n + 1):
        p = paths.chapter_path(project, i); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# 第{i}章\n\n沈砚在矿场，记得三年后的那一刀。\n", encoding="utf-8")


def test_scan_returns_three_section_candidates_no_write(project):
    _seed_chapters(project)
    before = (project / "外置大脑/世界观").glob("*.md")
    before_names = {f.name for f in before}
    out = diagnose.scan(project, FakeBackend(const(_CANDIDATE)))
    assert "金手指" in out["世界观"]
    assert "沈砚" in out["人物卡"]
    assert out["卡章纲"].startswith("- 第1章")
    # 不落盘:世界观目录没多出文件
    after_names = {f.name for f in (project / "外置大脑/世界观").glob("*.md")}
    assert after_names == before_names


def test_scan_samples_reads_body(project):
    _seed_chapters(project, 5)
    fake = FakeBackend(const(_CANDIDATE))
    diagnose.scan(project, fake)
    # 采样进了 prompt:user 里带正文关键词
    assert any("沈砚" in user for _, user in fake.calls)


def test_scan_garbage_returns_empty(project):
    _seed_chapters(project)
    assert diagnose.scan(project, FakeBackend(const("好的我来帮你分析一下这本书。"))) == {}


def test_scan_no_chapters_returns_empty(project):
    assert diagnose.scan(project, FakeBackend(const(_CANDIDATE))) == {}


def test_commit_lands_candidates_skipping_digest(project):
    # commit 直接落已整形候选,不调 LLM(backend 传 None 也能落 sections/card_lines)
    from loom import diagnose
    picks = {
        "世界观": "## 金手指\n重生记忆。",
        "人物卡": "## 主角 · 沈砚\n矿场少年。",
        "卡章纲": "- 第1章:雪夜重生。",
        "protagonist": "沈砚",
    }
    out = diagnose.commit(project, picks)
    assert (project / "外置大脑/世界观/金手指.md").is_file()
    assert (project / "外置大脑/人物/主角·沈砚.md").is_file()   # 主角指认落对名
    assert "第1章:雪夜重生" in (project / "外置大脑/卡章纲.md").read_text(encoding="utf-8")


def test_commit_does_not_overwrite_human_file(project):
    from loom import diagnose
    human = project / "外置大脑/世界观/金手指.md"
    human.write_text("# 金手指\n\n我手写的,别动。\n", encoding="utf-8")
    diagnose.commit(project, {"世界观": "## 金手指\nAI 提炼的。", "人物卡": "", "卡章纲": "", "protagonist": ""})
    assert "我手写的,别动" in human.read_text(encoding="utf-8")   # 人写优先,不覆盖
    assert "AI 提炼的" not in human.read_text(encoding="utf-8")   # 撞人写成品 → 进访谈补充,不进原文件


def test_commit_unlocks_gate(project):
    from loom import diagnose, journey, paths
    # 先造正文章(有章)+ 立项(建书代落场景外,手补一格)
    (project / paths.PROJECT_CARD_REL).write_text("# 立项卡\n\n## 题材\n重生\n", encoding="utf-8")
    diagnose.commit(project, {
        "世界观": "## 金手指\n重生记忆。", "人物卡": "## 主角 · 沈砚\n少年。",
        "卡章纲": "- 第1章:重生。", "protagonist": "沈砚"})
    ok, missing = journey.writing_unlocked(project)
    assert ok is True and missing == []   # 四项齐,门禁开
