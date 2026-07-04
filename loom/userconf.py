"""用户级默认后端:连一次(接入模型),全局记住;新建的每本书自动继承。

存在用户级本地目录(~/.loom,LOOM_HOME 可覆盖)——纯本地文件、非服务器,守 Loom
「无服务器、稿子不离机」。两份:
- backend.json:provider / model / base_url(非密文,给新书铺 loom.toml)。
- .env(0600):各供应商的 key,与项目 .env 同格式;load_config 已把它当回退加载,
  所以新书不填 key 也能用默认 key(继承),某本单独填了就覆盖。key 不拷进书 .env,
  于是 zip 分享某本书永远不含 key。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as _cfg
from .backends import PROVIDERS
from .config import Config, load_config, save_config, set_provider_key, user_config_dir
from .fsutil import atomic_write_text

_BACKEND_JSON = "backend.json"


def _json_path() -> Path:
    return user_config_dir() / _BACKEND_JSON


def load_default_backend() -> dict:
    """读用户级默认后端(provider/model/base_url);没设过返回 {}。"""
    p = _json_path()
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:   # 坏 JSON 当没设(极简:不做迁移)
        return {}


def has_default() -> bool:
    return bool(load_default_backend().get("provider"))


def save_default_backend(provider: str, model: str, base_url: str = "", api_key: str | None = None) -> None:
    """保存用户级默认后端;api_key 给了就按该供应商的 key_env 落进 ~/.loom/.env(0600)。"""
    d = {"provider": provider, "model": model, "base_url": base_url or ""}
    atomic_write_text(_json_path(), json.dumps(d, ensure_ascii=False, indent=2))
    if api_key:
        key_env = (PROVIDERS.get(provider) or {}).get("key_env")
        if key_env:
            set_provider_key(user_config_dir(), key_env, api_key.strip())


def default_key_is_set(provider: str) -> bool:
    key_env = (PROVIDERS.get(provider) or {}).get("key_env")
    return bool(key_env) and _cfg._env_var_set(user_config_dir(), key_env)


def apply_default_to_new_book(root: Path) -> None:
    """新书创建后铺上用户级默认后端:把 provider/model/base_url 写进该书 loom.toml。
    key 不拷(靠 load_config 的用户级回退继承),privacy 不变。没设默认则什么都不做。"""
    d = load_default_backend()
    provider = d.get("provider")
    if not provider:
        return
    cfg = load_config(root)   # 保留书自己的 title/字数等,只覆盖后端三项
    save_config(root, Config(
        provider=provider, model=d.get("model", ""), base_url=d.get("base_url", ""),
        cheap_model=cfg.cheap_model, title=cfg.title,
        chapter_chars=cfg.chapter_chars, gate_rounds=cfg.gate_rounds,
        foreshadow_distance=cfg.foreshadow_distance,
    ))
