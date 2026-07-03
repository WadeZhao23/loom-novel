"""拆书:离线把一本参考书拆成【可迁移条件框架】,产物只是候选。

红线:
- 只抽 what(套路/金手指机制/爽点循环),绝不碰 voice;产物绝不写 写作指纹.md。
- 物理隔离:只写 外置大脑/.拆书/ 隔离草稿区,绝不直接写 canon(世界观.md/人物卡.md/正文)。
- 不进默认流水线:没有任何 agent 的 reads: 含 skills/拆书.md,run_pipeline 不读 .拆书/。
- 极简:一遍过、读本地文件、复用 backends.complete 单接口,不引入任何重基础设施。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import events
from .fsutil import atomic_write_text
from .paths import DECONSTRUCT_DIR

Render = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


# 把 backend 压成"只抽框架、剥专名、出 Markdown"的硬护栏(拆书专属红线)
_GUARD = (
    "你是离线拆书工具,不是助手。只输出一份 Markdown 拆解候选,不输出别的话。\n"
    "铁律:① 只抽【可迁移条件框架】(什么条件组合造成爽/期待/反差),"
    "绝不保留原作角色名/地名/组织名/能力名/金手指专名/具体剧情/名场面/金句;\n"
    "② 必须单列一段【剥离清单/专名黑名单】把这些专名点名列出并标'绝不抄';\n"
    "③ 每条框架都要配一句'差异化改造'(换题材/人物/金手指/情绪 至少一种);\n"
    "④ 严禁写读后感,严禁凭记忆编造文本里没有的内容(没有就写'文本未覆盖')。"
)


def _load_skill(root: Path) -> str:
    """优先读项目内 skills/拆书.md(init 时由 copytree 拷入);回退包内模板。"""
    local = root / "skills" / "拆书.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    pkg = Path(__file__).parent / "templates" / "skills" / "拆书.md"
    return pkg.read_text(encoding="utf-8")


def deconstruct(root: Path, source_text: str, name: str,
                backend, render: Render = _noop) -> Path:
    if not source_text.strip():
        raise ValueError("参考书文本是空的,没东西可拆。")
    render(events.info(f"拆书中:{name} …"))

    system = _load_skill(root) + "\n\n---\n\n" + _GUARD
    out_text = backend.complete(system, source_text, max_chars=3000)

    # 物理隔离(红线②):只写隔离草稿区,绝不碰 世界观.md / 写作指纹.md / 正文/
    out_path = root / DECONSTRUCT_DIR / f"{name}-拆解.md"
    atomic_write_text(out_path, out_text.strip() + "\n")
    render(events.info(f"已落:{out_path}"))
    return out_path
