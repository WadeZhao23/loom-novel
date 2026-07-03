"""多供应商一等预设(3.1):注册表纯数据扩展 + key 各落各行 + 路由泛化。"""
from __future__ import annotations

from loom.backends import PROVIDERS, get_backend, probe, provider_catalog
from loom.config import Config, provider_key_is_set, set_provider_key

_PRESETS = ["zhipu", "moonshot", "qwen", "doubao", "siliconflow"]


def test_catalog_contains_presets_in_order():
    ids = [p["id"] for p in provider_catalog()]
    for pid in _PRESETS:
        assert pid in ids
    # deepseek 仍是第一位默认;自定义兜底仍在
    assert ids[0] == "deepseek" and "openai_compat" in ids


def test_presets_are_locked_openai_kind_with_unique_key_env():
    envs = []
    for pid in _PRESETS:
        spec = PROVIDERS[pid]
        assert spec["kind"] == "openai" and spec["needs_key"]
        assert spec["base_url_locked"] and spec["base_url"].startswith("https://")
        assert spec["models"] == [], "预设模型列表刻意留空:靠「拉取可用模型」,绝不硬编码白名单"
        assert spec["can_list_models"]
        envs.append(spec["key_env"])
    all_envs = [s.get("key_env") for s in PROVIDERS.values() if s.get("key_env")]
    assert len(all_envs) == len(set(all_envs)), "key_env 必须全表唯一,否则互相覆盖"


def test_provider_key_lands_in_own_env_line(tmp_path):
    set_provider_key(tmp_path, "LOOM_ZHIPU_KEY", "zp-123")
    set_provider_key(tmp_path, "LOOM_MOONSHOT_KEY", "ms-456")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LOOM_ZHIPU_KEY=zp-123" in env and "LOOM_MOONSHOT_KEY=ms-456" in env
    assert provider_key_is_set(tmp_path, "LOOM_ZHIPU_KEY")
    assert not provider_key_is_set(tmp_path, "LOOM_QWEN_KEY")


def test_get_backend_routes_presets_via_openai_compat(monkeypatch):
    monkeypatch.delenv("LOOM_DEMO", raising=False)
    monkeypatch.setenv("LOOM_ZHIPU_KEY", "zp-test")
    be = get_backend(Config(provider="zhipu", model="glm-x"))
    assert type(be).__name__ == "OpenAICompatBackend"
    assert be.provider == "zhipu" and be.model == "glm-x"


def test_probe_presets_key_kind():
    for pid in _PRESETS:
        d = probe(pid)
        assert d["ok"] and d["kind"] == "key"
