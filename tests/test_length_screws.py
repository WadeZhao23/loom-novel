"""字数五螺丝:确定性反馈环治字数飘忽(字数五螺丝 spec)。"""
from loom.agents import _length_hint, _flag_overlong


def test_length_hint_injects_actual_when_over():
    # step_budget 传章目标(编辑/润色的 short_budget 为 None→config.chapter_chars);0 会走开头早退
    h = _length_hint("编辑", 800, 800, actual_chars=1200)
    assert "原稿实测 1200 字" in h and "目标 800 字" in h and "超 50%" in h
    assert "压回目标量级" in h and "绝不扩写" in h


def test_length_hint_generic_when_under_or_no_actual():
    # 达标/没给实测 → 保持原通用文案(不对合格稿瞎压;golden fixture 稿<目标走这支)
    under = _length_hint("编辑", 800, 800, actual_chars=600)
    none = _length_hint("润色师", 800, 800)
    assert "原稿实测" not in under and "篇幅目标约 800 字" in under
    assert "原稿实测" not in none and "篇幅目标约 800 字" in none


def test_length_hint_writer_and_outliner_unaffected():
    assert "原稿实测" not in _length_hint("写手", 800, 800, actual_chars=9999)
    assert "原稿实测" not in _length_hint("大纲师", 450, 800, actual_chars=9999)


def test_overlong_threshold_and_event(project):
    from loom import events
    seen = []
    # 目标 800:900 字(1.125x)不报;1100 字(1.375x>1.25)报 + 发 overlong 事件
    _flag_overlong(project, 1, "# 标题\n\n" + "字" * 900, 800, seen.append)
    assert not any(e["type"] == "overlong" for e in seen)
    _flag_overlong(project, 2, "# 标题\n\n" + "字" * 1100, 800, seen.append)
    assert any(e["type"] == "overlong" and e["chars"] == 1100 and e["target"] == 800 for e in seen)
    assert "篇幅提醒" in (project / ".审稿留痕/第2章.md").read_text(encoding="utf-8")


def test_overlong_event_contract():
    from loom import events
    ev = events.overlong(3, 1500, 800)
    assert ev == {"type": "overlong", "chapter": 3, "chars": 1500, "target": 800}


def test_parse_scene_budgets():
    from loom.agents import _parse_scene_budgets
    assert _parse_scene_budgets("分镜一(约300字):验伤。分镜二(约 500 字):遇敌。") == [300, 500]
    assert _parse_scene_budgets("分镜一:验伤。分镜二:遇敌。") == []   # 没标 → 空


def test_check_scene_budget_flags_missing_and_drift(project):
    from loom.agents import _check_scene_budget
    a, b, c = [], [], []
    # ④ 大纲师产出:一场都没标 → warn
    _check_scene_budget(project, 1, "分镜一:验伤。分镜二:遇敌。", 2000, False, a.append)
    assert any(e["type"] == "warn" for e in a)
    # ④ 标了但总和(2600)与目标(2000)偏差 30% 内 → 不报
    _check_scene_budget(project, 1, "一(约1200字)。二(约1400字)。", 2000, False, b.append)
    assert not any(e["type"] == "warn" for e in b)
    # ⑤ WYSIWYG 沿用:旧细纲总和(约6000)与当前目标(2000)差得多 → info 提示重新生成
    _check_scene_budget(project, 1, "一(约3000字)。二(约3000字)。", 2000, True, c.append)
    assert any(e["type"] == "info" and "重新生成" in e["message"] for e in c)


def test_templates_drop_hardcoded_scene_count():
    from loom.scaffold import TEMPLATES_DIR
    outliner = (TEMPLATES_DIR / "agents/大纲师.md").read_text(encoding="utf-8")
    engine = (TEMPLATES_DIR / "skills/故事引擎.md").read_text(encoding="utf-8")
    assert "3-6 个场景" not in outliner and "3-6 个场景" not in engine
    assert "字数预算为准" in outliner   # 改成以任务预算为准
