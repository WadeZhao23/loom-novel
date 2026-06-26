"""粗粒度按角色分模型(rank 5)+ 信息边界 rubric(rank 6)。"""
from __future__ import annotations

import pytest

from loom import gates
from loom.backends import cheap_backend
from loom.config import Config


def test_cheap_backend_off_when_unset():
    assert cheap_backend(Config(model="deepseek-v4-flash")) is None


def test_cheap_backend_off_when_same_as_main():
    assert cheap_backend(Config(model="m", cheap_model="m")) is None


def test_cheap_backend_builds_when_different(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOOM_DEMO", "1")  # demo 后端不需要 key,只验证「确实另建了一个后端」
    b = cheap_backend(Config(model="deepseek-v4-pro", cheap_model="deepseek-v4-flash"))
    assert b is not None and hasattr(b, "complete")


def test_critic_backend_routes_critic_only():
    # 复审走 critic_backend,回炉走 backend —— 验证两路确实分流
    calls = {"critic": 0, "revise": 0}

    class Tagging:
        def __init__(self, tag): self.tag = tag
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            calls[self.tag] += 1
            return "- 设定漂移 | 有问题 | 证据:\"x\"" if self.tag == "critic" else "改好的整章正文。"

    res = gates.run_gate(
        Tagging("revise"), label="质检", owner_role="编辑",
        critic_system="c", revise_system="r", draft="原稿", knowledge="", produces="本章改稿",
        rounds=2, max_chars=2000, critic_backend=Tagging("critic"),
    )
    assert calls["critic"] >= 1   # 复审用了便宜后端
    assert calls["revise"] >= 1   # 回炉用了主后端
    assert res.text == "改好的整章正文。"


def test_info_boundary_rubric_present():
    # rank 6:信息边界进了质检复审 rubric
    assert "信息边界" in gates.CRITIC_质检
