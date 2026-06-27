"""多供应商模型路由:供应商表、模型软校验、后端构造、config base_url + 双 key 隔离。"""
from __future__ import annotations

import pytest

from loom.backends import (LoomBackendError, _budget_tokens, get_backend, provider_catalog,
                           validate_model)
from loom.config import (Config, key_is_set, load_config, openai_compat_key_is_set,
                         save_config, set_env_key, set_openai_compat_key)


def test_catalog_has_four_providers():
    ids = [p["id"] for p in provider_catalog()]
    assert ids == ["deepseek", "claude", "codex", "openai_compat"]
    ds = next(p for p in provider_catalog() if p["id"] == "deepseek")
    assert ds["default_model"] == "deepseek-v4-pro"
    assert any(m["id"] == "deepseek-v4-flash" for m in ds["models"])
    assert any(m["id"] == "deepseek-v4-pro" for m in ds["models"])


def test_budget_tokens_deepseek_reserves_thinking_room():
    # 真因:DeepSeek V4 是思考型,小步骤(标题 max_chars=24)旧公式只给 52 → 思考占满 → 空响应。
    # 修复:DeepSeek 给 6144 底线 + 思考余量,封顶 8192。
    assert _budget_tokens("deepseek", 24) == 6144          # 标题/短步骤拿到底线,不再被思考饿死
    assert _budget_tokens("deepseek", 800) == 6144         # base 1760+4096=5856 < 底线 → 6144
    assert _budget_tokens("deepseek", 2000) == 8192        # base 4400+4096=8496 → 封顶 8192
    assert _budget_tokens("deepseek", None) == 8192


def test_budget_tokens_other_providers_unchanged():
    # 别家 OpenAI 兼容供应商输出上限各不同,维持原 max_chars*2.2,不贸然抬高
    assert _budget_tokens("openai_compat", 24) == int(24 * 2.2)
    assert _budget_tokens("openai_compat", 800) == int(800 * 2.2)
    assert _budget_tokens("openai_compat", None) == 2048


def test_validate_model_catches_the_v4flash_mistake():
    # 用户实报的那次:把裸名 v4-flash 填进 deepseek
    warn = validate_model("deepseek", "v4-flash")
    assert warn and "deepseek-v4-flash" in warn
    assert validate_model("deepseek", "deepseek-v4-flash") is None
    assert validate_model("deepseek", "deepseek-v4-pro") is None
    assert validate_model("openai_compat", "glm-4-flash") is None   # 自定义供应商不拦
    assert validate_model("claude", "opus") is None


def test_openai_compat_needs_model(monkeypatch):
    monkeypatch.delenv("LOOM_OPENAI_COMPAT_KEY", raising=False)
    with pytest.raises(LoomBackendError) as e:
        get_backend(Config(provider="openai_compat", model="", base_url="https://x/v1"))
    assert e.value.code == "model_name_missing"


def test_openai_compat_needs_base_url(monkeypatch):
    monkeypatch.delenv("LOOM_OPENAI_COMPAT_KEY", raising=False)
    with pytest.raises(LoomBackendError) as e:
        get_backend(Config(provider="openai_compat", model="glm-4-flash", base_url=""))
    assert e.value.code == "openai_compat_base_url_missing"


def test_openai_compat_needs_key(monkeypatch):
    monkeypatch.delenv("LOOM_OPENAI_COMPAT_KEY", raising=False)
    with pytest.raises(LoomBackendError) as e:
        get_backend(Config(provider="openai_compat", model="glm-4-flash", base_url="https://x/v1"))
    assert e.value.code == "openai_compat_key_missing"


def test_deepseek_needs_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(LoomBackendError) as e:
        get_backend(Config(provider="deepseek", model="deepseek-v4-flash"))
    assert e.value.code == "deepseek_key_missing"


def test_base_url_persists_only_for_openai_compat(project):
    save_config(project, Config(provider="openai_compat", model="glm-4-flash",
                                base_url="https://open.bigmodel.cn/api/paas/v4", title="t", chapter_chars=800))
    assert load_config(project).base_url == "https://open.bigmodel.cn/api/paas/v4"
    # 切回 deepseek 重写 toml → 不再有 base_url 行,load 兜底空串
    save_config(project, Config(provider="deepseek", model="deepseek-v4-flash", title="t", chapter_chars=800))
    assert load_config(project).base_url == ""


def test_two_keys_live_side_by_side(project):
    set_env_key(project, "sk-deepseek-xxx")
    set_openai_compat_key(project, "sk-compat-yyy")
    assert key_is_set(project) and openai_compat_key_is_set(project)
    env = (project / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-deepseek-xxx" in env
    assert "LOOM_OPENAI_COMPAT_KEY=sk-compat-yyy" in env
    # 再覆盖 deepseek 那行,不该动到自定义那行
    set_env_key(project, "sk-deepseek-new")
    env2 = (project / ".env").read_text(encoding="utf-8")
    assert "sk-deepseek-new" in env2 and "sk-compat-yyy" in env2
