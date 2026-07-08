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
