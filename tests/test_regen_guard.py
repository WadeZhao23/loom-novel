"""S4b:regen_outline 每棒非空闸——设定师空产物即刹车,不再静默喂大纲师空转。"""
from __future__ import annotations

import pytest

from loom.agents import regen_outline
from loom.backends import LoomBackendError
from loom.config import load_config
from tests.conftest import FakeBackend


def test_regen_first_step_empty_halts(project):
    be = FakeBackend(lambda system, user: "")   # 设定师就返回空
    with pytest.raises(LoomBackendError):
        regen_outline(project, 1, be, load_config(project))
    assert len(be.calls) == 1, "设定师空产物必须当场刹车,不许再调大纲师"
