"""测试夹具:一个临时 loom 项目 + 可编程的假后端。"""
from __future__ import annotations

from pathlib import Path

import pytest

from loom.scaffold import init as scaffold_init


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path_factory, monkeypatch):
    """把用户级配置(~/.loom 默认后端/默认 key)指向临时目录,防开发机的真 ~/.loom 泄漏进测试。"""
    monkeypatch.setenv("LOOM_HOME", str(tmp_path_factory.mktemp("loom_home")))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """离线铺一个真实项目骨架(含 agents / 外置大脑 / 中性默认指纹)。"""
    return scaffold_init("测试书", parent=tmp_path)


class FakeBackend:
    """按 (system, user) -> str 的回调产出。on_chunk 给了就回放一次,够流式路径冒烟。"""

    def __init__(self, responder) -> None:
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
        self.calls.append((system, user))
        out = self.responder(system, user) if callable(self.responder) else self.responder
        if on_chunk and out:
            on_chunk(out)
        return out


def const(value: str):
    return lambda system, user: value
