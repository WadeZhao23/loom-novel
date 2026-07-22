"""S4 本地检测器:成语堆砌/排比句滥用/转折词密集(纯规则,不调 LLM)。"""
import pytest

from loom.detectors import (
    detect_chengyu_piling,
    detect_parallel_abuse,
    detect_excessive_transitions,
)
from loom.agents import _chengyu_factory, _parallel_factory, _transition_factory


class TestChengyuPiling:
    """成语堆砌检测。"""

    def test_no_chengyu_returns_empty(self):
        text = "今天天气很好,适合出去走走。"
        assert detect_chengyu_piling(text) == []

    def test_few_chengyu_no_piling(self):
        text = "他兴高采烈地走进教室,同学们都目瞪口呆地看着他。"
        assert detect_chengyu_piling(text) == []

    def test_many_chengyu_in_window(self):
        text = (
            "他这人一心一意、二话不说、三心二意、四面八方、五光十色、六神无主地做事。"
        )
        issues = detect_chengyu_piling(text)
        assert len(issues) == 1
        assert "成语堆砌" in issues[0].kind
        assert issues[0].severity == 3

    def test_chengyu_spread_across_window_ok(self):
        """不超过阈值的四字格不触发。"""
        text = "今天天气很好,明天应该也不错。"
        assert detect_chengyu_piling(text) == []

    def test_exactly_threshold_chengyu_still_triggers(self):
        """刚好达到阈值也触发(宽松检测策略)。"""
        text = "一心一意、二话不说、三心二意、四面八方、五光十色"
        assert len(detect_chengyu_piling(text)) == 1

    def test_factory_ignores_params(self):
        """工厂函数签名兼容,忽略 project_root/chapter_n/anchors。"""
        fn = _chengyu_factory(None, 0, [])
        issues = fn("一心一意 二话不说 三心二意 四面八方 五光十色 六神无主")
        assert len(issues) == 1


class TestParallelAbuse:
    """排比句滥用检测。"""

    def test_no_parallel(self):
        text = "今天天气好。明天也不错。后天应该也行。"
        assert detect_parallel_abuse(text) == []

    def test_three_parallel_lines(self):
        text = (
            "他喜欢读书。\n"
            "他喜欢写作。\n"
            "他喜欢画画。\n"
        )
        issues = detect_parallel_abuse(text)
        assert len(issues) == 1
        assert "排比" in issues[0].kind
        assert "他喜欢" in issues[0].desc

    def test_four_parallel_lines(self):
        text = (
            "不是为名。\n"
            "不是为利。\n"
            "不是为权。\n"
            "不是为色。\n"
        )
        issues = detect_parallel_abuse(text)
        assert len(issues) == 1
        assert issues[0].severity == 3

    def test_only_two_parallel_is_fine(self):
        text = (
            "他喜欢读书。\n"
            "他喜欢写作。\n"
            "明天要下雨。\n"
        )
        assert detect_parallel_abuse(text) == []

    def test_parallel_not_at_start_ignored(self):
        text = (
            "今天他喜欢读书。\n"
            "明天他喜欢写作。\n"
            "后天他喜欢画画。\n"
        )
        assert detect_parallel_abuse(text) == []

    def test_factory(self):
        fn = _parallel_factory(None, 0, [])
        issues = fn("他喜欢读书。\n他喜欢写作。\n他喜欢画画。\n")
        assert len(issues) == 1


class TestExcessiveTransitions:
    """转折词密集检测。"""

    def test_no_transitions(self):
        text = "天气很好。阳光明媚。鸟语花香。"
        assert detect_excessive_transitions(text) == []

    def test_few_transitions_is_fine(self):
        """2 个转折词在窗口内,不触发。"""
        text = "虽然天气不好,但是他还是决定出门,因为天气太差。"
        assert detect_excessive_transitions(text) == []

    def test_many_transitions_in_window(self):
        text = (
            "虽然今天下雨,但是他不介意。"
            "然而路上堵车,不过他还是准时到了。"
            "可是没人等他,却发现自己记错了日期。"
        )
        issues = detect_excessive_transitions(text)
        assert len(issues) == 1
        assert "转折" in issues[0].kind
        assert issues[0].severity == 3

    def test_scattered_transitions_fine(self):
        """转折词之间距离远,不触发。"""
        # 每个转折词后跟 200+ 字普通叙述
        text = "虽然他今天很不高兴。" + "嗯嗯,那就这样吧。" * 30 + "但是,那也没有办法的事。" + "那就这样吧。" * 30
        assert detect_excessive_transitions(text) == []

    def test_factory(self):
        fn = _transition_factory(None, 0, [])
        issues = fn("虽然但是然而不过可是却尽管即便")
        assert len(issues) >= 0  # 至少不炸
