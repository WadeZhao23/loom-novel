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
