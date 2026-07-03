"""书房三视图(loom/studio.py):卡章纲/人物卡/世界观的只读投影。"""
from __future__ import annotations

from loom.studio import foreshadow, names, timeline

_CARD = """# 卡章纲

## 第1卷·重生
- 第1章:沈砚重生回矿场,发现颈上刀疤消失
    [AI回顾] 摘要:沈砚醒来发现回到三年前,决定改写命运。
    伏笔:
    - [埋设] 周楠腰间多了一块玉牌,来历不明
- 第2章:初见师姐,拿回青锋剑
    [AI回顾] 摘要:师姐出现,青锋剑认主。
    - [推进] 玉牌在夜里发出微光
- 第3章:矿场坍塌,发现地窖
"""

_WORLD = """# 世界观

## 一句话定位
重生复仇流。

## 力量体系
- 凡→蜕凡→化神,共三境
- 越境战斗几乎不可能

## 冰山真相
其实师姐才是重生者。

## 地理与势力
- 青云宗:主角门派
"""

_CARD_REL = "外置大脑/卡章纲.md"


def _proj(tmp_path, card=_CARD, world=_WORLD, chars="## 主角 · 沈砚\n\n## 配角 · 周楠\n"):
    (tmp_path / "外置大脑").mkdir()
    (tmp_path / _CARD_REL).write_text(card, encoding="utf-8")
    (tmp_path / "外置大脑" / "世界观.md").write_text(world, encoding="utf-8")
    (tmp_path / "外置大脑" / "人物卡.md").write_text(chars, encoding="utf-8")
    (tmp_path / "loom.toml").write_text('[novel]\n"书名" = "测"\n', encoding="utf-8")
    return tmp_path


def test_timeline_parses_plan_and_recap(tmp_path):
    rows = timeline(_proj(tmp_path))
    assert [r["n"] for r in rows] == [1, 2, 3]
    assert rows[0]["plan"].startswith("沈砚重生")
    assert "回到三年前" in rows[0]["recap"]
    assert rows[2]["recap"] == ""          # 没 learn 过的章,回顾为空


def test_foreshadow_rows_and_kinds(tmp_path):
    d = foreshadow(_proj(tmp_path))
    kinds = [(r["chapter"], r["kind"]) for r in d["rows"]]
    assert (1, "埋设") in kinds and (2, "推进") in kinds
    assert isinstance(d["stale"], list)   # 悬空判据走 hooks.stale 既有逻辑,这里只保证形状


def test_names_roster_and_sections_deny_spoiler(tmp_path):
    d = names(_proj(tmp_path))
    assert "主角 · 沈砚" in d["roster"]
    titles = [s["title"] for s in d["sections"]]
    assert "力量体系" in titles and "地理与势力" in titles
    assert all("真相" not in t for t in titles), "冰山真相绝不进任何展示面"
    body = next(s["body"] for s in d["sections"] if s["title"] == "力量体系")
    assert "凡→蜕凡→化神" in body


def test_missing_files_return_empty(tmp_path):
    (tmp_path / "loom.toml").write_text('[novel]\n"书名" = "空"\n', encoding="utf-8")
    assert timeline(tmp_path) == []
    assert foreshadow(tmp_path)["rows"] == []
    assert names(tmp_path) == {"roster": [], "sections": []}
