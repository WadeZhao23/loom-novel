"""章节字数失控修复:字数=软指令进各棒 prompt + 终稿超长留痕(不阻断)。

根因:chapter_chars 以前只流向 max_tokens 预算,从未进 prompt——DeepSeek 思考型预算故意宽
(防截断/空响应),模型等于零字数约束自由发挥。修法是「说」不是「截」:max_tokens 不动。
"""
from __future__ import annotations

from loom.agents import Agent, _build_user_prompt, _length_hint, regen_outline, run_pipeline
from loom.config import Config

from conftest import FakeBackend

LONG = "他屏住呼吸,后背贴着冰冷的石头。" * 30   # 480 实字(去空白),过各闸


def _capture() -> FakeBackend:
    def responder(system, user):
        return "矿洞惊变" if "章节标题" in system else LONG
    return FakeBackend(responder)


def _user_of(backend: FakeBackend, produces: str) -> str:
    hits = [u for _, u in backend.calls if f"产出【{produces}】" in u]
    assert hits, f"没找到产出【{produces}】的调用"
    return hits[-1]


# ── 各棒 prompt 带角色化字数指令 ─────────────────────────────────────

def test_pipeline_prompts_carry_length_hints(project):
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=2400, gate_rounds=0)
    run_pipeline(project, 1, be, cfg)

    writer = _user_of(be, "本章初稿")
    assert "正文约 2400 字(±20%)" in writer
    assert "写满即收、宁短勿长" in writer
    # 编辑/润色师:压缩授权(超目标压回来,删冗余不删情节,绝不扩写)
    assert "篇幅目标约 2400 字" in _user_of(be, "本章改稿")
    assert "绝不扩写" in _user_of(be, "本章改稿")
    assert "篇幅目标约 2400 字" in _user_of(be, "本章终稿")
    # 设定师沿用 _SHORT 的 350
    assert "≤350 字" in _user_of(be, "本章设定锚点")
    # 大纲师:结构闸——知道章目标、按目标定场次、每场标字数预算(超长的真根因在这)
    outliner = _user_of(be, "本章场景骨头(分镜细纲)")
    # 细纲上限不再是写死的 450,按章目标现算(2400 → (3,4) 档 → 200+350×4=1600)。
    # 450 是 spec §10.4 的自相矛盾:真机 20/20 全部越线,它从来不是约束。
    from loom.agents import outline_budget
    assert f"细纲本身 ≤{outline_budget(2400)} 字" in outliner
    assert outline_budget(2400) == 1600
    assert "本章正文目标约 2400 字" in outliner
    assert "拆 3-4 场" in outliner            # 2400 字 → 3-4 场,不再放任 5-6 场撑爆篇幅
    assert "约X字」的篇幅预算" in outliner


def test_scene_budget_scales_with_target(project):
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=1200, gate_rounds=0)
    run_pipeline(project, 1, be, cfg)
    assert "拆 2-3 场" in _user_of(be, "本章场景骨头(分镜细纲)")   # 短章更少场次


def test_regen_outline_prompts_carry_length_hints(project):
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=2400, gate_rounds=0)
    regen_outline(project, 1, be, cfg)

    assert "≤350 字" in _user_of(be, "本章设定锚点")
    outliner = _user_of(be, "本章场景骨头(分镜细纲)")
    assert "本章正文目标约 2400 字" in outliner and "拆 3-4 场" in outliner   # 与主线同口径


# ── golden:除任务行新增的字数句外,prompt 逐字节不变 ────────────────

def test_prompt_unchanged_except_length_sentence():
    agent = Agent(name="写手", produces="本章初稿")
    args = (3, "写手", agent, "知识块", "上一章结尾。", [("本章设定锚点", "锚点内容")], "硬设定块")
    old = _build_user_prompt(*args)
    new = _build_user_prompt(*args, target_chars=2400, chapter_target=2400)
    hint = _length_hint("写手", 2400, 2400)
    assert hint and hint in new
    assert new.replace(hint, "", 1) == old   # 上下文拼装没被顺手改坏


# ── 终稿超长 → 留痕提醒,但绝不阻断出稿 ─────────────────────────────

def test_overlong_final_flags_note_but_does_not_block(project):
    be = _capture()   # LONG=480 实字 > 300*1.5
    cfg = Config(provider="deepseek", model="x", chapter_chars=300, gate_rounds=0)
    path, final = run_pipeline(project, 1, be, cfg)

    assert (project / "正文" / "第1章.md").exists()          # 出稿没被拦
    note = (project / ".审稿留痕" / "第1章.md").read_text(encoding="utf-8")
    assert "篇幅提醒" in note
    assert "本章 480 字,超出目标 300 字较多" in note
    assert "注水" in note


def test_normal_length_final_leaves_no_note(project):
    be = _capture()   # 480 实字 ≤ 400*1.5
    cfg = Config(provider="deepseek", model="x", chapter_chars=400, gate_rounds=0)
    run_pipeline(project, 1, be, cfg)

    p = project / ".审稿留痕" / "第1章.md"
    assert not p.exists() or "篇幅提醒" not in p.read_text(encoding="utf-8")


# ── spec §10.1:编辑不再失明 ────────────────────────────────────────────
# 它的 12 项自检里「承诺兑现/章首衔接/时间连续性/物品·状态连续性」四项此前结构上
# 拿不到材料——StepSpec("编辑") 既无 wants_prev 也无 wants_state,只能靠 ≤350 字锚点转述。

def test_editor_now_sees_prev_chapter(project):
    """承诺兑现/章首衔接/时间连续性:要对照上一章原件,不是锚点的二手转述。"""
    (project / "正文").mkdir(exist_ok=True)
    (project / "正文" / "第1章.md").write_text(
        "# 旧章\n\n上一章的结尾钩子:矿道尽头有人提灯走来。", encoding="utf-8")
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=600, gate_rounds=0)
    run_pipeline(project, 2, be, cfg)
    editor = _user_of(be, "本章改稿")
    assert "## 上一章正文" in editor
    assert "矿道尽头有人提灯走来" in editor


def test_editor_now_sees_statebook(project):
    """物品/状态连续性:自检原文就写着「对照状态账本」,此前编辑一个字都读不到。"""
    from loom import paths
    p = project / paths.STATEBOOK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    # 格式必须合 statebook 的 _SEC_RE/_LINE_RE,否则 parse_book 宽容跳过、快照恒空
    p.write_text("# 状态账本\n\n## 第1章\n- [物品] 半块旧矿牌:拾得,仍在沈砚手上\n",
                 encoding="utf-8")
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=600, gate_rounds=0)
    # 用第 2 章:快照取的是 snapshot_for(root, chapter_n - 1),第 1 章的上游是第 0 章、恒空
    run_pipeline(project, 2, be, cfg)
    editor = _user_of(be, "本章改稿")
    assert "## 当前状态" in editor and "半块旧矿牌" in editor


def test_editor_still_denied_hardfacts(project):
    """刻意不给编辑硬设定逐字块:那是写手防专名漂移用的,编辑吃了只是灌 token。
    拆 wants_state / wants_hardfacts 两个开关的意义就在这——别图省事合并回去。"""
    d = project / "外置大脑" / "世界观"
    d.mkdir(parents=True, exist_ok=True)
    (d / "力量体系.md").write_text("# 力量体系\n\n- 逆息:吸灵反噬。\n", encoding="utf-8")
    be = _capture()
    cfg = Config(provider="deepseek", model="x", chapter_chars=600, gate_rounds=0)
    run_pipeline(project, 1, be, cfg)
    assert "## 硬设定" not in _user_of(be, "本章改稿")
    assert "## 硬设定" in _user_of(be, "本章初稿")      # 写手照旧拿得到
