"""learn 的句级切分:句末标点后紧跟的收尾引号并入本句;连续标点(!?/……)不拆——
否则对白密集章会被切成残句,learn 的改写对齐信号被打碎。"""
from __future__ import annotations

from loom.fingerprint import _segment


def test_segment_plain_sentences():
    assert _segment("他走了。她没追。") == ["他走了。", "她没追。"]


def test_segment_closing_straight_quote_stays_with_sentence():
    assert _segment('他说:"好的。"然后离开。') == ['他说:"好的。"', "然后离开。"]


def test_segment_closing_cjk_quotes_stay_with_sentence():
    assert _segment("他说:「好的。」然后离开。") == ["他说:「好的。」", "然后离开。"]
    assert _segment("他说:“好的。”然后离开。") == ["他说:“好的。”", "然后离开。"]
    assert _segment("他说:『好的!』然后离开。") == ["他说:『好的!』", "然后离开。"]


def test_segment_consecutive_punct_not_split():
    assert _segment("真的吗!?我不信……你再说一遍。") == ["真的吗!?", "我不信……", "你再说一遍。"]


def test_segment_newline_splits_and_drops_blank():
    assert _segment("第一行\n\n第二行。") == ["第一行", "第二行。"]


def test_segment_trailing_text_without_punct_kept():
    assert _segment("他停了下来。风还在吹") == ["他停了下来。", "风还在吹"]
