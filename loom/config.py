"""读项目根的 loom.toml + .env。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    provider: str = "deepseek"        # deepseek | claude | codex
    model: str = "deepseek-chat"
    title: str = "我的第一本书"
    chapter_chars: int = 800           # 终稿目标字数;中间工序自然更短


def find_project_root(start: Path | None = None) -> Path:
    """从当前目录向上找含 loom.toml 的项目根。"""
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / "loom.toml").exists():
            return d
    from .errors import render
    raise FileNotFoundError(render("project_root_not_found"))


def load_config(project_root: Path) -> Config:
    # .env 从项目根读(里面放 DEEPSEEK_API_KEY);override=True 保证切换项目时当前项目的 key 生效
    load_dotenv(project_root / ".env", override=True)
    try:
        data = tomllib.loads((project_root / "loom.toml").read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"loom.toml 格式有误:{e}") from e
    backend = data.get("backend", {})
    novel = data.get("novel", {})
    return Config(
        provider=backend.get("provider", "deepseek"),
        model=backend.get("model", "deepseek-chat"),
        title=novel.get("title", "我的第一本书"),
        chapter_chars=int(novel.get("章节字数", novel.get("chapter_chars", 800))),
    )


def set_env_key(project_root: Path, key: str) -> None:
    """把 DEEPSEEK_API_KEY 写进项目根的 .env(替换已有行)。"""
    env = project_root / ".env"
    lines = []
    if env.exists():
        lines = [l for l in env.read_text(encoding="utf-8").splitlines()
                 if not l.strip().startswith("DEEPSEEK_API_KEY")]
    lines.append(f"DEEPSEEK_API_KEY={key}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


def key_is_set(project_root: Path) -> bool:
    env = project_root / ".env"
    if not env.exists():
        return False
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DEEPSEEK_API_KEY="):
            return bool(line.split("=", 1)[1].strip())
    return False


def save_config(project_root: Path, cfg: Config) -> None:
    content = (
        "# Loom 项目配置\n\n"
        "[backend]\n"
        f'provider = "{cfg.provider}"\n'
        f'model    = "{cfg.model}"\n\n'
        "[novel]\n"
        f'title = "{cfg.title}"\n'
        f'"章节字数" = {int(cfg.chapter_chars)}\n'
    )
    (project_root / "loom.toml").write_text(content, encoding="utf-8")
