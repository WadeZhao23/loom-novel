"""写章轨迹:append-only jsonl,产物级续跑的料。

spec 2026-08-16 §5.1/§7.5(P2)。纪律照抄 `.伙伴对话/当前.jsonl`:单事件单行 append、
坏行跳过、**永不当状态真相**——门禁/完成度一律从文件现状推导,轨迹只用于重放已提交产物。
"""
from __future__ import annotations

from loom import paths, trail


def test_提交事件单行append再读回来(project):
    trail.record_commit(project, 3, "本章设定锚点", "锚点甲乙丙丁", "v2:aaa")
    trail.record_commit(project, 3, "本章初稿", "初稿正文", "v2:bbb")
    got = trail.read_commits(project, 3)
    assert [(c["产物"], c["text"], c["sig"]) for c in got] == [
        ("本章设定锚点", "锚点甲乙丙丁", "v2:aaa"),
        ("本章初稿", "初稿正文", "v2:bbb"),
    ]


def test_坏行跳过不炸(project):
    """半截行(断电写到一半)不该让整条轨迹作废——同 partner_store 的纪律。"""
    trail.record_commit(project, 3, "本章设定锚点", "锚点甲乙丙丁", "v2:aaa")
    p = paths.trail_path(project, 3)
    with p.open("a", encoding="utf-8") as f:
        f.write('{"t":"commit","产物":"半截\n')
    trail.record_commit(project, 3, "本章初稿", "初稿正文", "v2:bbb")
    assert [c["产物"] for c in trail.read_commits(project, 3)] == ["本章设定锚点", "本章初稿"]


def test_没有轨迹时读回空而不是抛(project):
    assert trail.read_commits(project, 3) == []


def test_正文里的多行内容原样活过一轮往返(project):
    """整章正文含换行,单事件单行的形态必须扛得住(json 转义,不是裸文本追加)。"""
    body = "他没说话。\n\n火把的光爬上矿壁。\n血顺着指缝往下滴。"
    trail.record_commit(project, 3, "本章终稿", body, "v2:ccc")
    assert trail.read_commits(project, 3)[0]["text"] == body


def test_轨迹进章节产物表_删章重编号会一起搬():
    """漏了这条 = 删掉第 3 章后,新的第 3 章会重放【上一本第 3 章】的产物。
    章节管理的两段式搬运只认 CHAPTER_ARTIFACTS 这张表。"""
    assert any(d == paths.TRAIL_DIR for d, _, _ in paths.CHAPTER_ARTIFACTS)


def test_删掉整个轨迹目录书完好无损(project):
    """红线:轨迹不是状态真相。删了只是下次从头跑,书本身一个字不动。"""
    import shutil
    trail.record_commit(project, 3, "本章终稿", "终稿正文", "v2:ccc")
    shutil.rmtree(project / paths.TRAIL_DIR)
    assert trail.read_commits(project, 3) == []
    assert (project / "loom.toml").is_file()
