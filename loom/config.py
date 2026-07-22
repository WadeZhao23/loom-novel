"""读项目根的 loom.toml + .env。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .fsutil import atomic_write_text


def _toml_str(s: str) -> str:
    """TOML 基本字符串字面量:反斜杠/双引号正经转义,别再用「引号换单引号」的糊弄净化。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Config:
    provider: str = "deepseek"        # deepseek | claude | codex | openai_compat
    model: str = "deepseek-v4-pro"    # DeepSeek V4 默认 pro(更强);更快更省可填 v4-flash。都是思考型,见 backends 预算
    cheap_model: str = ""              # 可选:复审/写后摘要这类「评估」调用走的便宜模型(同供应商换 model);空=全用主模型
    base_url: str = ""                 # 仅 openai_compat 有意义:第三方 OpenAI 兼容供应商的接口地址
    title: str = "我的第一本书"
    idea: str = ""                     # 建书时的一句话设定:AI 铺设定底稿(draft)的种子;空=没填
    chapter_chars: int = 800           # 终稿目标字数;中间工序自然更短
    gate_rounds: int = 1               # 质检/去AI味 复审轮数:1=只诊断列留痕(默认,不替作者改稿)、≥2 才自动回炉重写、0=关闭(见 ADR-0006)
    foreshadow_distance: int = 8       # 伏笔悬空提醒章距:埋设超过这么多章仍无推进/回收 → 写第N章时进留痕提醒(纯提示、不回炉、不阻断);0=关
    continuity_scan: bool = True       # 每章终稿后自动除虫(跨章连续性,非阻断附赠);False=只手动
    custom_rubric: str = ""             # 可选:用户自定义 rubric 文件路径(相对项目根);配了则替代默认 rubric


def find_project_root(start: Path | None = None) -> Path:
    """从当前目录向上找含 loom.toml 的项目根。"""
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / "loom.toml").exists():
            return d
    from .errors import render
    raise FileNotFoundError(render("project_root_not_found"))


def user_config_dir() -> Path:
    """用户级配置目录(默认后端 backend.json + 默认 key 的 .env)。本地文件、非服务器,守「稿子不离机」。
    LOOM_HOME 可覆盖(测试/自定义)。"""
    return Path(os.environ.get("LOOM_HOME") or (Path.home() / ".loom"))


def user_env_path() -> Path:
    return user_config_dir() / ".env"


def load_config(project_root: Path) -> Config:
    # 先加载用户级默认 key(~/.loom/.env)作回退,再加载项目 .env——两次 override=True,项目在后=项目赢。
    # 于是:新书没填 key 也能用用户级默认 key(继承);某本单独填了就覆盖(该本 .env 里那行赢)。
    load_dotenv(user_env_path(), override=True)
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
        model=backend.get("model", "deepseek-v4-pro"),
        cheap_model=backend.get("cheap_model", ""),    # 老 toml 没这行 → 空串=不开,行为不变
        base_url=backend.get("base_url", ""),          # 老 toml 没这行 → 兜底空串,无需迁移
        title=novel.get("title", "我的第一本书"),
        idea=novel.get("idea", ""),
        chapter_chars=int(novel.get("章节字数", novel.get("chapter_chars", 800))),
        gate_rounds=int(gate.get("轮数", gate.get("rounds", 1))),
        foreshadow_distance=int(gate.get("伏笔提醒章距", gate.get("foreshadow_distance", 8))),
        continuity_scan=bool(gate.get("除虫", gate.get("continuity_scan", True))),
        custom_rubric=gate.get("custom_rubric", ""),
    )


def _set_env_var(project_root: Path, name: str, value: str) -> None:
    """把 name=value 写进项目根的 .env,只替换 name 那一行——多个 key(DeepSeek / 自定义供应商)各占一行,互不覆盖。"""
    env = project_root / ".env"
    lines = []
    if env.exists():
        lines = [l for l in env.read_text(encoding="utf-8").splitlines()
                 if not l.strip().startswith(f"{name}=") and l.strip() != name]
    lines.append(f"{name}={value}")
    atomic_write_text(env, "\n".join(lines) + "\n")
    if os.name == "posix":
        env.chmod(0o600)  # .env 存 API key:只留属主读写(Windows 无此权限位,跳过)


def _env_var_set(project_root: Path, name: str) -> bool:
    env = project_root / ".env"
    if not env.exists():
        return False
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return bool(line.split("=", 1)[1].strip())
    return False


def set_provider_key(project_root: Path, key_env: str, key: str) -> None:
    """按供应商的 key_env(PROVIDERS 注册表声明)把 key 写进项目 .env——各供应商各占一行,互不覆盖。"""
    _set_env_var(project_root, key_env, key)


def provider_key_is_set(project_root: Path, key_env: str) -> bool:
    return _env_var_set(project_root, key_env)


def key_available(project_root: Path, key_env: str) -> bool:
    """这本书能不能拿到这个 key:本书 .env 有 → 有;否则看用户级默认 .env(继承)。"""
    return _env_var_set(project_root, key_env) or _env_var_set(user_config_dir(), key_env)


def read_env_value(env_dir: Path, name: str) -> str:
    """从某目录的 .env 读一个变量的原值(没有返回空)。用户级默认后端读 key 值用。"""
    env = env_dir / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def set_env_key(project_root: Path, key: str) -> None:
    """把 DEEPSEEK_API_KEY 写进项目根的 .env(替换已有行)。"""
    _set_env_var(project_root, "DEEPSEEK_API_KEY", key)


def key_is_set(project_root: Path) -> bool:
    return _env_var_set(project_root, "DEEPSEEK_API_KEY")


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
    idea_line = f'idea  = {_toml_str(cfg.idea)}\n' if cfg.idea else ""
    content = (
        "# Loom 项目配置\n\n"
        "[backend]\n"
        f'provider = "{cfg.provider}"\n'
        f'model    = "{cfg.model}"\n'
        f'{cheap_line}'
        f'{base_url_line}'
        "\n"
        "[novel]\n"
        f'title = {_toml_str(cfg.title)}\n'
        f'{idea_line}'
        f'"章节字数" = {int(cfg.chapter_chars)}\n\n'
        "[gate]\n"
        "# 质检/去AI味 复审轮数:1=只挑硬伤写进 .审稿留痕/(默认,不自动改稿);≥2 才回炉重写;0=关闭。不打分、不硬阻断(见 ADR-0006)\n"
        f'"轮数" = {int(cfg.gate_rounds)}\n'
        "# 伏笔悬空提醒章距:埋设超过这么多章仍无推进/回收 → 写新章时进 .审稿留痕/ 提醒(纯提示,不回炉、不阻断);0=关\n"
        f'"伏笔提醒章距" = {int(cfg.foreshadow_distance)}\n'
        "# 每章写完自动「除虫」(跨章连续性检查,走便宜模型,非阻断只出报告);false=只在编辑器手动点\n"
        f'"除虫" = {"true" if cfg.continuity_scan else "false"}\n'
    )
    atomic_write_text(project_root / "loom.toml", content)
