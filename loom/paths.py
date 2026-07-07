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
STATEBOOK_REL = brain_rel("状态账本")   # 跨章状态流水账(物品/状态/规则/时钟),除虫自动追加、人可改可删

# ── 外置大脑目录形态(3.2):世界观/人物 一节(人)一文件,AI 补充物理分离进 成长档案.md ──
# 双形态兼容:单文件存在 → 单文件优先(老书零迁移/手工建档者);否则目录存在 → 目录(新书)。
# 卡章纲(线性表)/写作指纹(整文件重蒸馏红线)/违禁词/立项卡/文风参考 刻意保持单文件。
WORLD_DIR_REL = f"{BRAIN_DIR}/世界观"
CHARS_DIR_REL = f"{BRAIN_DIR}/人物"
GROWTH_NAME = "成长档案.md"   # learn 的 [AI补充·第N章] 都进它:AI 有自己的文件,永不碰人写的文件

# [AI补充] 可能住的全部文件(enrich 写入/删章清理/重编号/prompt 折叠都认这一份清单):
# 老书=世界观.md/人物卡.md 文末;目录形态=各目录的 成长档案.md(AI 自留地,物理隔离)
SUPP_RELS = (WORLD_REL, CHARS_REL,
             f"{WORLD_DIR_REL}/{GROWTH_NAME}", f"{CHARS_DIR_REL}/{GROWTH_NAME}")


def brain_form(root: Path | str, file_rel: str, dir_rel: str) -> str:
    """外置大脑某部位的形态:"file" | "dir" | "none"(单文件优先)。"""
    root = Path(root)
    if (root / file_rel).is_file():
        return "file"
    if (root / dir_rel).is_dir():
        return "dir"
    return "none"


def brain_dir_files(root: Path | str, dir_rel: str) -> list[Path]:
    """目录形态的成员文件(名字排序稳定;成长档案固定排最后——先读人写的,再读 AI 补的)。"""
    d = Path(root) / dir_rel
    if not d.is_dir():
        return []
    files = sorted(p for p in d.glob("*.md") if p.name != GROWTH_NAME)
    growth = d / GROWTH_NAME
    return files + ([growth] if growth.is_file() else [])


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
