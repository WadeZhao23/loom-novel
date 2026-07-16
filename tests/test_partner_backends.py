"""P3:DemoBackend 领航员·伙伴对话分支的脚本化多轮罐头 + CLI 后端反 agent 护栏的
agent_mode 伙伴变体(spec 2026-07-16-navigator-agent-design.md §3/§8)。"""
from __future__ import annotations

from types import SimpleNamespace

from loom.backends import ClaudeCodeBackend, CodexBackend, DemoBackend
from loom.config import Config
from loom.partner import run_turn


# ---- DemoBackend 领航员·伙伴对话分支:脚本化多轮(§8) ----
# 轮数从每轮重拼进 user 的对话尾部数 assistant 事件推断,DemoBackend 本身保持无状态。

def _demo():
    return DemoBackend(Config())


def test_demo_partner_opens_with_greeting(project):
    evs = []
    run_turn(project, "你好", _demo(), emit=evs.append, ts="t1")
    texts = [e["text"] for e in evs if e["t"] == "assistant"]
    assert len(texts) == 1
    assert "(demo)" in texts[0]
    assert not any(e["t"] in ("tool", "proposal") for e in evs)   # 开场不该带工具


def test_demo_partner_asks_on_second_turn(project):
    run_turn(project, "你好", _demo(), emit=lambda e: None, ts="t1")
    evs = []
    run_turn(project, "准备好了", _demo(), emit=evs.append, ts="t2")
    texts = [e["text"] for e in evs if e["t"] == "assistant"]
    assert len(texts) == 1
    assert "(demo)" in texts[0] and "?" in texts[0]   # 第二轮该是提问,不是重复问候


def test_demo_partner_proposes_slot_candidate_on_third_turn(project):
    run_turn(project, "你好", _demo(), emit=lambda e: None, ts="t1")
    run_turn(project, "准备好了", _demo(), emit=lambda e: None, ts="t2")
    evs = []
    run_turn(project, "废土复仇流吧", _demo(), emit=evs.append, ts="t3")
    kinds = [e["t"] for e in evs]
    assert "tool" in kinds and "proposal" in kinds   # 用:提设定 真被解析执行

    tool_ev = next(e for e in evs if e["t"] == "tool")
    assert tool_ev["name"] == "提设定"

    proposal_ev = next(e for e in evs if e["t"] == "proposal")
    assert proposal_ev["slot"] == "外置大脑/立项卡.md#题材"
    assert "(demo" in proposal_ev["content"]

    # 提设定是 mutates 工具、不终结本轮:demo 紧接着回喂再 complete 一次收尾,
    # 一次 run_turn 调用里应看到两条 assistant(候选卡说明 + 收尾)。
    assistant_texts = [e["text"] for e in evs if e["t"] == "assistant"]
    assert len(assistant_texts) == 2
    assert all("(demo)" in t for t in assistant_texts)


def test_demo_partner_stays_wrapped_on_later_turns(project):
    for i, msg in enumerate(["你好", "准备好了", "废土复仇流吧"], start=1):
        run_turn(project, msg, _demo(), emit=lambda e: None, ts=f"t{i}")
    evs = []
    run_turn(project, "还有别的吗", _demo(), emit=evs.append, ts="t4")
    texts = [e["text"] for e in evs if e["t"] == "assistant"]
    assert len(texts) == 1 and "(demo)" in texts[0]
    assert not any(e["t"] in ("tool", "proposal") for e in evs)   # 收尾稳定,不再反复提案


# ---- run_turn 对伙伴通道调用 complete 时传 agent_mode=True ----

def test_run_turn_passes_agent_mode_true_to_backend_that_declares_it(project):
    calls = []

    class Probe:
        def complete(self, system, user, *, max_chars=None, on_chunk=None, agent_mode=False):
            calls.append(agent_mode)
            return "(demo)好的。"

    run_turn(project, "你好", Probe(), emit=lambda e: None, ts="t1")
    assert calls == [True]


def test_run_turn_tolerates_backend_without_agent_mode_param(project):
    # 旧假后端(不声明 agent_mode,如 tests/conftest.py 的 ScriptedBackend/FakeBackend)
    # 不该被新增的关键字参数炸掉——这里钉一个等价的最简后端复现同样的签名形状。
    calls = []

    class Legacy:
        def complete(self, system, user, *, max_chars=None, on_chunk=None):
            calls.append((system, user))
            return "好的。"

    run_turn(project, "你好", Legacy(), emit=lambda e: None, ts="t1")
    assert len(calls) == 1   # 没有因为多传 agent_mode 而 TypeError


# ---- CLI 后端护栏:agent_mode 伙伴变体解除「禁止工具/禁止反问」,五工序默认仍拦 ----

def _fake_subprocess_run(captured):
    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="好的。", stderr="")
    return _run


def test_claude_default_keeps_anti_agent_guard(monkeypatch):
    monkeypatch.setattr("loom.backends.shutil.which", lambda name: "/usr/bin/claude")
    captured: dict = {}
    monkeypatch.setattr("loom.backends.subprocess.run", _fake_subprocess_run(captured))
    be = ClaudeCodeBackend(Config(provider="claude", model="sonnet"))
    be.complete("系统", "用户")   # 不传 agent_mode → 默认 False,五工序旧护栏原样生效
    prompt = captured["cmd"][2]
    assert "调用或提及任何工具" in prompt
    assert "、反问、" in prompt


def test_claude_agent_mode_allows_tool_block_and_question(monkeypatch):
    monkeypatch.setattr("loom.backends.shutil.which", lambda name: "/usr/bin/claude")
    captured: dict = {}
    monkeypatch.setattr("loom.backends.subprocess.run", _fake_subprocess_run(captured))
    be = ClaudeCodeBackend(Config(provider="claude", model="sonnet"))
    be.complete("系统", "用户", agent_mode=True)
    prompt = captured["cmd"][2]
    assert "调用或提及任何工具" not in prompt
    assert "、反问、" not in prompt
    assert "--allowed-tools" in captured["cmd"]   # 真实工具执行仍锁死,只解除口头护栏
    assert captured["cmd"][captured["cmd"].index("--allowed-tools") + 1] == ""


def test_codex_default_keeps_anti_agent_guard(monkeypatch):
    monkeypatch.setattr("loom.backends.shutil.which", lambda name: "/usr/bin/codex")
    captured: dict = {}
    monkeypatch.setattr("loom.backends.subprocess.run", _fake_subprocess_run(captured))
    be = CodexBackend(Config(provider="codex", model=""))
    be.complete("系统", "用户")
    prompt = captured["cmd"][-1]
    assert "调用或提及任何工具" in prompt
    assert "、反问、" in prompt


def test_codex_agent_mode_allows_tool_block_and_question(monkeypatch):
    monkeypatch.setattr("loom.backends.shutil.which", lambda name: "/usr/bin/codex")
    captured: dict = {}
    monkeypatch.setattr("loom.backends.subprocess.run", _fake_subprocess_run(captured))
    be = CodexBackend(Config(provider="codex", model=""))
    be.complete("系统", "用户", agent_mode=True)
    prompt = captured["cmd"][-1]
    assert "调用或提及任何工具" not in prompt
    assert "、反问、" not in prompt
    assert "read-only" in captured["cmd"]   # 真实工具执行仍锁死在只读沙箱
