""".env 存 API key:落盘后只留属主读写(0600,仅 POSIX;Windows 无此权限位跳过)。"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from loom.config import set_env_key, set_openai_compat_key

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Windows 无 POSIX 权限位")


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_env_created_with_0600(tmp_path: Path):
    set_env_key(tmp_path, "sk-test")
    assert _mode(tmp_path / ".env") == 0o600


def test_env_rewrite_keeps_0600(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=old\n", encoding="utf-8")
    env.chmod(0o644)                      # 老项目里已经是宽权限的 .env,重写后也要收紧
    set_openai_compat_key(tmp_path, "sk-other")
    assert _mode(env) == 0o600
    text = env.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=old" in text and "LOOM_OPENAI_COMPAT_KEY=sk-other" in text
