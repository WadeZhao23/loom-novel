"""读取项目根的 loom.toml 和 .env。"""

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


@dataclass
class Config:
    provider: str = "deepseek"        # deepseek | claude | codex
    model: str = "deepseek-chat"
    title: str = "我的第一本书"
    chapter_chars: int = 800          # 目标章节字数; 中间工序自然更短
    gate_rounds: int = 1              # 质检/去AI味复审轮数: 1=只诊断留痕, >=2 才自动回炉重写, 0=关闭(见 ADR-0006)


def find_project_root(start: Path | None = None) -> Path:
    """从当前目录向上寻找包含 loom.toml 的项目根。"""
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


def _read_env_key(path: Path) -> str | None:
    if not path.exists():
        return None
    value = dotenv_values(path).get("DEEPSEEK_API_KEY")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _replace_env_key(path: Path, key: str) -> None:
    target_assignment = re.compile(r"^(?:export\s+)?DEEPSEEK_API_KEY\s*=")

    def is_target_assignment(line: str) -> bool:
        stripped = line.strip()
        return bool(target_assignment.match(stripped))

    lines: list[str] = []
    if path.exists():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not is_target_assignment(line)
        ]
    lines.append(f"DEEPSEEK_API_KEY={key}")
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

    project_key = _read_env_key(project_root / ".env")
    if project_key:
        return project_key, "project"

    global_key = _read_env_key(global_env_path())
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


def load_config(project_root: Path) -> Config:
    # 显式解析 DeepSeek key，避免切换项目后沿用上一个项目残留的凭据。
    apply_deepseek_key(project_root)
    try:
        data = tomllib.loads((project_root / "loom.toml").read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"loom.toml 格式有误:{e}") from e
    backend = data.get("backend", {})
    novel = data.get("novel", {})
    gate = data.get("gate", {})
    return Config(
        provider=backend.get("provider", "deepseek"),
        model=backend.get("model", "deepseek-chat"),
        title=novel.get("title", "我的第一本书"),
        chapter_chars=int(novel.get("章节字数", novel.get("chapter_chars", 800))),
        gate_rounds=int(gate.get("轮数", gate.get("rounds", 1))),
    )


def set_project_env_key(project_root: Path, key: str) -> None:
    """Write DEEPSEEK_API_KEY into the project .env file."""
    _replace_env_key(project_root / ".env", key)


def set_global_env_key(key: str) -> None:
    """Write DEEPSEEK_API_KEY into the per-user Loom .env file."""
    global_config_dir().mkdir(parents=True, exist_ok=True)
    _replace_env_key(global_env_path(), key)


def set_env_key(project_root: Path, key: str) -> None:
    """Compatibility wrapper: existing callers write a project override."""
    set_project_env_key(project_root, key)


def key_status(project_root: Path) -> dict:
    """Return key presence and effective source without returning the secret."""
    _, source = resolve_deepseek_key(project_root)
    return {
        "effective": source != "none",
        "source": source,
        "process": source == "process",
        "project": _read_env_key(project_root / ".env") is not None,
        "global": _read_env_key(global_env_path()) is not None,
    }


def key_is_set(project_root: Path) -> bool:
    return bool(key_status(project_root)["effective"])


def save_config(project_root: Path, cfg: Config) -> None:
    content = (
        "# Loom 项目配置\n\n"
        "[backend]\n"
        f'provider = "{cfg.provider}"\n'
        f'model    = "{cfg.model}"\n\n'
        "[novel]\n"
        f'title = "{cfg.title}"\n'
        f'"章节字数" = {int(cfg.chapter_chars)}\n\n'
        "[gate]\n"
        "# 质检/去AI味复审轮数:1=只挑硬伤并写进 .审稿留痕/, 默认不自动改稿; >=2 才回炉重写; 0=关闭(见 ADR-0006)\n"
        f'"轮数" = {int(cfg.gate_rounds)}\n'
    )
    atomic_write_text(project_root / "loom.toml", content)
