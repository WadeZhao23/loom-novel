"""读项目根的 loom.toml + .env。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .fsutil import atomic_write_text


@dataclass
class Config:
    provider: str = "deepseek"        # deepseek | claude | codex
    model: str = "deepseek-chat"
    title: str = "我的第一本书"
    chapter_chars: int = 800           # 终稿目标字数;中间工序自然更短
    gate_rounds: int = 1               # 质检/去AI味 复审轮数:1=只诊断列留痕(默认,不替作者改稿)、≥2 才自动回炉重写、0=关闭(见 ADR-0006)


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
    gate = data.get("gate", {})
    return Config(
        provider=backend.get("provider", "deepseek"),
        model=backend.get("model", "deepseek-chat"),
        title=novel.get("title", "我的第一本书"),
        chapter_chars=int(novel.get("章节字数", novel.get("chapter_chars", 800))),
        gate_rounds=int(gate.get("轮数", gate.get("rounds", 1))),
    )


def set_env_key(project_root: Path, key: str) -> None:
    """把 DEEPSEEK_API_KEY 写进项目根的 .env(替换已有行)。"""
    env = project_root / ".env"
    lines = []
    if env.exists():
        lines = [l for l in env.read_text(encoding="utf-8").splitlines()
                 if not l.strip().startswith("DEEPSEEK_API_KEY")]
    lines.append(f"DEEPSEEK_API_KEY={key}")
    atomic_write_text(env, "\n".join(lines) + "\n")


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
        f'"章节字数" = {int(cfg.chapter_chars)}\n\n'
        "[gate]\n"
        "# 质检/去AI味 复审轮数:1=只挑硬伤写进 .审稿留痕/(默认,不自动改稿);≥2 才回炉重写;0=关闭。不打分、不硬阻断(见 ADR-0006)\n"
        f'"轮数" = {int(cfg.gate_rounds)}\n'
    )
    atomic_write_text(project_root / "loom.toml", content)
