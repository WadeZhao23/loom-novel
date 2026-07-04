"""外置大脑目录形态(世界观/、人物/)的红线回归。

双形态铁律:单文件优先(老书零迁移);目录形态下——
硬设定按【文件名】allow/deny(冰山真相/成长档案绝不逐字喂写手)、
专名册=人物文件名(占位「未命名」不进)、AI 补充只落 成长档案.md(物理隔离,永不碰人写的文件)、
重编号连成长档案里的 [AI补充·第N章] 键一起搬、seed 起草按 H2 拆成一节(人)一文件且绝不覆盖真内容。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from loom import paths
from loom.agents import _hardfacts_for, _name_roster_for
from loom.draft import draft_brain
from loom.enrich import enrich_chapter, remap_supplement_keys
from loom.usecases import _brain_entries

from conftest import FakeBackend

W_DIR = paths.WORLD_DIR_REL
C_DIR = paths.CHARS_DIR_REL


def _reset_dir(project: Path, rel: str, files: dict[str, str]) -> None:
    """把某个大脑目录重置成给定文件集(测试自己掌控内容,不依赖脚手架占位文案)。"""
    d = project / rel
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")


# ── 硬设定:按文件名 allow/deny ───────────────────────────────────────────

def test_hardfacts_dir_allow_by_filename_deny_spoiler_and_growth(project):
    _reset_dir(project, W_DIR, {
        "力量体系.md": "# 力量体系\n- 凡→蜕凡DIRFACT力量\n",
        "地理与势力.md": "# 地理与势力\n- 青石宗DIRFACT地理\n",
        "一句话定位.md": "# 一句话定位\n情绪基调MOODONLY,本就该意译。\n",
        "冰山真相.md": "# 冰山真相\n- 灵气枯竭是有人在抽SPOILERX。\n",
        "成长档案.md": "[AI补充·第1章]\n- 新势力GROWTHX\n",
    })
    hf = _hardfacts_for(project)
    assert "DIRFACT力量" in hf and "DIRFACT地理" in hf     # 命中关键词的文件整篇逐字
    assert "MOODONLY" not in hf                            # 非硬设定文件不进
    assert "SPOILERX" not in hf and "GROWTHX" not in hf    # 反转/AI自留地 deny 压过一切


def test_hardfacts_file_precedence_over_dir(project):
    # 同时存在 世界观.md 与 世界观/:单文件优先(老书零迁移的根),目录被忽略
    (project / paths.WORLD_REL).write_text(
        "# 世界观\n\n## 力量体系\n- FILEFACT\n", encoding="utf-8")
    _reset_dir(project, W_DIR, {"力量体系.md": "# 力量体系\n- DIRFACT\n"})
    hf = _hardfacts_for(project)
    assert "FILEFACT" in hf and "DIRFACT" not in hf


# ── 专名册:文件名即名字 ─────────────────────────────────────────────────

def test_roster_dir_reads_filenames_skips_unnamed_and_growth(project):
    _reset_dir(project, C_DIR, {
        "主角·沈砚.md": "# 主角 · 沈砚\n- 核心欲望:活下去\n",
        "配角·周楠.md": "# 配角 · 周楠\n- 立场:同乡\n",
        "反派·未命名.md": "# 反派 · 未命名\n> (占位示例,换成你自己的。)\n",
        "成长档案.md": "[AI补充·第1章]\n- 周楠:其实会武\n",
        "备注.md": "随手记,没有分隔符,不是人物卡。\n",
    })
    roster = _name_roster_for(project)
    assert "主角·沈砚" in roster and "配角·周楠" in roster
    assert "未命名" not in roster            # 占位卡绝不喂写手
    assert "成长档案" not in roster and "备注" not in roster


# ── enrich:AI 补充只落成长档案,write-once,人写文件一字不动 ──────────────

_ENRICH_OUT = "【世界观补充】\n- 新势力:黑水商会浮出水面。\n\n【人物卡补充】\n- 周楠:其实身负内伤。\n"


def _prep_enrich(project: Path) -> tuple[str, str]:
    _reset_dir(project, W_DIR, {"力量体系.md": "# 力量体系\n- 凡→蜕凡\n"})
    _reset_dir(project, C_DIR, {"主角·沈砚.md": "# 主角 · 沈砚\n- 欲望:活下去\n"})
    ch = paths.chapter_path(project, 1)
    ch.parent.mkdir(parents=True, exist_ok=True)
    ch.write_text("# 第一章\n\n沈砚在矿场遇见黑水商会的人。\n", encoding="utf-8")
    return ((project / W_DIR / "力量体系.md").read_text(encoding="utf-8"),
            (project / C_DIR / "主角·沈砚.md").read_text(encoding="utf-8"))


def test_enrich_dir_writes_growth_file_only(project):
    world_before, chars_before = _prep_enrich(project)
    enrich_chapter(project, 1, FakeBackend(_ENRICH_OUT))
    wg = (project / W_DIR / paths.GROWTH_NAME).read_text(encoding="utf-8")
    cg = (project / C_DIR / paths.GROWTH_NAME).read_text(encoding="utf-8")
    assert "[AI补充·第1章]" in wg and "黑水商会" in wg
    assert "[AI补充·第1章]" in cg and "周楠" in cg
    # 物理隔离:人写的文件一个字节都不动
    assert (project / W_DIR / "力量体系.md").read_text(encoding="utf-8") == world_before
    assert (project / C_DIR / "主角·沈砚.md").read_text(encoding="utf-8") == chars_before


def test_enrich_growth_write_once_per_chapter(project):
    _prep_enrich(project)
    be = FakeBackend(_ENRICH_OUT)
    enrich_chapter(project, 1, be)
    enrich_chapter(project, 1, be)   # 重复 learn 同一章
    wg = (project / W_DIR / paths.GROWTH_NAME).read_text(encoding="utf-8")
    assert wg.count("[AI补充·第1章]") == 1, "write-once:同章键只落一次"
    assert len(be.calls) == 1, "已补过的章连 LLM 都不该调"


def test_remap_covers_growth_files(project):
    # 走真实链路:enrich 落成长档案(### [AI补充·第1章] 块头),再重编号 1→3
    _prep_enrich(project)
    enrich_chapter(project, 1, FakeBackend(_ENRICH_OUT))
    remap_supplement_keys(project, {1: 3})
    for rel in (W_DIR, C_DIR):
        g = (project / rel / paths.GROWTH_NAME).read_text(encoding="utf-8")
        assert "[AI补充·第3章]" in g and "第1章" not in g, "插/移章后键必须跟着走,否则 write-once 卡死"


# ── seed 起草:按 H2 拆进目录,绝不覆盖真内容,占位卡功成身退 ─────────────

_DRAFT_OUT = """===世界观===
## 力量体系
体系名:蚀骨阶。共九级,每级异化一处骨骼,代价可见。
## 金手指
重生记忆,回想过度当场昏厥,敌人可用幻术污染记忆反制。
===人物卡===
## 主角·沈砚
- 核心欲望:改写三年后的那一刀。
- 底线:不牵连矿上的老人。
## 反派·赵器
- 立场:黑水商会少东,视主角为耗材。
===卡章纲===
第1章:醒来验伤,遇周楠,章末危机迫近。
第2章:初次动用重生记忆,昏厥暴露弱点。
"""


def test_draft_splits_h2_into_dir_files_and_drops_unnamed(project):
    _reset_dir(project, W_DIR, {
        "力量体系.md": "# 力量体系\n> (占位示例,换成你自己的。)\n- 体系名称:\n",
        "一句话定位.md": "# 一句话定位\n作者手写的真定位,谁也别动。\n",   # 无「占位示例」标记 = 真内容
    })
    _reset_dir(project, C_DIR, {
        "主角·未命名.md": "# 主角 · 未命名\n> (占位示例,换成你自己的。)\n",
    })
    result = draft_brain(project, "重生复仇矿工流", FakeBackend(_DRAFT_OUT))
    assert "世界观" in result["written"] and "人物卡" in result["written"]
    # 世界观:占位的 力量体系.md 被起草覆盖,新出现 金手指.md;真内容文件一字不动
    assert "蚀骨阶" in (project / W_DIR / "力量体系.md").read_text(encoding="utf-8")
    assert (project / W_DIR / "金手指.md").is_file()
    assert "作者手写的真定位" in (project / W_DIR / "一句话定位.md").read_text(encoding="utf-8")
    # 人物:一人一文件,起草成功后仍是占位的「·未命名」模板卡被清掉
    assert (project / C_DIR / "主角·沈砚.md").is_file()
    assert (project / C_DIR / "反派·赵器.md").is_file()
    assert not (project / C_DIR / "主角·未命名.md").exists()


def test_draft_filename_sanitizes_path_separators(project):
    _reset_dir(project, W_DIR, {})
    bad = "===世界观===\n## 地理 / 势力\n安全岛一条、深渊一条、对立势力黑水商会。\n"
    draft_brain(project, "", FakeBackend(bad))
    names = [f.name for f in (project / W_DIR).glob("*.md")]
    assert names and all("/" not in n and "\\" not in n for n in names)
    assert any("地理" in n and "势力" in n for n in names)


# ── 侧栏数据形状:单文件=一行,目录=分组(children) ─────────────────────────

def test_brain_entries_dual_shape(project):
    _reset_dir(project, W_DIR, {
        "力量体系.md": "# 力量体系\n- 凡→蜕凡\n",
        "成长档案.md": "[AI补充·第1章]\n- x\n",
    })
    (project / paths.CHARS_REL).write_text("# 人物卡\n\n## 主角\n- 名字:沈砚\n", encoding="utf-8")
    shutil.rmtree(project / C_DIR, ignore_errors=True)   # 人物走单文件形态
    entries = {e["name"]: e for e in _brain_entries(project)}
    world = entries["世界观"]
    assert [c["name"] for c in world["children"]] == ["力量体系", "成长档案"], "成长档案固定排最后"
    assert all(c["rel"].startswith(W_DIR) for c in world["children"])
    chars = entries["人物卡"]
    assert "children" not in chars and chars["rel"] == paths.CHARS_REL, "单文件形态保持一行"
