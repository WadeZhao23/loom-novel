"""磁盘布局的唯一真相:一本书在盘上长什么样,只在这里声明一次。

- 目录常量 + 各产物的路径构造:正文章节 / .原稿快照 / .细纲 / .历史 / .回收站 /
  .审稿留痕 / 外置大脑各文件 / .指纹历史 / ledger。其余模块一律从这里取,不再各自拼字面量。
- CHAPTER_ARTIFACTS 注册表:一章在盘上的全部关联产物;chapters 的删除/重编号按它整体搬,
  新增每章产物时在此登记一行,搬家就不会漏。
- 纯 stdlib、不 import 任何 loom 模块——谁都能安全依赖它,永不成环。
"""

from __future__ import annotations

import re
from pathlib import Path

# ── 目录(相对项目根;点开头 = 引擎自动维护,作者一般不手碰)────────────────
BODY_DIR = "正文"                       # 章节正文(作者手改的定稿)
SNAPSHOT_DIR = f"{BODY_DIR}/.原稿"       # AI 原稿快照 + 续跑账本(只给 learn 的 diff / 断点续跑)
OUTLINE_DIR = f"{BODY_DIR}/.细纲"        # 每章分镜细纲(可看可改,WYSIWYG)
HISTORY_DIR = f"{BODY_DIR}/.历史"        # 单章版本历史(覆盖前快照,后悔药)
TRASH_DIR = f"{BODY_DIR}/.回收站"        # 删章的整章产物落这里,可恢复
REVIEW_DIR = ".审稿留痕"                 # 编辑留痕 / 关卡残留 / 各类提醒(人可读可改)
BRAIN_DIR = "外置大脑"                   # 每本书的状态文件(人写主体 + AI 追加子块)
FP_HISTORY_DIR = f"{BRAIN_DIR}/.指纹历史"  # learn 前的指纹备份(一键撤销)
DECONSTRUCT_DIR = f"{BRAIN_DIR}/.拆书"    # 拆书隔离草稿区(没有任何 agent 读它)


# ── 外置大脑各文件(相对项目根)────────────────────────────────────────────
def brain_rel(name: str) -> str:
    """外置大脑文件的相对路径(name 不带 .md)。"""
    return f"{BRAIN_DIR}/{name}.md"


FINGERPRINT_REL = brain_rel("写作指纹")
WORLD_REL = brain_rel("世界观")
CHARS_REL = brain_rel("人物卡")
CARD_REL = brain_rel("卡章纲")
BANNED_REL = brain_rel("违禁词")
PROJECT_CARD_REL = brain_rel("立项卡")


# ── 每章产物 ──────────────────────────────────────────────────────────────
def chapter_rel(n: int) -> str:
    """正文章节的相对路径(给 snapshot_chapter 这类吃 rel 字符串的口)。"""
    return f"{BODY_DIR}/第{n}章.md"


def chapter_path(root: Path | str, n: int) -> Path:
    return Path(root) / BODY_DIR / f"第{n}章.md"


def snapshot_path(root: Path | str, n: int) -> Path:
    return Path(root) / SNAPSHOT_DIR / f"第{n}章.md"


def ledger_path(root: Path | str, n: int) -> Path:
    return Path(root) / SNAPSHOT_DIR / f"第{n}章.ledger.json"


def outline_path(root: Path | str, n: int) -> Path:
    return Path(root) / OUTLINE_DIR / f"第{n}章.md"


def history_dir(root: Path | str, key: str) -> Path:
    """某章的版本历史目录;key 是「第N章」这样的章名(见 CHAP_RE 的捕获组)。"""
    return Path(root) / HISTORY_DIR / key


def review_note_path(root: Path | str, n: int) -> Path:
    return Path(root) / REVIEW_DIR / f"第{n}章.md"


def fp_history_path(root: Path | str, n: int) -> Path:
    return Path(root) / FP_HISTORY_DIR / f"第{n}章-learn前.md"


# 正文章节 rel 的判定正则(fsutil 历史快照用):命中「正文/第N章.md」取章名做 key。
# 【红线】不匹配一律由调用方静默跳过——外置大脑等非章节文件的保存走同一写盘口,
# 改成 raise 会炸掉它们的保存路径(评审已否决)。
CHAP_RE = re.compile(rf"^{BODY_DIR}/(第.+?章)\.md$")


def chapter_numbers(root: Path | str) -> list[int]:
    """盘上已有的章号(升序)。文件名即真相:正文/第N章.md。"""
    body = Path(root) / BODY_DIR
    return sorted(int(p.stem[1:-1]) for p in body.glob("第*章.md")) if body.is_dir() else []


# 一章在盘上的全部关联产物:(相对目录, 文件名模板, 是否目录)。
CHAPTER_ARTIFACTS: list[tuple[str, str, bool]] = [
    (BODY_DIR, "第{n}章.md", False),
    (SNAPSHOT_DIR, "第{n}章.md", False),
    (SNAPSHOT_DIR, "第{n}章.ledger.json", False),
    (OUTLINE_DIR, "第{n}章.md", False),
    (HISTORY_DIR, "第{n}章", True),
    (REVIEW_DIR, "第{n}章.md", False),
    (FP_HISTORY_DIR, "第{n}章-learn前.md", False),
]
