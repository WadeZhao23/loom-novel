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


def test_botched_tool_line_not_leaked_as_assistant(project):
    # 未知工具名的协议行绝不作为权威 assistant 泄漏
    evs = []
    run_turn(project, "x", ScriptedBackend(["用:瞎编的工具\n\n用:看地基"]), emit=evs.append, ts="t")
    assert not any(e.get("t") == "assistant" and "用:" in e.get("text", "") for e in evs)
    assert any(e.get("t") == "tool" and e.get("name") == "看地基" for e in evs)   # 真工具仍执行


def test_assistant_emitted_once_per_reply(project):
    evs = []
    run_turn(project, "y", ScriptedBackend(["好的,继续。"]), emit=evs.append, ts="t")
    assert sum(1 for e in evs if e.get("t") == "assistant") == 1   # 不双发射


def test_two_consecutive_botched_tools_terminate_with_trace(project):
    from loom.paths import NAV_TRACE_REL
    evs = []
    run_turn(project, "z", ScriptedBackend(["用:瞎编1", "用:瞎编2", "用:瞎编3"]), emit=evs.append, ts="t")
    # 连续2次botched→终结,不会一直循环到6轮;留痕文件出现 tool_unparsed
    assert (project / NAV_TRACE_REL).is_file()
    assert "tool_unparsed" in (project / NAV_TRACE_REL).read_text(encoding="utf-8")


def test_empty_text_opening_no_user_event(project):
    # 空 text 开场:不落空 user 事件,但伙伴仍开场发言(spec §2 开场幂等,第二道保险)
    evs = []
    run_turn(project, "", ScriptedBackend(["你好,我们从题材聊起?"]), emit=evs.append, ts="t")
    from loom import partner_store
    assert not any(e["t"] == "user" and not e.get("text") for e in partner_store.read_events(project))
    assert any(e["t"] == "assistant" for e in evs)   # 仍开场


def test_empty_text_noop_when_history_exists(project):
    # 已有对话时空 text → no-op 不调模型(防重复开场)
    run_turn(project, "你好", ScriptedBackend(["回1"]), emit=lambda e: None, ts="t1")
    be = ScriptedBackend(["不该被调用"])
    run_turn(project, "", be, emit=lambda e: None, ts="t2")
    assert be.calls == []   # 模型没被调
