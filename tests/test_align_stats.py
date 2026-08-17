"""句级对齐的计数出口:`_aligned_signal`(喂 prompt)与镜台(算比率)共用同一份。

绝不建第二个句级对齐——否则曲线和 learn 学到的东西会对不上,而镜台的全部说服力
就来自「它和 learn 学的是同一件事」。
"""
from __future__ import annotations

from loom import fingerprint


def test_逐句改写只算改写不算增删():
    ai = "他没说话。风停了。刀收回鞘。"
    edited = "他不吭声。风停了。刀收回鞘。"
    s = fingerprint.align_stats(ai, edited)
    assert s["总句数"] == 3
    assert s["改写句数"] == 1
    assert s["增删句数"] == 0


def test_纯新增只算增删():
    ai = "他没说话。风停了。"
    edited = "他没说话。风停了。她笑了一下。"
    s = fingerprint.align_stats(ai, edited)
    assert s["总句数"] == 2
    assert s["改写句数"] == 0
    assert s["增删句数"] == 1


def test_纯删除也算增删():
    ai = "他没说话。风停了。刀收回鞘。"
    edited = "他没说话。刀收回鞘。"
    s = fingerprint.align_stats(ai, edited)
    assert s["改写句数"] == 0
    assert s["增删句数"] == 1


def test_改写块取AI侧句数():
    """`replace` 块两侧句数可以不等(作者把一句拆成两句)。分子取 AI 侧,
    才和分母(AI 稿总句数)同侧,这个比率才读得懂。"""
    ai = "他没说话风停了刀收回鞘。"          # 1 句
    edited = "他没说话。风停了。刀收回鞘。"   # 3 句
    s = fingerprint.align_stats(ai, edited)
    assert s["总句数"] == 1
    assert s["改写句数"] == 1        # 取 AI 侧的 1,不是作者侧的 3


def test_没改动时全是零():
    ai = edited = "他没说话。风停了。"
    s = fingerprint.align_stats(ai, edited)
    assert s["改写句数"] == 0 and s["增删句数"] == 0 and s["总句数"] == 2


def test_空稿不炸():
    s = fingerprint.align_stats("", "")
    assert s == {"改写句数": 0, "增删句数": 0, "总句数": 0,
                 "rewrites": [], "removed": [], "added": []}
