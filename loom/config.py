"""读项目根的 loom.toml + .env。"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .fsutil import atomic_write_text


_APPLIED_DEEPSEEK_KEY: str | None = None
_DEEPSEEK_KEY_OWNER_ENV = "_LOOM_DEEPSEEK_KEY_OWNER"
_APPLIED_OPENAI_COMPAT_KEY: str | None = None
_OPENAI_COMPAT_KEY_OWNER_ENV = "_LOOM_OPENAI_COMPAT_KEY_OWNER"


@dataclass
class Config:
    provider: str = "deepseek"        # deepseek | claude | codex | openai_compat
    model: str = "deepseek-v4-pro"    # DeepSeek V4 默认 pro(更强);更快更省可填 v4-flash。都是思考型,见 backends 预算
    cheap_model: str = ""              # 可选:复审/写后摘要这类「评估」调用走的便宜模型(同供应商换 model);空=全用主模型
    base_url: str = ""                 # 仅 openai_compat 有意义:第三方 OpenAI 兼容供应商的接口地址
    title: str = "我的第一本书"
    chapter_chars: int = 800           # 终稿目标字数;中间工序自然更短
    gate_rounds: int = 1               # 质检/去AI味 复审轮数:1=只诊断列留痕(默认,不替作者改稿)、≥2 才自动回炉重写、0=关闭(见 ADR-0006)
    foreshadow_distance: int = 8       # 伏笔悬空提醒章距:埋设超过这么多章仍无推进/回收 → 写第N章时进留痕提醒(纯提示、不回炉、不阻断);0=关


def find_project_root(start: Path | None = None) -> Path:
    """从当前目录向上找含 loom.toml 的项目根。"""
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / "loom.toml").exists():
            return d
    from .errors import render
    raise FileNotFoundError(render("project_root_not_found"))


def global_config_dir() -> Path:
    """Return the per-user Loom config directory."""
    return Path.home() / ".loom"


def global_env_path() -> Path:
    """Return the per-user Loom dotenv path."""
    return global_config_dir() / ".env"


def _read_env_var(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    value = dotenv_values(path).get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _replace_env_var(path: Path, name: str, value: str) -> None:
    target_assignment = re.compile(rf"^(?:export\s+)?{re.escape(name)}\s*=")

    def is_target_assignment(line: str) -> bool:
        return bool(target_assignment.match(line.strip()))

    lines: list[str] = []
    if path.exists():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not is_target_assignment(line)
        ]
    lines.append(f"{name}={value}")
    atomic_write_text(path, "\n".join(lines) + "\n")


def _loom_owns_process_key(process_key: str) -> bool:
    return (
        bool(process_key)
        and _APPLIED_DEEPSEEK_KEY is not None
        and process_key == _APPLIED_DEEPSEEK_KEY
        and os.environ.get(_DEEPSEEK_KEY_OWNER_ENV) == "1"
    )


def resolve_deepseek_key(project_root: Path) -> tuple[str | None, str]:
    """Resolve the effective DeepSeek key without exposing it in API state."""
    process_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if process_key and not _loom_owns_process_key(process_key):
        return process_key, "process"

    project_key = _read_env_var(project_root / ".env", "DEEPSEEK_API_KEY")
    if project_key:
        return project_key, "project"

    global_key = _read_env_var(global_env_path(), "DEEPSEEK_API_KEY")
    if global_key:
        return global_key, "global"

    return None, "none"


def apply_deepseek_key(project_root: Path) -> str:
    """Apply the resolved DeepSeek key to os.environ for existing backends."""
    global _APPLIED_DEEPSEEK_KEY
    key, source = resolve_deepseek_key(project_root)
    if key:
        os.environ["DEEPSEEK_API_KEY"] = key
        if source == "process":
            _APPLIED_DEEPSEEK_KEY = None
            os.environ.pop(_DEEPSEEK_KEY_OWNER_ENV, None)
        else:
            _APPLIED_DEEPSEEK_KEY = key
            os.environ[_DEEPSEEK_KEY_OWNER_ENV] = "1"
    else:
        if _loom_owns_process_key(os.environ.get("DEEPSEEK_API_KEY", "").strip()):
            os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop(_DEEPSEEK_KEY_OWNER_ENV, None)
        _APPLIED_DEEPSEEK_KEY = None
    return source


def _loom_owns_openai_compat_key(process_key: str) -> bool:
    return (
        bool(process_key)
        and _APPLIED_OPENAI_COMPAT_KEY is not None
        and process_key == _APPLIED_OPENAI_COMPAT_KEY
        and os.environ.get(_OPENAI_COMPAT_KEY_OWNER_ENV) == "1"
    )


def apply_openai_compat_key(project_root: Path) -> str:
    """Apply this project's OpenAI-compatible provider key when present."""
    global _APPLIED_OPENAI_COMPAT_KEY
    name = "LOOM_OPENAI_COMPAT_KEY"
    process_key = os.environ.get(name, "").strip()
    project_key = _read_env_var(project_root / ".env", name)
    if project_key:
        os.environ[name] = project_key
        _APPLIED_OPENAI_COMPAT_KEY = project_key
        os.environ[_OPENAI_COMPAT_KEY_OWNER_ENV] = "1"
        return "project"
    if _loom_owns_openai_compat_key(process_key):
        os.environ.pop(name, None)
        process_key = ""
    os.environ.pop(_OPENAI_COMPAT_KEY_OWNER_ENV, None)
    _APPLIED_OPENAI_COMPAT_KEY = None
    return "process" if process_key else "none"


def load_config(project_root: Path) -> Config:
    # Explicitly apply API keys so switching projects does not leak a previous project's key.
    apply_deepseek_key(project_root)
    apply_openai_compat_key(project_root)
    try:
        data = tomllib.loads((project_root / "loom.toml").read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"loom.toml 格式有误:{e}") from e
    backend = data.get("backend", {})
    novel = data.get("novel", {})
    gate = data.get("gate", {})
    return Config(
        provider=backend.get("provider", "deepseek"),
        model=backend.get("model", "deepseek-v4-pro"),
        cheap_model=backend.get("cheap_model", ""),    # 老 toml 没这行 → 空串=不开,行为不变
        base_url=backend.get("base_url", ""),          # 老 toml 没这行 → 兜底空串,无需迁移
        title=novel.get("title", "我的第一本书"),
        chapter_chars=int(novel.get("章节字数", novel.get("chapter_chars", 800))),
        gate_rounds=int(gate.get("轮数", gate.get("rounds", 1))),
        foreshadow_distance=int(gate.get("伏笔提醒章距", gate.get("foreshadow_distance", 8))),
    )


def _set_env_var(project_root: Path, name: str, value: str) -> None:
    """把 name=value 写进项目根的 .env,只替换 name 那一行——多个 key(DeepSeek / 自定义供应商)各占一行,互不覆盖。"""
    env = project_root / ".env"
    _replace_env_var(env, name, value)
    if os.name == "posix":
        env.chmod(0o600)  # .env 存 API key:只留属主读写(Windows 无此权限位,跳过)


def _env_var_set(project_root: Path, name: str) -> bool:
    return _read_env_var(project_root / ".env", name) is not None


def set_env_key(project_root: Path, key: str) -> None:
    """把 DEEPSEEK_API_KEY 写进项目根的 .env(替换已有行)。"""
    set_project_env_key(project_root, key)


def set_project_env_key(project_root: Path, key: str) -> None:
    """Write DEEPSEEK_API_KEY into the project .env file."""
    _set_env_var(project_root, "DEEPSEEK_API_KEY", key)


def key_is_set(project_root: Path) -> bool:
    return bool(key_status(project_root)["effective"])


def set_global_env_key(key: str) -> None:
    """Write DEEPSEEK_API_KEY into the per-user Loom .env file."""
    global_config_dir().mkdir(parents=True, exist_ok=True)
    _replace_env_var(global_env_path(), "DEEPSEEK_API_KEY", key)


def key_status(project_root: Path) -> dict:
    """Return key presence and effective source without returning the secret."""
    _, source = resolve_deepseek_key(project_root)
    return {
        "effective": source != "none",
        "source": source,
        "process": source == "process",
        "project": _read_env_var(project_root / ".env", "DEEPSEEK_API_KEY") is not None,
        "global": _read_env_var(global_env_path(), "DEEPSEEK_API_KEY") is not None,
    }


def set_openai_compat_key(project_root: Path, key: str) -> None:
    """第三方 OpenAI 兼容供应商的 key 写进 .env 的 LOOM_OPENAI_COMPAT_KEY(与 DeepSeek key 各占一行)。"""
    _set_env_var(project_root, "LOOM_OPENAI_COMPAT_KEY", key)


def openai_compat_key_is_set(project_root: Path) -> bool:
    return _env_var_set(project_root, "LOOM_OPENAI_COMPAT_KEY")


def save_config(project_root: Path, cfg: Config) -> None:
    # base_url 只对 openai_compat 有意义,只在该供应商下写出这一行——deepseek/claude/codex 重写后照旧无该字段
    base_url_line = (f'base_url = "{cfg.base_url}"\n'
                     if cfg.provider == "openai_compat" and cfg.base_url else "")
    cheap_line = f'cheap_model = "{cfg.cheap_model}"\n' if cfg.cheap_model else ""  # 没设就不写,保持 toml 干净
    content = (
        "# Loom 项目配置\n\n"
        "[backend]\n"
        f'provider = "{cfg.provider}"\n'
        f'model    = "{cfg.model}"\n'
        f'{cheap_line}'
        f'{base_url_line}'
        "\n"
        "[novel]\n"
        f'title = "{cfg.title}"\n'
        f'"章节字数" = {int(cfg.chapter_chars)}\n\n'
        "[gate]\n"
        "# 质检/去AI味 复审轮数:1=只挑硬伤写进 .审稿留痕/(默认,不自动改稿);≥2 才回炉重写;0=关闭。不打分、不硬阻断(见 ADR-0006)\n"
        f'"轮数" = {int(cfg.gate_rounds)}\n'
        "# 伏笔悬空提醒章距:埋设超过这么多章仍无推进/回收 → 写新章时进 .审稿留痕/ 提醒(纯提示,不回炉、不阻断);0=关\n"
        f'"伏笔提醒章距" = {int(cfg.foreshadow_distance)}\n'
    )
    atomic_write_text(project_root / "loom.toml", content)
