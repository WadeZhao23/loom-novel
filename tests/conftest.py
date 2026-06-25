"""测试夹具:一个临时 loom 项目 + 可编程的假后端。"""
from __future__ import annotations

from pathlib import Path

import pytest

from loom.scaffold import init as scaffold_init


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
