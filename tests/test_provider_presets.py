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


# ---- S7c: capability 字段化 + CLI 错误 code 对齐 ----

def test_capability_fields_drive_dispatch():
    from loom.backends import PROVIDERS, _budget_tokens
    # deepseek 声明思考型 → 底线预算;国产预设未声明 → 走通用换算(与旧 provider==deepseek 分支等价)
    assert PROVIDERS["deepseek"].get("thinking_budget") is True
    assert PROVIDERS["deepseek"].get("error_family") == "deepseek"
    assert not PROVIDERS["zhipu"].get("thinking_budget")
    assert _budget_tokens("deepseek", 24) == 6144           # 思考型底线
    assert _budget_tokens("zhipu", 24) == int(24 * 2.2)     # 非思考型:通用换算,不吃底线


def test_error_family_selects_deepseek_mapping(monkeypatch):
    from loom.backends import OpenAICompatBackend
    from loom.config import Config
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    monkeypatch.setenv("LOOM_ZHIPU_KEY", "zp-x")
    ds = OpenAICompatBackend(Config(provider="deepseek", model="deepseek-v4-pro"), "deepseek")
    zp = OpenAICompatBackend(Config(provider="zhipu", model="glm-x"), "zhipu")
    assert ds._empty_code == "deepseek_empty_response"      # error_family=deepseek
    assert zp._empty_code == "model_empty_response"          # 缺省 generic


def test_cli_backends_raises_carry_codes():
    # 三处此前裸 raise 的 CLI 错误现在都带 code(前端可差异化提示);错误目录条目都在
    from loom.errors import render
    assert "claude" in render("claude_call_failed")
    assert "codex" in render("codex_call_failed")
