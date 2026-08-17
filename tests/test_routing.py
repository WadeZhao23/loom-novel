"""多供应商模型路由:供应商表、模型软校验、后端构造、config base_url + 双 key 隔离。"""
from __future__ import annotations

import pytest

from loom.backends import (LoomBackendError, _budget_tokens, get_backend, provider_catalog,
                           validate_model)
from loom.config import (Config, key_is_set, load_config, openai_compat_key_is_set,
                         save_config, set_env_key, set_openai_compat_key)


def test_catalog_providers_order():
    ids = [p["id"] for p in provider_catalog()]
    # deepseek 默认第一;国产直连预设凑一组;订阅 CLI 随后;自定义兜底收尾(3.1 扩充)
    assert ids == ["deepseek", "zhipu", "moonshot", "qwen", "doubao", "siliconflow",
                   "claude", "codex", "openai_compat"]
    ds = next(p for p in provider_catalog() if p["id"] == "deepseek")
    assert ds["default_model"] == "deepseek-v4-pro"
    assert any(m["id"] == "deepseek-v4-flash" for m in ds["models"])
    assert any(m["id"] == "deepseek-v4-pro" for m in ds["models"])


def test_budget_tokens_survives_real_thinking_length():
    """真机实测 2026-08-16(v4-flash,样例书《重生记忆》第 3 章的真实 prompt,非流式重放)。

    写手棒(prompt 5964 字):
        6736 (旧代码给的值)→ finish=length,思考  9652 字,正文    0 字
        12288              → finish=length,思考 17289 字,正文    0 字
        16384              → finish=stop,  思考 10057 字,正文 1102 字
        32768              → finish=stop,  思考 19489 字,正文 1055 字
    润色师棒(prompt 5308 字):
        16384              → finish=length,思考【43433】字,正文  0 字   ← 16384 也不够
        32768              → finish=stop,  思考 13084 字,正文 1332 字

    三条结论:
    ① 思考长度方差极大(9.6k~43.4k 字),**没有哪个按 max_chars 现算的公式对每一棒都够** →
       不算了,直接给一个装得下最坏情况的常数。
    ② 旧注释「封顶 8192(DeepSeek 接受的上限)」对 V4 是错的:65536 与 131072 都正常受理。
    ③ 抬上限**零成本**:按实际产出的 token 计费,65536 那次只出了 31 个 token。
    """
    from loom.backends import _budget_tokens
    # 写章/复审/标题——每一步都必须拿到装得下【最坏那次思考】的预算,故是同一个常数
    assert _budget_tokens("deepseek", 1200) == 65536
    assert _budget_tokens("deepseek", 600) == 65536
    assert _budget_tokens("deepseek", None) == 65536
    # 非思考型供应商一律不动:各家输出上限不同,贸然抬高可能被拒
    assert _budget_tokens("zhipu", 800) == int(800 * 2.2)


def test_budget_tokens_deepseek_reserves_thinking_room():
    # 真因:DeepSeek V4 是思考型,小步骤(标题 max_chars=24)旧公式只给 52 → 思考占满 → 空响应。
    # 真机把这里的形状改过一次:曾是「底线+余量、封顶」的算式(6144/8192),现在是一个常数。
    # 原因是思考长度方差太大(实测 9.6k~43.4k 字),没有哪个算式能对每一棒都刚好够。
    assert _budget_tokens("deepseek", 24) == 65536         # 标题这种极短步骤也给满
    assert _budget_tokens("deepseek", 20000) == 65536      # 长章同样是它,不随 max_chars 变


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
