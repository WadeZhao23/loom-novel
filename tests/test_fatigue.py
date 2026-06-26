"""跨章重复/腔调检测器:抓套路化章首章末 + 整句跨章复用,靠 Dice 阈值与 anchor 豁免控误报。"""
from __future__ import annotations

from pathlib import Path

from loom.fatigue import scan
from loom.gates import Issue


def _ch(project: Path, n: int, body: str, title: str = "标题") -> None:
    (project / "正文" / f"第{n}章.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def _kinds(issues: list[Issue]) -> list[str]:
    return [i.kind for i in issues]


def test_flags_formulaic_opening(project: Path):
    _ch(project, 1, "夜色像浸了墨的布沉沉压下来。他握紧了刀柄。远处一声闷响。")
    draft = "夜色像浸了墨的布沉沉压了下来。她忽然睁开眼睛望向窗外的院子。"
    issues = scan(project, 2, draft)
    assert any(i.kind == "跨章·章首雷同" for i in issues)
    assert all(isinstance(i, Issue) for i in issues)


def test_flags_recycled_sentence(project: Path):
    _ch(project, 1, "开篇是随便的一句闲话。他记得每一个会死的人包括他自己。结尾也随便一句。")
    draft = "这是一个毫不相干的全新开头。他记得每一个会死的人包括他自己。这是又一个毫不相干的收尾。"
    issues = scan(project, 2, draft)
    assert any(i.kind == "跨章·近重复句" for i in issues)
    assert any("他记得每一个会死的人" in i.evidence for i in issues)


def test_distinct_chapters_are_quiet(project: Path):
    _ch(project, 1, "他在矿洞里点亮了火把。脚下的碎石硌得生疼。前方传来滴水声。")
    draft = "春天的集市熙熙攘攘。她挑了一篮新鲜的杨梅。卖糖人的老汉吆喝着。"
    assert scan(project, 2, draft) == []


def test_anchor_exempts_signature_repeat(project: Path):
    # 作者有意复用的母题句(在 anchor 里)→ 不当跨章疲劳报
    _ch(project, 1, "无关的开头一句话。他记得每一个会死的人包括他自己。无关的结尾一句话。")
    draft = "另一个无关的开头句子。他记得每一个会死的人包括他自己。另一个无关的结尾句子。"
    anchors = ["他记得每一个会死的人包括他自己。"]
    assert scan(project, 2, draft, anchors) == []


def test_first_chapter_has_no_priors(project: Path):
    assert scan(project, 1, "随便写点什么作为第一章的正文内容。") == []


def test_no_chapter_files_is_empty(project: Path):
    # 第 5 章但前面几章文件都不存在 → 无可比
    assert scan(project, 5, "孤零零的一章,前面没有任何已落盘的正文。") == []
