"""S3 Token 计量:complete 返回值加 usage 字段 + usage_history 累积。"""
import pytest

from loom.backends import CompletionResult, Usage


class TestUsageDataclass:
    """Usage 数据类基本功能。"""

    def test_default_all_none(self):
        u = Usage()
        assert u.prompt_tokens is None
        assert u.completion_tokens is None
        assert u.total_tokens is None
        assert bool(u) is False

    def test_from_openai_none(self):
        assert Usage.from_openai(None) is None

    def test_from_openai_valid(self):
        class MockUsage:
            prompt_tokens = 10
            completion_tokens = 20
            total_tokens = 30
        u = Usage.from_openai(MockUsage())
        assert u is not None
        assert u.prompt_tokens == 10
        assert u.completion_tokens == 20
        assert u.total_tokens == 30
        assert bool(u) is True

    def test_bool_partial(self):
        u = Usage(prompt_tokens=100)
        assert bool(u) is True

    def test_add_two_usages(self):
        a = Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        b = Usage(prompt_tokens=5, completion_tokens=10, total_tokens=15)
        c = a + b
        assert c.prompt_tokens == 15
        assert c.completion_tokens == 30
        assert c.total_tokens == 45

    def test_add_with_none_keeps_original(self):
        a = Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        c = a + None
        assert c.prompt_tokens == 10
        assert c.completion_tokens == 20
        assert c.total_tokens == 30

    def test_sum_aggregation(self):
        usages = [
            Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            Usage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
        ]
        total = sum(usages, Usage())  # type: ignore[arg-type]
        assert total.prompt_tokens == 15
        assert total.completion_tokens == 30
        assert total.total_tokens == 45


class TestCompletionResult:
    """CompletionResult 向后兼容性测试。"""

    def test_is_str(self):
        r = CompletionResult("hello")
        assert isinstance(r, str)
        assert r == "hello"
        assert len(r) == 5

    def test_with_usage(self):
        u = Usage(prompt_tokens=10, completion_tokens=20)
        r = CompletionResult("world", usage=u)
        assert r == "world"
        assert r.usage is u
        assert r.usage.prompt_tokens == 10

    def test_without_usage(self):
        r = CompletionResult("test")
        assert r.usage is None

    def test_str_methods_work(self):
        r = CompletionResult("hello world")
        assert r.startswith("hello")
        assert "world" in r
        assert r.split() == ["hello", "world"]
        assert r.strip() == "hello world"

    def test_concat_still_works(self):
        r = CompletionResult("hello")
        combined = r + " world"
        assert isinstance(combined, str)
        assert combined == "hello world"
