"""OpenAI 兼容后端的显式超时:SDK 默认 600s 太长,挂了要等 10 分钟;超时映射成友好错误。"""
from __future__ import annotations

import pytest

from loom.backends import _deepseek_error, _openai_compat_error


def test_client_has_explicit_timeout(monkeypatch):
    pytest.importorskip("openai")
    from loom.backends import OpenAICompatBackend
    from loom.config import Config

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    be = OpenAICompatBackend(Config(provider="deepseek", model="deepseek-v4-pro"), "deepseek")
    t = be._client.timeout
    assert t.connect == 10.0
    assert t.read == 120.0                      # 非流式整体 120s,不再是 SDK 默认 600s
    assert be._stream_timeout.read == 300.0     # 流式按 chunk 间隔计 read,放宽
    assert be._stream_timeout.connect == 10.0


def test_timeout_maps_to_friendly_error():
    err = _deepseek_error(Exception("Request timed out."))
    assert err.code == "deepseek_timeout"
    assert "超时" in str(err)

    err2 = _openai_compat_error(Exception("Request timed out."))
    assert err2.code == "model_timeout"
    assert "超时" in str(err2)


def test_other_errors_still_map_as_before():
    assert _deepseek_error(Exception("rate limit exceeded")).code == "deepseek_rate_limited"
    assert _deepseek_error(Exception("boom")).code == "deepseek_call_failed"
    assert _openai_compat_error(Exception("boom")).code == "model_call_failed"
