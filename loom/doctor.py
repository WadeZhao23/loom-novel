"""极简启动自检:检查 key/后端命令/agent 文件/外置大脑四件套齐不齐。

只读、无副作用:纯 stat + find_spec + which,绝不写文件、不调后端 LLM、不碰 learn/diff。
只有 ok|缺失 二态 + 一行修复;不引入 SQLite/RAG/projection/dashboard/phase/severity。
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import key_is_set, load_config, openai_compat_key_is_set

# 单一真相:server.py 也从这里导入,避免清单各存一份漂移
BRAIN_FILES = ["世界观", "人物卡", "卡章纲", "写作指纹"]   # 外置大脑【四件套强制】
OPTIONAL_BRAIN = ["立项卡", "文风参考", "违禁词"]           # 【可选】:有无都 ok,不阻断出稿
AGENT_FILES = ["设定师", "大纲师", "写手", "编辑", "润色师"]  # 5 道工序


@dataclass
class Check:
    name: str
    ok: bool
    missing: str = ""   # 缺什么(仅 ok=False)
    fix: str = ""       # 怎么补(仅 ok=False)


def _c(name: str, ok: bool, missing: str = "", fix: str = "") -> Check:
    return Check(name, ok, "" if ok else missing, "" if ok else fix)


def run_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    # a. loom.toml 可解析
    try:
        cfg = load_config(root)
        checks.append(_c("loom.toml 可解析", True))
    except Exception as e:
        checks.append(_c("loom.toml 可解析", False,
                         f"无法读取/解析:{e}", "确认 loom.toml 存在且为合法 TOML,或重新 loom init"))
        return checks  # 没配置,后面的检查无意义,提前返回
    prov = (cfg.provider or "deepseek").lower()
    # b. provider 凭据(deepseek / openai_compat 要 key;自定义还要 base_url)
    if prov == "deepseek":
        checks.append(_c("DEEPSEEK_API_KEY 已配", key_is_set(root),
                         "全局 ~/.loom/.env 和项目 .env 都没读到 DEEPSEEK_API_KEY",
                         "在顶栏保存全局 DeepSeek Key,或在本项目 .env 加 DEEPSEEK_API_KEY=sk-你的key"))
    elif prov == "openai_compat":
        checks.append(_c("自定义供应商 base_url 已填", bool((cfg.base_url or "").strip()),
                         "loom.toml 里没填 backend.base_url",
                         "顶栏填这家供应商的接口地址 base_url(如智谱 https://open.bigmodel.cn/api/paas/v4)再保存后端"))
        checks.append(_c("LOOM_OPENAI_COMPAT_KEY 已配", openai_compat_key_is_set(root),
                         ".env 里没读到 LOOM_OPENAI_COMPAT_KEY",
                         "顶栏 API Key 框填这家供应商的 key,点保存后端(写进项目 .env)"))
    # c. provider 对应命令/库
    if prov in ("deepseek", "openai_compat"):
        checks.append(_c("openai 库已装", importlib.util.find_spec("openai") is not None,
                         "没装 openai 库", "pip install openai"))
    elif prov == "claude":
        checks.append(_c("claude 命令可用", shutil.which("claude") is not None,
                         "PATH 里没有 claude", "装 Claude Code 并确保 claude 在 PATH"))
    elif prov == "codex":
        checks.append(_c("codex 命令可用", shutil.which("codex") is not None,
                         "PATH 里没有 codex",
                         "装 Codex CLI(npm i -g @openai/codex)并 codex login(复用 ChatGPT 订阅,不用填 key)"))
    else:
        checks.append(_c("provider 受支持", False,
                         f"未知 provider={prov!r}", "loom.toml 里改成 deepseek/claude/codex/openai_compat"))
    # d. 5 个 agent 文件齐
    for n in AGENT_FILES:
        p = root / "agents" / f"{n}.md"
        checks.append(_c(f"agent · {n}", p.is_file(),
                         f"缺 agents/{n}.md", f"补回 agents/{n}.md(可对照 loom init 模板)"))
    # e. 外置大脑四件套在
    for n in BRAIN_FILES:
        p = root / "外置大脑" / f"{n}.md"
        fix = ("loom seed 重新生成,或从备份恢复" if n == "写作指纹"
               else f"外置大脑是人维护文件,手动补回 外置大脑/{n}.md")
        checks.append(_c(f"外置大脑 · {n}", p.is_file(), f"缺 外置大脑/{n}.md", fix))
    # f. 可选卡(立项卡/文风参考/违禁词):有无都 ok——纯信息、绝不 ok=False、绝不阻断(同违禁词待遇)
    for n in OPTIONAL_BRAIN:
        checks.append(_c(f"外置大脑 · {n}(可选)", True))
    return checks


def report(checks: list[Check]) -> dict:
    return {"ok": all(c.ok for c in checks), "checks": [asdict(c) for c in checks]}
