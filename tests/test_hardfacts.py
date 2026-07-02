"""硬设定逐字透传:把世界观的境界阶梯/金手指代价/地名势力 + 人物专名,原文(不经设定师复述)
喂给大纲师/写手,堵住"F~SSS 凭空多出一阶0级、一中写成二中"这类专名/等级漂移。

红线回归:确定性切片(不调 LLM)、故意排除「冰山真相」(终极反转,逐字喂会诱使提前抖包袱)与
「一句话定位」(情绪基调、本就该意译)、缺文件返回空串绝不阻断出稿。
"""
from __future__ import annotations

from pathlib import Path

from loom.agents import (
    _hardfacts_for,
    _md_h2_sections,
    _name_roster,
    run_pipeline,
)
from loom.config import Config

from conftest import FakeBackend

WORLDVIEW = """# 世界观

## 一句话定位
情绪基调测试句,本就该意译。

## 力量体系
- 阶梯:凡→淬体→筑基→金丹→元婴→化神。化神即天花板。
- 越阶杀人需付灵魂反噬代价。

## 金手指
- 类型:重生记忆。代价:回想过度当场昏厥。

## 地理 / 势力
- 青石宗:没落二流宗门。
- 黑风寨:盘踞后山的山匪。

## 冰山真相
- 灵气枯竭是有人在抽——这是终极反转。
"""

CHARS = """# 人物卡

## 主角 · 沈砚
- 身份:青石宗杂役,灵根测废。

## 对手 · 周楯
- 外门天才,惯于当众羞辱沈砚。
"""


def _seed(project: Path) -> None:
    (project / "外置大脑" / "世界观.md").write_text(WORLDVIEW, encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text(CHARS, encoding="utf-8")


# ── 纯函数:确定性切片 ───────────────────────────────────────────────

def test_md_h2_sections_splits_and_keeps_heading_line():
    secs = dict(_md_h2_sections(WORLDVIEW))
    assert set(secs) == {"一句话定位", "力量体系", "金手指", "地理 / 势力", "冰山真相"}
    # 每段原文含自己的标题行,且只到下一个 ## 为止
    assert secs["力量体系"].startswith("## 力量体系")
    assert "灵魂反噬" in secs["力量体系"]
    assert "重生记忆" not in secs["力量体系"]      # 没串进下一段


def test_md_h2_sections_h3_stays_inside_parent():
    md = "## 力量体系\n### 子阶\n- 一阶\n## 地理\n- 城"
    secs = dict(_md_h2_sections(md))
    assert "### 子阶" in secs["力量体系"] and "一阶" in secs["力量体系"]
    assert "### 子阶" not in secs["地理"]


# ── _hardfacts_for:纳入硬设定、排除反转/基调 ────────────────────────

def test_hardfacts_includes_ladder_cheat_geography_verbatim(project):
    _seed(project)
    hf = _hardfacts_for(project)
    # 境界阶梯逐字
    assert "凡→淬体→筑基→金丹→元婴→化神" in hf
    assert "灵魂反噬" in hf
    # 金手指代价逐字
    assert "重生记忆" in hf and "当场昏厥" in hf
    # 地名/势力逐字
    assert "青石宗" in hf and "黑风寨" in hf
    # 人物专名册
    assert "主角 · 沈砚" in hf and "周楯" in hf


def test_hardfacts_excludes_iceberg_and_tagline(project):
    _seed(project)
    hf = _hardfacts_for(project)
    assert "灵气枯竭是有人在抽" not in hf       # 冰山真相:绝不逐字喂写手
    assert "情绪基调测试句" not in hf           # 一句话定位:基调,本就该意译


def test_hardfacts_empty_when_files_missing(tmp_path: Path):
    assert _hardfacts_for(tmp_path) == ""        # 缺外置大脑 → 空串,不抛错、不阻断出稿


def test_name_roster_only_takes_headings_not_bios(project):
    _seed(project)
    roster = _name_roster(project / "外置大脑" / "人物卡.md")
    assert roster == "- 主角 · 沈砚\n- 对手 · 周楯"   # 只取专名,不带"灵根测废"等小传
    assert "灵根测废" not in roster


def test_name_roster_skips_placeholders_and_ai_supplement(project):
    # 默认模板的「## 主角」占位(名字在 - 名字: 行)、learn 追加的「## AI 补充…」段名都不是人名
    (project / "外置大脑" / "人物卡.md").write_text(
        "# 人物卡\n\n## 主角\n- 名字:沈砚\n\n## 主角 · 周楯\n- 外门天才\n\n"
        "## 关系网\n- 谁和谁\n\n## AI 补充(loom learn 后随章自动追加,你可改可删)\n"
        "### [AI补充·第1章]\n- 新角色:某某\n",
        encoding="utf-8")
    roster = _name_roster(project / "外置大脑" / "人物卡.md")
    assert roster == "- 主角 · 周楯"          # 只认带 · 的角色标题
    assert "AI 补充" not in roster            # learn 段名没被当人名
    assert "关系网" not in roster and "## 主角\n" not in roster


def test_hardfacts_denies_spoiler_heading_even_with_hardfact_keyword(project):
    # 「## 势力背后的真相」既含硬设定词(势力)又是反转 → deny 压过 allow,绝不进硬设定
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 力量体系\n- 阶梯:凡→化神。\n\n"
        "## 势力背后的真相\n- 终极黑手是天枢阁,绝不能提前写。\n",
        encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    hf = _hardfacts_for(project)
    assert "凡→化神" in hf                     # 真·硬设定还在
    assert "终极黑手是天枢阁" not in hf         # 伪装成势力的反转被挡
    assert "势力背后的真相" not in hf


def test_hardfacts_strips_nested_spoiler_subsection(project):
    # 反转嵌进被命中段的 ### 子块里,也要剥掉
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 力量体系\n- 阶梯:凡→化神。\n"
        "### 子阶说明\n- 每阶九重。\n"
        "### 冰山真相\n- 灵气枯竭是有人在抽。\n",
        encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    hf = _hardfacts_for(project)
    assert "凡→化神" in hf and "每阶九重" in hf      # 阶梯 + 正常子块都在
    assert "灵气枯竭是有人在抽" not in hf            # 嵌套的反转被剥
    assert "冰山真相" not in hf


def test_hardfacts_no_crash_on_directory_paths(project):
    # 红线:外置大脑路径被人误建成目录,也只返回空串、绝不 IsADirectoryError 崩、绝不阻断出稿
    for name in ("世界观.md", "人物卡.md"):
        p = project / "外置大脑" / name
        if p.exists():
            p.unlink()
        p.mkdir()
    assert _hardfacts_for(project) == ""


# ── 反转剔除按层级:#### 也剔,剔到同级/更浅标题为止 ─────────────────

def test_hardfacts_strips_h4_spoiler_and_resumes_at_sibling(project):
    # 反转写进 ####:只认 ### 的旧逻辑会整段漏给写手
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 力量体系\n- 阶梯:凡→化神。\n"
        "### 子阶说明\n- 每阶九重。\n"
        "#### 隐藏真相\n- 灵气枯竭是有人在抽。\n"
        "### 修炼资源\n- 灵石分三等。\n",
        encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    hf = _hardfacts_for(project)
    assert "凡→化神" in hf and "每阶九重" in hf and "灵石分三等" in hf   # 反转后的同级子节还在
    assert "灵气枯竭是有人在抽" not in hf and "隐藏真相" not in hf


def test_hardfacts_spoiler_h3_drops_its_deeper_children(project):
    # 命中反转的 ### 连同其 #### 子孙一起剔,到下一个同级 ### 恢复
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 力量体系\n- 阶梯:凡→化神。\n"
        "### 冰山真相\n- 表层线索。\n"
        "#### 更深一层\n- 真凶是天枢阁。\n"
        "### 子阶说明\n- 每阶九重。\n",
        encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    hf = _hardfacts_for(project)
    assert "凡→化神" in hf and "每阶九重" in hf
    assert "表层线索" not in hf and "真凶是天枢阁" not in hf


# ── H3 小节参与匹配 + 命不中提示 ─────────────────────────────────────

def test_hardfacts_picks_h3_under_unmatched_h2(project):
    # 硬设定写在没命中关键词的 H2 下面的 ### 小节里 → 只捞命中的那个 ###
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 基础设定\n开场杂记。\n\n"
        "### 力量体系\n- 阶梯:凡→化神。\n\n"
        "### 起名备忘\n- 别用生僻字。\n",
        encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    hf = _hardfacts_for(project)
    assert "凡→化神" in hf
    assert "开场杂记" not in hf and "别用生僻字" not in hf


def test_hardfacts_picks_h3_when_doc_has_no_h2(project):
    # 整份世界观只用 ### 分节也能命中;反转 ### 照旧 deny
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n### 力量体系\n- 阶梯:凡→化神。\n\n### 冰山真相\n- 有人在抽灵气。\n",
        encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    hf = _hardfacts_for(project)
    assert "凡→化神" in hf
    assert "有人在抽灵气" not in hf


def test_hardfacts_matches_tixi_without_other_keywords(project):
    # 「## 修仙体系」不含旧关键词(力量/境界…)也该命中——按「体系」认
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 修仙体系\n- 阶梯:凡→化神。\n", encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    assert "凡→化神" in _hardfacts_for(project)


def test_hardfacts_warns_when_nothing_recognized(project):
    # 世界观有内容但没有一节像硬设定 → 发 warn 提示检查标题写法(照旧不阻断、返回空)
    (project / "外置大脑" / "世界观.md").write_text(
        "# 世界观\n\n## 修仙杂谈\n- 随便写写。\n", encoding="utf-8")
    (project / "外置大脑" / "人物卡.md").write_text("# 人物卡\n", encoding="utf-8")
    events: list[dict] = []
    assert _hardfacts_for(project, events.append) == ""
    assert any(e["type"] == "warn" and "硬设定" in e["message"] for e in events)


def test_hardfacts_missing_file_stays_silent(tmp_path: Path):
    # 世界观整个缺失是另一回事(doctor 管),不发 warn
    events: list[dict] = []
    assert _hardfacts_for(tmp_path, events.append) == ""
    assert events == []


# ── 端到端:写手 prompt 真的拿到硬设定,设定师不重复注入 ──────────────

def _capture():
    long = "他屏住呼吸,后背贴着冰冷的石头。" * 30   # 够长,过非空/字数闸

    def responder(system, user):
        return "矿洞惊变" if "章节标题" in system else long
    return FakeBackend(responder)


def _user_of(backend: FakeBackend, produces: str) -> str:
    """取产出某物的那一棒收到的 user prompt(prompt 末尾必有「产出【…】」)。"""
    hits = [u for _, u in backend.calls if f"产出【{produces}】" in u]
    assert hits, f"没找到产出【{produces}】的调用"
    return hits[-1]


def test_writer_prompt_carries_hardfacts_but_not_iceberg(project):
    _seed(project)
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=300, gate_rounds=0)
    run_pipeline(project, 1, be, cfg)

    writer = _user_of(be, "本章初稿")
    assert "## 硬设定" in writer                                  # 有逐字硬设定块
    assert "凡→淬体→筑基→金丹→元婴→化神" in writer              # 境界阶梯原文到位
    assert "青石宗" in writer
    assert "灵气枯竭是有人在抽" not in writer                     # 反转没泄给写手


def test_setupper_prompt_has_no_hardfacts_block(project):
    _seed(project)
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=300, gate_rounds=0)
    run_pipeline(project, 1, be, cfg)

    setup = _user_of(be, "本章设定锚点")
    assert "## 硬设定" not in setup        # 设定师本就整本读世界观,不再二次塞硬设定块
