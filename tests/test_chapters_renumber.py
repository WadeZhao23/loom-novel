"""章节重编号时,loom 自己写的嵌入式块跟着搬:
世界观/人物卡的 [AI补充·第N章] 块换章号键、卡章纲的 [AI回顾] 子块搬到新章行下。
删除路径的既有行为(本章块成对清进回收站)保持不变。
"""
from __future__ import annotations

from pathlib import Path

from loom import paths
from loom.chapters import delete_chapter, insert_after, move_chapter

_WORLD = """# 世界观

## 力量体系
- F~SSS 九级(人手写,绝不动)

## AI 补充(loom learn 后随章自动追加,你可改可删;绝不覆盖你上面手写的)

### [AI补充·第1章]
- 青玉牌能开地窖

### [AI补充·第2章]
- 沈家地窖藏着旧账本
"""

_CHARS = """# 人物卡

## 主角 · 沈砚
- 底线:不卖旧宅(人手写,绝不动)

## AI 补充(loom learn 后随章自动追加,你可改可删;绝不覆盖你上面手写的)

### [AI补充·第2章]
- 沈砚:确认能听见地窖里的心跳声
"""

_CARD = """# 卡章纲

- 第1章:捡到青玉牌,章末抛地窖钩子
  - [AI回顾] 摘要:第一章捡到青玉牌。
    伏笔:
    - [埋设] 青玉牌
- 第2章:开地窖,发现旧账本
  - [AI回顾] 摘要:第二章开了地窖。
    伏笔:
    - [推进] 青玉牌
- 第3章:账本牵出仇家
"""


def _setup(project: Path, chapters: int = 2) -> None:
    for n in range(1, chapters + 1):
        paths.chapter_path(project, n).write_text(f"第{n}章正文。\n", encoding="utf-8")
    (project / paths.WORLD_REL).write_text(_WORLD, encoding="utf-8")
    (project / paths.CHARS_REL).write_text(_CHARS, encoding="utf-8")
    (project / paths.CARD_REL).write_text(_CARD, encoding="utf-8")


def test_insert_remaps_supplement_keys(project: Path) -> None:
    """插章后,后续章的 [AI补充·第2章] 键变 [AI补充·第3章],块内容/人手写主体一字不动。"""
    _setup(project)
    insert_after(project, 1)  # 第1章后插空章:旧第2章 → 第3章

    world = (project / paths.WORLD_REL).read_text(encoding="utf-8")
    chars = (project / paths.CHARS_REL).read_text(encoding="utf-8")
    assert "[AI补充·第3章]" in world and "[AI补充·第2章]" not in world
    assert "[AI补充·第1章]" in world                      # 插点之前的章不动
    assert "沈家地窖藏着旧账本" in world                    # 块内容原样
    assert "F~SSS 九级(人手写,绝不动)" in world           # 人手写主体原样
    assert "[AI补充·第3章]" in chars and "[AI补充·第2章]" not in chars
    # 新空章(第2章)的键已让位:learn 第2章不再被 write-once 挡住
    from loom.enrich import _already_supplemented
    assert not _already_supplemented(world, 2)


def test_insert_moves_recap_block_to_new_chapter_line(project: Path) -> None:
    """插章后,卡章纲 [AI回顾] 子块搬到新章号的规划行下;人写规划行一字不动。"""
    _setup(project)
    insert_after(project, 1)

    card = (project / paths.CARD_REL).read_text(encoding="utf-8")
    lines = card.splitlines()
    # 人写规划行全部原样(章号同步仍归人,SYNC_NOTE 提示)
    assert "- 第2章:开地窖,发现旧账本" in card
    # 旧第2章的回顾搬到了 第3章 行下
    i2 = next(i for i, l in enumerate(lines) if l.startswith("- 第2章"))
    i3 = next(i for i, l in enumerate(lines) if l.startswith("- 第3章"))
    seg2 = "\n".join(lines[i2:i3])
    seg3 = "\n".join(lines[i3:])
    assert "[AI回顾]" not in seg2                          # 第2章行下已空
    assert "第二章开了地窖" in seg3 and "[AI回顾]" in seg3   # 子块整体在第3章行下
    assert "[推进] 青玉牌" in seg3                          # 伏笔子行一起搬
    # 第1章的回顾不动
    i1 = next(i for i, l in enumerate(lines) if l.startswith("- 第1章"))
    assert "第一章捡到青玉牌" in "\n".join(lines[i1:i2])


def test_move_swaps_embedded_blocks(project: Path) -> None:
    """上下移(交换 1↔2):两章的 [AI补充] 键与 [AI回顾] 子块两段式互换,不互相覆盖。"""
    _setup(project)
    move_chapter(project, 1, "down")  # 交换第1、2章

    world = (project / paths.WORLD_REL).read_text(encoding="utf-8")
    assert "### [AI补充·第2章]\n- 青玉牌能开地窖" in world
    assert "### [AI补充·第1章]\n- 沈家地窖藏着旧账本" in world
    card = (project / paths.CARD_REL).read_text(encoding="utf-8")
    lines = card.splitlines()
    i1 = next(i for i, l in enumerate(lines) if l.startswith("- 第1章"))
    i2 = next(i for i, l in enumerate(lines) if l.startswith("- 第2章"))
    assert "第二章开了地窖" in "\n".join(lines[i1:i2])      # 互换后:1 行下挂旧 2 的回顾
    i3 = next(i for i, l in enumerate(lines) if l.startswith("- 第3章"))
    assert "第一章捡到青玉牌" in "\n".join(lines[i2:i3])


def test_delete_still_strips_blocks_to_trash(project: Path) -> None:
    """删除路径行为不变:被删章的 [AI回顾]/[AI补充] 照旧成对清掉、留底回收站。"""
    _setup(project)
    res = delete_chapter(project, 2)

    trash = Path(res["trash"])
    recap_bak = trash / paths.BRAIN_DIR / "卡章纲-第2章-AI回顾.md"
    supp_bak = trash / paths.BRAIN_DIR / "第2章-AI补充.md"
    assert recap_bak.is_file() and "第二章开了地窖" in recap_bak.read_text(encoding="utf-8")
    assert supp_bak.is_file() and "沈家地窖藏着旧账本" in supp_bak.read_text(encoding="utf-8")
    card = (project / paths.CARD_REL).read_text(encoding="utf-8")
    assert "第二章开了地窖" not in card                     # 已删章的回顾不再留在卡上
    world = (project / paths.WORLD_REL).read_text(encoding="utf-8")
    assert "沈家地窖藏着旧账本" not in world
    assert "[AI补充·第1章]" in world                       # 第1章的块不受影响


def test_delete_renumber_shifts_survivor_keys(project: Path) -> None:
    """删中间章触发重编号时,幸存章的嵌入式键同样下移——与插/移同走 _renumber 一个口,
    不然删章后幸存章照样卡 write-once(同一个 bug 的删除面)。"""
    _setup(project, chapters=3)
    delete_chapter(project, 1)  # 第2章 → 第1章,第3章 → 第2章

    world = (project / paths.WORLD_REL).read_text(encoding="utf-8")
    assert "### [AI补充·第1章]\n- 沈家地窖藏着旧账本" in world   # 旧第2章的块跟到新第1章
    assert "[AI补充·第2章]" not in world                        # 旧键不残留
    card = (project / paths.CARD_REL).read_text(encoding="utf-8")
    lines = card.splitlines()
    i1 = next(i for i, l in enumerate(lines) if l.startswith("- 第1章"))
    i2 = next(i for i, l in enumerate(lines) if l.startswith("- 第2章"))
    assert "第二章开了地窖" in "\n".join(lines[i1:i2])           # 回顾子块跟着搬到第1章行下
