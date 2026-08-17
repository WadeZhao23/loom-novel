"""篇幅校准:从作者【已写章节】实测段落节奏,把「写 N 字」换成「写 P 段」。

背景:大模型数不准字数(LIFEBench 等基准的普遍结论),但对**小整数的结构计数**跟随得好得多。
Loom 的可用单位从粗到细是 场次(2-6)→ 段落(几十)→ 句子(近百)→ 字(上千)。
场次已经在细纲里了;这里补段落这一层。

换算系数**不写死**,从这本书已有正文现算——不同作者的段落节奏差很多(样例书实测 18.9 字/段),
写死一个常数就等于把别人的节奏塞给他。顺带:这个系数本身就是文风的一部分。
"""
from __future__ import annotations

from loom import lengthcal


def test_从已写章节实测每段字数(project):
    (project / "正文").mkdir(exist_ok=True)
    # 两章,各 8 段、每段 10 字 → 10.0 字/段
    ch = "\n\n".join(["一二三四五六七八九十"] * 8)
    (project / "正文/第1章.md").write_text("# 标题\n" + ch, encoding="utf-8")
    (project / "正文/第2章.md").write_text("# 标题\n" + ch, encoding="utf-8")
    assert abs(lengthcal.chars_per_para(project) - 10.0) < 0.01


def test_标题不算进段落节奏(project):
    """标题是 H1、不是正文段落,算进去会把系数拉偏(且它绝不参与文风,ADR 0009)。"""
    (project / "正文").mkdir(exist_ok=True)
    body = "\n\n".join(["一二三四五六七八九十"] * 8)
    (project / "正文/第1章.md").write_text("# 一个标题\n" + body, encoding="utf-8")
    (project / "正文/第2章.md").write_text("# 另一个标题\n" + body, encoding="utf-8")
    assert abs(lengthcal.chars_per_para(project) - 10.0) < 0.01


def test_样本不够就不给系数(project):
    """新书没有正文 → 返回 0 = 没有校准。宁可不给结构目标,也不拿一个编的系数糊弄。"""
    assert lengthcal.chars_per_para(project) == 0.0


def test_段落目标按实测系数派生(project):
    (project / "正文").mkdir(exist_ok=True)
    ch = "\n\n".join(["一二三四五六七八九十"] * 8)
    for n in (1, 2):
        (project / f"正文/第{n}章.md").write_text("# 标题\n" + ch, encoding="utf-8")
    assert lengthcal.para_target(project, 1200) == 120      # 1200 / 10
    assert lengthcal.para_target(project, 0) == 0


def test_没有校准时段落目标为0(project):
    assert lengthcal.para_target(project, 1200) == 0


def test_太短的章不进节奏统计(project):
    """少于 6 段的章要么是残章、要么短到节奏不具代表性,算进去会把系数带歪。
    这条护栏是有意的,不是碰巧——两章都太短 → 样本不足 → 不给系数。"""
    (project / "正文").mkdir(exist_ok=True)
    for n in (1, 2):
        (project / f"正文/第{n}章.md").write_text(
            "# 标题\n" + "\n\n".join(["一二三四五六七八九十"] * 3), encoding="utf-8")
    assert lengthcal.chars_per_para(project) == 0.0
