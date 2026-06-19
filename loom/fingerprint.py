"""写作指纹的两件事:seed(从样本提炼初版)、learn(从你的手改 diff 重新蒸馏)。

铁律(见 ADR 0001/0002):
- 学习信号【只能是你的手改 diff】,绝不用 AI 自己的输出回写。
- 蒸馏只提取【个人文风偏好】,忽略剧情/设定纠错和单纯的去 AI 味改动。
- 指纹是被【反复重写的一份】(合并去重、有预算),不是流水账 append。
- 保留若干条逐字 anchor 例句,模型不许改写——防止反复蒸馏磨成中庸腔。

引擎不依赖前端:进度通过 progress(event: dict) 回调发出。
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Callable

from .backends import Backend, LoomBackendError
from .state import mark_learned, set_fingerprint_source

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


FINGERPRINT_REL = "外置大脑/写作指纹.md"

_SEED_SYSTEM = """你是一个文风分析器。从用户给的真实写作样本里,提炼出一份可复用的【写作指纹】\
——也就是"这个人写东西的辨识特征"。只看怎么写(句式/用词/节奏/口头禅/爱用和绝不用的表达),\
不要复述样本的内容主题。输出必须是中文 Markdown,沿用下面给定的小标题结构,简洁、具体、可执行。\
其中 anchor 例句必须从样本里【逐字摘抄】3-6 句最有个人味的原话,不许改写。"""

_LEARN_SYSTEM = """你在维护一个作者的【写作指纹】。我会给你:① 现有指纹;② 作者对某一章 AI 稿的手改 diff。\
请只从 diff 里提取作者的【个人文风偏好】(句式长短、用词习惯、节奏、口头禅、禁用表达),\
明确【忽略】这三类改动:剧情/人物/设定的纠错、信息增删、以及单纯的"去 AI 味"通用改动\
(那是另一个功能的事)。把新观察并进现有指纹:合并、去重、冲突时以更近的证据为准,\
整体压在 40 条规则以内。anchor 例句用"作者改完后保留下来的原句"补充/替换,逐字保留。\
输出【完整的新指纹】,沿用与现有指纹相同的小标题结构,不要解释你改了什么。"""

_FORMAT_HINT = """# 写作指纹

> 这是"你"的文风规则化描述;写手/润色师写前会读它,你 learn 后它会更新。目的只有一个:越写越像你。

## 句式偏好
- (例:爱用短句+单句成段;长句少;少用关联词焊接)

## 口头禅 / 高频表达
-

## 禁用词 / 绝不这么写
-

## 节奏
-

## anchor 例句(逐字保留的我的原话,模型照这个味儿写、不许改写)
>
"""


def neutral_default() -> str:
    """init 离线落的中性默认指纹——老实标注"还没学到你"。"""
    return (
        "# 写作指纹\n\n"
        "> ⚠️ 这是**中性默认指纹**,还没学到你。\n"
        "> 喂样本(seed),或先写一章、手改、再 learn,它就开始像你了。\n\n"
        "## 句式偏好\n- (待 seed/learn 填充)\n\n"
        "## 口头禅 / 高频表达\n- (待填充)\n\n"
        "## 禁用词 / 绝不这么写\n- 殊不知、仿佛、宛如的堆砌\n- 连续三个以上排比\n- 直接点名情绪(\"悲伤涌上心头\")\n\n"
        "## 节奏\n- (待填充)\n\n"
        "## anchor 例句(逐字保留的我的原话,模型照这个味儿写、不许改写)\n> (还没有——喂样本后这里会出现你的原句)\n"
    )


def seed_from_samples(project_root: Path, samples: str, backend: Backend, progress: Progress = _noop) -> Path:
    if not samples.strip():
        raise LoomBackendError("样本是空的。给我一段你真写过的文字(越像你平时越好)。")
    progress({"type": "info", "message": "正在从你的样本里提炼写作指纹…"})
    user = (
        f"这是我真写过的文字样本:\n\n{samples.strip()}\n\n"
        f"请按下面的结构输出我的写作指纹:\n\n{_FORMAT_HINT}"
    )
    fp = backend.complete(_SEED_SYSTEM, user, max_chars=1800)
    path = project_root / FINGERPRINT_REL
    path.write_text(fp.strip() + "\n", encoding="utf-8")
    set_fingerprint_source(project_root, "sample")
    progress({"type": "seed_done", "path": str(path), "source": "sample"})
    return path


def seed_from_inherit(project_root: Path, other_fingerprint: Path, progress: Progress = _noop) -> Path:
    if not other_fingerprint.exists():
        raise LoomBackendError(f"找不到要继承的指纹文件:{other_fingerprint}")
    path = project_root / FINGERPRINT_REL
    path.write_text(other_fingerprint.read_text(encoding="utf-8"), encoding="utf-8")
    set_fingerprint_source(project_root, "inherit")
    progress({"type": "seed_done", "path": str(path), "source": "inherit"})
    return path


def _diff(snapshot: str, edited: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            snapshot.splitlines(), edited.splitlines(),
            fromfile="AI原稿", tofile="你的改稿", lineterm="",
        )
    )


def learn(project_root: Path, chapter_n: int, backend: Backend, progress: Progress = _noop) -> Path:
    edited_path = project_root / "正文" / f"第{chapter_n}章.md"
    snap_path = project_root / "正文" / ".原稿" / f"第{chapter_n}章.md"
    if not snap_path.exists() or not edited_path.exists():
        raise LoomBackendError(f"第 {chapter_n} 章还没生成过(找不到原稿快照)。先写第 {chapter_n} 章。")
    edited = edited_path.read_text(encoding="utf-8")
    snapshot = snap_path.read_text(encoding="utf-8")
    if edited.strip() == snapshot.strip():
        raise LoomBackendError(
            f"第 {chapter_n} 章你一个字都还没改 —— 没有「你的改动」可学。\n"
            f"先手改它,把不像你的地方改成像你的,再 learn。"
        )

    diff = _diff(snapshot, edited)
    fp_path = project_root / FINGERPRINT_REL
    old_fp = fp_path.read_text(encoding="utf-8") if fp_path.exists() else neutral_default()

    progress({"type": "info", "message": f"正在从你对第 {chapter_n} 章的手改里学习…"})
    user = (
        f"## 现有指纹\n{old_fp}\n\n"
        f"## 作者对第 {chapter_n} 章的手改 diff(- 是 AI 原稿,+ 是作者改成的)\n{diff}\n\n"
        f"请输出更新后的【完整新指纹】。"
    )
    new_fp = backend.complete(_LEARN_SYSTEM, user, max_chars=1800)
    fp_path.write_text(new_fp.strip() + "\n", encoding="utf-8")
    mark_learned(project_root, chapter_n)
    progress({"type": "learn_done", "path": str(fp_path), "chapter": chapter_n})
    return fp_path
