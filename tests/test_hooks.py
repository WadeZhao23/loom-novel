"""伏笔悬空检测器:扫卡章纲 recap 伏笔行,催久埋未还的伏笔,靠区别性词避免误判与噪声。"""
from __future__ import annotations

from pathlib import Path

from loom.hooks import Hook, parse_hooks, stale


def _write_card(project: Path, text: str) -> None:
    (project / "外置大脑" / "卡章纲.md").write_text(text, encoding="utf-8")


# 一份带 recap 伏笔行的卡章纲:ch1 埋青玉牌+阿芸,ch2 埋床板,ch12 回收青玉牌
_CARD = """# 卡章纲

> 一章一句话的脊柱。

- 第1章:沈砚被周楯当众羞辱。
  - [AI回顾] 摘要:重生第一天。
    伏笔:
    - [埋设] 周楯腰间多了一块青玉牌,来历与意义未明。
    - [埋设] 阿芸上一世死得早,沈砚暗中为她系紧鞋绳。
- 第2章:沈砚摸黑上后山。
  - [AI回顾] 摘要:枯井边发现尸体。
    伏笔:
    - [埋设] 床板下摸到一样不是他放的东西。
- 第12章:真相浮出。
  - [AI回顾] 摘要:青玉牌的来历揭晓。
    伏笔:
    - [回收] 青玉牌原是师门信物,周楯是早就潜入的卧底。
"""


def test_parse_reads_markers(project: Path):
    _write_card(project, _CARD)
    hooks = parse_hooks(project)
    assert Hook(1, "埋设", "周楯腰间多了一块青玉牌,来历与意义未明。") in hooks
    assert Hook(12, "回收", "青玉牌原是师门信物,周楯是早就潜入的卧底。") in hooks
    # 顶格章规划行(人手写)绝不被当伏笔
    assert all("沈砚被周楯当众羞辱" not in h.text for h in hooks)
    kinds = {(h.chapter, h.kind) for h in hooks}
    assert (1, "埋设") in kinds and (12, "回收") in kinds


def test_flags_old_unresolved_but_not_resolved(project: Path):
    _write_card(project, _CARD)
    issues = stale(project, current_chapter=13, threshold=8)
    texts = [i.evidence for i in issues]
    # 阿芸(ch1)、床板(ch2)久埋未还 → 报;青玉牌(ch1)已在 ch12 回收 → 不报
    assert any("阿芸" in t for t in texts)
    assert any("床板" in t for t in texts)
    assert not any("青玉牌" in t for t in texts)
    assert all(i.kind == "伏笔悬空" for i in issues)


def test_distance_below_threshold_is_quiet(project: Path):
    _write_card(project, _CARD)
    # 写第 6 章时,ch1/ch2 的埋设才隔 4-5 章,未超 threshold=8 → 不催
    assert stale(project, current_chapter=6, threshold=8) == []


def test_threshold_zero_disables(project: Path):
    _write_card(project, _CARD)
    assert stale(project, current_chapter=99, threshold=0) == []


def test_missing_card_is_empty(tmp_path: Path):
    assert stale(tmp_path, current_chapter=20, threshold=8) == []
    assert parse_hooks(tmp_path) == []


def test_no_foreshadow_rows_is_empty(project: Path):
    # 只有人手写规划行、没跑过 learn(无 [AI回顾] 伏笔)→ 无可催
    _write_card(project, "# 卡章纲\n\n- 第1章:开局。\n- 第2章:推进。\n")
    assert stale(project, current_chapter=30, threshold=8) == []


def test_protagonist_name_noise_does_not_falsely_resolve(project: Path):
    # 4 条埋设都含「沈砚」(高频噪声);一条 ch15 回收只和「青锋剑」那条共享区别性词。
    # 「沈砚」被当噪声剔除 → 不会让另外三条也被误判为已回收。
    card = (
        "# 卡章纲\n\n"
        "- 第1章:开局。\n"
        "  - [AI回顾] 摘要:沈砚起步。\n"
        "    伏笔:\n"
        "    - [埋设] 沈砚得到一柄青锋剑。\n"
        "    - [埋设] 沈砚发现地窖暗格。\n"
        "    - [埋设] 沈砚被赐婚给柳家。\n"
        "    - [埋设] 沈砚的玉佩入夜会发光。\n"
        "- 第15章:练剑。\n"
        "  - [AI回顾] 摘要:沈砚有所悟。\n"
        "    伏笔:\n"
        "    - [回收] 沈砚的青锋剑终于认主。\n"
    )
    _write_card(project, card)
    issues = stale(project, current_chapter=16, threshold=8)
    texts = [i.evidence for i in issues]
    assert not any("青锋剑" in t for t in texts)  # 真被回收 → 不报
    assert any("地窖" in t for t in texts)         # 仅共享「沈砚」噪声 → 仍报
    assert any("赐婚" in t for t in texts)
    assert any("玉佩" in t for t in texts)
