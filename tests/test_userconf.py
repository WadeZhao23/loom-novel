"""用户级默认后端:连一次全局记住 + 新书继承 + key 回退(不拷进书,privacy 不变)。"""
from __future__ import annotations

from loom import userconf
from loom.config import (key_available, load_config, set_provider_key, user_config_dir)


def test_save_and_load_default_backend():
    assert not userconf.has_default()
    userconf.save_default_backend("deepseek", "deepseek-v4-pro", api_key="sk-abc")
    d = userconf.load_default_backend()
    assert d["provider"] == "deepseek" and d["model"] == "deepseek-v4-pro"
    assert userconf.has_default()
    assert userconf.default_key_is_set("deepseek")
    assert not userconf.default_key_is_set("zhipu")


def test_new_book_inherits_default_backend_without_copying_key(project):
    # 用户级默认 = 智谱 + key
    userconf.save_default_backend("zhipu", "glm-x", api_key="zp-xyz")
    userconf.apply_default_to_new_book(project)
    cfg = load_config(project)
    assert cfg.provider == "zhipu" and cfg.model == "glm-x"          # loom.toml 继承了默认后端
    assert key_available(project, "LOOM_ZHIPU_KEY")                   # key 可用(靠用户级回退)
    # 但 key 没拷进书 .env —— zip 分享这本书不含 key
    book_env = project / ".env"
    assert not book_env.exists() or "zp-xyz" not in book_env.read_text(encoding="utf-8")


def test_book_key_overrides_user_default(project):
    userconf.save_default_backend("deepseek", "deepseek-v4-pro", api_key="sk-user-default")
    set_provider_key(project, "DEEPSEEK_API_KEY", "sk-book-specific")
    load_config(project)   # 触发 .env 回退+覆盖加载
    import os
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-book-specific"  # 书级覆盖用户级


def test_apply_default_noop_when_unset(project):
    before = (project / "loom.toml").read_text(encoding="utf-8")
    userconf.apply_default_to_new_book(project)   # 没设默认 → 什么都不改
    assert (project / "loom.toml").read_text(encoding="utf-8") == before


def test_key_available_falls_back_to_user(project):
    assert not key_available(project, "LOOM_MOONSHOT_KEY")
    set_provider_key(user_config_dir(), "LOOM_MOONSHOT_KEY", "ms-1")   # 只在用户级设
    assert key_available(project, "LOOM_MOONSHOT_KEY")                 # 本书就能用(继承)
