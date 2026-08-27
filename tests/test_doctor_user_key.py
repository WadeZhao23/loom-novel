"""自检认的 key 范围必须和 `load_config` 一致——否则它照出的是一个不存在的问题。

真机实测 2026-08-26:用户级默认 key(`~/.loom/.env`)与它的自检漏洞是同一个 commit
(b3adc02「接入优先 onboarding」)一起发的。作者按那个功能配好全局 key、写章也确实跑得通,
但每开一本书点「自检」都被告知「DEEPSEEK_API_KEY ✗」,修复提示还让他去项目 .env 补一行
——正是那个功能要免掉的动作。
"""
from __future__ import annotations

import pytest

from loom import config as cfgmod
from loom.config import key_is_set, openai_compat_key_is_set


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    """把用户级配置目录钉到 tmp,别碰真的 ~/.loom。"""
    home = tmp_path / "loomhome"
    home.mkdir()
    monkeypatch.setenv("LOOM_HOME", str(home))
    return home


def test_只有用户级key时自检也认(project, user_home):
    """这条就是真机撞上的那一幕:项目里没有 .env,全局配了 key。"""
    assert not (project / ".env").exists()
    (user_home / ".env").write_text("DEEPSEEK_API_KEY=sk-global\n", encoding="utf-8")
    assert key_is_set(project) is True


def test_两处都没有才算没配(project, user_home):
    (user_home / ".env").write_text("# 空的\n", encoding="utf-8")
    assert key_is_set(project) is False


def test_项目级照旧认(project, user_home):
    (project / ".env").write_text("DEEPSEEK_API_KEY=sk-book\n", encoding="utf-8")
    assert key_is_set(project) is True


def test_项目里写成空值不该盖掉用户级(project, user_home):
    """`load_config` 是两次 override=True(项目在后=项目赢),但 dotenv 的空值不会顶掉已有值。
    自检要跟它同口径:项目那行是空的,就继续看用户级,别报「没配」。"""
    (project / ".env").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    (user_home / ".env").write_text("DEEPSEEK_API_KEY=sk-global\n", encoding="utf-8")
    assert key_is_set(project) is True


def test_用户级env读不了时不抛穿(project, user_home):
    """编码坏了/权限没了不该让整个自检崩——自检是只读、绝不抛的。"""
    (user_home / ".env").write_bytes(b"\xff\xfe")
    assert key_is_set(project) is False       # 当它没有,不是抛异常


def test_openai_compat那把key同样口径(project, user_home):
    (user_home / ".env").write_text("LOOM_OPENAI_COMPAT_KEY=sk-global\n", encoding="utf-8")
    assert openai_compat_key_is_set(project) is True


def test_doctor整张表不再假报(project, user_home, monkeypatch):
    """收口:走真正的 `run_checks`,确认那一行是 ok 的。"""
    from loom.doctor import run_checks
    (user_home / ".env").write_text("DEEPSEEK_API_KEY=sk-global\n", encoding="utf-8")
    row = next(c for c in run_checks(project) if c.name.startswith("DEEPSEEK_API_KEY"))
    assert row.ok is True, f"自检仍在假报:{row.missing}"


def test_自检与load_config永不打架(project, user_home):
    """真正的不变量:自检说「配了」当且仅当 load_config 之后环境里真有值。"""
    import os
    (user_home / ".env").write_text("DEEPSEEK_API_KEY=sk-global\n", encoding="utf-8")
    monkey = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        cfgmod.load_config(project)
        assert bool(os.environ.get("DEEPSEEK_API_KEY")) == key_is_set(project)
    finally:
        if monkey is not None:
            os.environ["DEEPSEEK_API_KEY"] = monkey
        else:
            os.environ.pop("DEEPSEEK_API_KEY", None)
