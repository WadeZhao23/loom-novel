"""镜台的曲线:每章手改量随时间的两条线。

spec 2026-08-17。改写率=它像不像你(voice);增删率=它懂不懂你要什么(what)。
"""
from __future__ import annotations

from loom import mirror, paths
from loom.state import mark_learned


def _chapter(project, n: int, ai: str, edited: str, *, learn: bool = True) -> None:
    """铺一章:`.原稿` 放 AI 稿,`正文` 放作者改后的;默认标记成 learn 过。"""
    paths.snapshot_path(project, n).parent.mkdir(parents=True, exist_ok=True)
    paths.chapter_path(project, n).parent.mkdir(parents=True, exist_ok=True)
    paths.snapshot_path(project, n).write_text(f"# 标题\n{ai}", encoding="utf-8")
    paths.chapter_path(project, n).write_text(f"# 标题\n{edited}", encoding="utf-8")
    if learn:
        mark_learned(project, n)


def test_改写率算得对(project):
    ai = "一。二。三。四。五。六。七。八。九。十。"          # 10 句
    edited = "壹。贰。叁。四。五。六。七。八。九。十。"        # 前 3 句被改写
    _chapter(project, 1, ai, edited)
    row = mirror.curve(project)[0]
    assert row["章"] == 1
    assert abs(row["改写率"] - 0.3) < 0.001
    assert row["增删率"] == 0.0


def test_增删率算得对(project):
    ai = "一。二。三。四。五。六。七。八。九。十。"
    edited = ai + "加一。加二。"                              # 纯加 2 句
    _chapter(project, 1, ai, edited)
    row = mirror.curve(project)[0]
    assert row["改写率"] == 0.0
    assert abs(row["增删率"] - 0.2) < 0.001


def test_没learn过的章不进曲线(project):
    """诚实边界:没 learn 的 0% 是「还没看」,不是「不用改」。
    摆进曲线会让英雄指标虚高,而虚高一次就再也不可信了。"""
    _chapter(project, 1, "一。二。", "壹。二。", learn=False)
    assert mirror.curve(project) == []


def test_导入章没有AI稿所以不进曲线(project):
    """导入的正文没有 `.原稿` 快照,无从比较(CONTEXT「导入铺底」词条)。"""
    paths.chapter_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.chapter_path(project, 1).write_text("# 标题\n作者自己写的。", encoding="utf-8")
    mark_learned(project, 1)
    assert mirror.curve(project) == []


def test_只改标题不算手改(project):
    """ADR 0009:标题绝不参与文风学习,也不该算进手改量。"""
    paths.snapshot_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.chapter_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.snapshot_path(project, 1).write_text("# 旧标题\n一。二。", encoding="utf-8")
    paths.chapter_path(project, 1).write_text("# 新标题\n一。二。", encoding="utf-8")
    mark_learned(project, 1)
    row = mirror.curve(project)[0]
    assert row["改写率"] == 0.0 and row["增删率"] == 0.0


def test_按章号升序(project):
    for n in (3, 1, 2):
        _chapter(project, n, "一。二。", "壹。二。")
    assert [r["章"] for r in mirror.curve(project)] == [1, 2, 3]


def test_覆盖三个数对得上(project):
    _chapter(project, 1, "一。二。", "壹。二。")                    # 有稿 + 已学
    _chapter(project, 2, "一。二。", "壹。二。", learn=False)        # 有稿,没学
    paths.chapter_path(project, 3).write_text("# 标题\n导入的。", encoding="utf-8")  # 无稿
    cov = mirror.coverage(project)
    assert cov == {"已学": 1, "有稿": 2, "总章": 3}


def test_空书不炸(project):
    assert mirror.curve(project) == []
    assert mirror.coverage(project) == {"已学": 0, "有稿": 0, "总章": 0}


def test_镜台与learn共用同一个句级对齐函数():
    """spec §7 的「共用性」:不是「两边算得一样」,是**两边就是同一个对象**。

    这是防漂最硬的形式(同 `agents._scene_range is artifacts.scene_range` 的做法)。
    镜台的全部说服力来自「它和 learn 学的是同一件事」——一旦有两份实现,这句话就假了。
    """
    from loom import fingerprint
    assert mirror.align_stats is fingerprint.align_stats
