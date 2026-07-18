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


def test_multi_tishe_emits_multiple_proposals(project):
    # FB-B:一条消息连发多个「提设定」→ 一轮内 emit 多张 proposal(唯一 id),引子(say)在卡前
    evs, emit = _collect()
    be = ScriptedBackend([
        "我给你两个方向挑:\n用:提设定\n落点:外置大脑/立项卡.md#分区\n内容:玄幻\n"
        "用:提设定\n落点:外置大脑/立项卡.md#分区\n内容:都市",
        "两个方向都提了,你挑一个。"])
    run_turn(project, "定分区", be, emit=emit, ts="t")
    proposals = [e for e in evs if e["t"] == "proposal"]
    assert [p["content"] for p in proposals] == ["玄幻", "都市"]   # 两张卡都出
    assert proposals[0]["id"] != proposals[1]["id"]               # 唯一 id
    kinds = [e["t"] for e in evs]
    assert kinds.index("assistant") < kinds.index("proposal")    # 引子在卡之前(顺序正)


def test_multi_tools_capped_per_message(project):
    # 一条消息里超过 3 个「提设定」→ 只执行前 3(护栏防刷屏)
    evs, emit = _collect()
    blocks = "\n".join(f"用:提设定\n落点:外置大脑/立项卡.md#分区\n内容:方向{i}" for i in range(5))
    be = ScriptedBackend(["给你几个:\n" + blocks, "提完了。"])
    run_turn(project, "x", be, emit=emit, ts="t")
    assert len([e for e in evs if e["t"] == "proposal"]) == 3     # ≤3 卡/消息


def test_empty_text_advances_after_confirm(project):
    # bug4下一步:落盘(confirm)后空 text 放行,领航员自动引下一格(不再 no-op、不需假user气泡)
    from loom import partner_store as ps
    ps.append_event(project, {"t": "user", "ts": "t0", "text": "定题材"})
    ps.append_event(project, {"t": "confirm", "ts": "t1", "id": "p1", "landed": "外置大脑/立项卡.md"})
    evs, emit = _collect()
    be = ScriptedBackend(["好,题材定了,接下来定世界观?"])
    run_turn(project, "", be, emit=emit, ts="t2")
    assert be.calls                                    # 模型被调了(没 no-op)
    assert any(e["t"] == "assistant" for e in evs)     # 领航员接着说了下一步
    assert not any(e["t"] == "user" for e in evs)      # 空 text 不落假 user 事件


def test_should_cancel_returns_before_any_complete(project):
    evs, emit = _collect()
    be = ScriptedBackend(["不该被调用"])
    run_turn(project, "你好", be, emit=emit, ts="t", should_cancel=lambda: True)
    assert be.calls == []                       # 顶部即取消,complete 从未调用
    assert any(e["t"] == "user" for e in evs)   # user 事件在循环前已落(不丢)


def test_should_cancel_stops_at_round_boundary(project):
    evs, emit = _collect()
    be = ScriptedBackend(["用:看地基"] * 10)     # 不取消会跑满 6 轮工具
    n = {"i": 0}
    def sc():
        n["i"] += 1
        return n["i"] > 2                        # 前两轮顶放行,第三轮顶取消
    run_turn(project, "x", be, emit=emit, ts="t", should_cancel=sc)
    assert len(be.calls) == 2                     # 只跑两轮 complete,第三轮顶提前 return


def test_should_cancel_none_is_unchanged(project):
    evs, emit = _collect()
    be = ScriptedBackend(["用:看地基"] * 10)
    run_turn(project, "x", be, emit=emit, ts="t", should_cancel=None)
    assert sum(1 for e in evs if e["t"] == "tool") <= 6   # 与 test_tool_rounds_capped 一致,行为不变
