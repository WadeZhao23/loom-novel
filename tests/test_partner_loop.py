from loom.partner import run_turn
from conftest import ScriptedBackend


def _collect():
    evs = []
    return evs, (lambda e: evs.append(e))


def test_speech_turn_terminates(project):
    evs, emit = _collect()
    run_turn(project, "你好", ScriptedBackend(["你好呀,我们从金手指聊起?"]), emit=emit, ts="t")
    texts = [e for e in evs if e["t"] == "assistant"]
    assert texts and "金手指" in texts[-1]["text"]


def test_tool_round_then_speak(project):
    evs, emit = _collect()
    be = ScriptedBackend(["看看现状。\n用:看地基", "立项还空着,先定题材吧?"])
    run_turn(project, "帮我看看", be, emit=emit, ts="t")
    kinds = [e["t"] for e in evs]
    assert "tool" in kinds and "result" in kinds
    assert evs[-1]["t"] == "assistant" and "题材" in evs[-1]["text"]


def test_tool_rounds_capped(project):
    evs, emit = _collect()
    be = ScriptedBackend(["用:看地基"] * 10)   # 一直调工具
    run_turn(project, "x", be, emit=emit, ts="t")
    assert sum(1 for e in evs if e["t"] == "tool") <= 6


def test_protocol_line_not_leaked_to_assistant(project):
    evs, emit = _collect()
    # 说话段 + 工具块,流式按 6 字小块吐(含把「用」「:」拆开的边界)
    be = ScriptedBackend(["我查一下金手指。\n用:看地基"], stream=True)
    run_turn(project, "x", be, emit=emit, ts="t")
    for e in evs:
        if e["t"] == "assistant":
            assert "用:" not in e["text"] and "看地基" not in e["text"]


def test_delete_dialogue_keeps_book(project):
    from loom.journey import journey_state
    before = journey_state(project)["current"]
    run_turn(project, "定个题材:重生流", ScriptedBackend(["好"]), emit=lambda e: None, ts="t")
    import shutil
    shutil.rmtree(project / ".伙伴对话")
    assert journey_state(project)["current"] == before   # 删对话,门禁不变
