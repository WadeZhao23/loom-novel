"""测试 L2 · A2A 通信试点:外部 agent 注册解析 + tasks/send 最小闭环 + 领航员「问外部」工具。"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from loom import a2a
from loom.partner_tools import REGISTRY, run_tool


# ── 本地 stub 外部 agent:记录收到的请求,按模式回 A2A 风味响应 ─────────────

class _StubHandler(BaseHTTPRequestHandler):
    """最小 A2A server 试点:收 tasks/send,回 artifacts 形状的 Task。

    回应模式由 path 决定:/a2a 正常;/a2a-error 回 JSON-RPC error;
    /a2a-plain 回最简 {"result": {"text": …}};/a2a-bad 回非 JSON。
    """

    def do_POST(self):  # noqa: N802(stdlib 约定)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.last_request = {"path": self.path, "body": body}
        task_text = body["params"]["message"]["parts"][0]["text"]
        tid = body["params"]["id"]
        if self.path == "/a2a-bad":
            return self._reply_raw(b"not json at all")
        if self.path == "/a2a-error":
            return self._reply({"jsonrpc": "2.0", "id": body.get("id"),
                                "error": {"code": -32000, "message": "stub 内部炸了"}})
        if self.path == "/a2a-plain":
            return self._reply({"result": {"text": f"[plain]{task_text}"}})
        if self.path == "/a2a-long":
            return self._reply({"result": {"text": "长" * 5000}})
        # 默认 /a2a:完整 A2A Task 形状(artifacts)
        return self._reply({
            "jsonrpc": "2.0", "id": body.get("id"),
            "result": {"id": tid, "status": {"state": "completed"},
                       "artifacts": [{"parts": [{"kind": "text", "text": f"[stub 答复]{task_text}"}]}]},
        })

    def _reply(self, payload: dict):
        self._reply_raw(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _reply_raw(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默,不污染测试输出
        pass


@pytest.fixture
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.last_request = None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def _register(project: Path, name: str = "查资料", endpoint: str = "http://127.0.0.1:1/a2a",
              desc: str = "查历史事件与参考作品", extra: str = "") -> Path:
    d = project / a2a.EXTERNAL_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(f"---\n端点: {endpoint}\n说明: {desc}\n{extra}---\n", encoding="utf-8")
    return p


# ── 注册解析 ──────────────────────────────────────────────────────────

def test_list_agents_empty(project: Path):
    assert a2a.list_agents(project) == []


def test_list_agents_parses_frontmatter(project: Path):
    _register(project, endpoint="http://127.0.0.1:9/a2a")
    agents = a2a.list_agents(project)
    assert len(agents) == 1
    a = agents[0]
    assert a.name == "查资料"
    assert a.endpoint == "http://127.0.0.1:9/a2a"
    assert a.desc == "查历史事件与参考作品"
    assert a.timeout == a2a._DEFAULT_TIMEOUT


def test_list_agents_skips_file_without_endpoint(project: Path):
    d = project / a2a.EXTERNAL_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / "坏注册.md").write_text("---\n说明: 没写端点\n---\n", encoding="utf-8")
    assert a2a.list_agents(project) == []


def test_list_agents_timeout_override_and_clamp(project: Path):
    _register(project, "快", extra="超时: 5\n")
    _register(project, "慢", extra="超时: 9999\n")
    _register(project, "乱", extra="超时: 不是数字\n")
    agents = {a.name: a for a in a2a.list_agents(project)}
    assert agents["快"].timeout == 5
    assert agents["慢"].timeout == a2a._MAX_TIMEOUT
    assert agents["乱"].timeout == a2a._DEFAULT_TIMEOUT


def test_briefing_from_body(project: Path):
    p = _register(project)
    p.write_text(p.read_text(encoding="utf-8") + "只答有公开史料支撑的内容。\n", encoding="utf-8")
    (a,) = a2a.list_agents(project)
    assert "公开史料" in a.briefing


# ── 协议客户端(对 stub server 的最小闭环) ─────────────────────────────

def test_send_task_roundtrip(stub_server):
    endpoint = f"http://127.0.0.1:{stub_server.server_port}/a2a"
    agent = a2a.ExternalAgent(name="查资料", endpoint=endpoint, desc="", timeout=5, briefing="")
    text = a2a.send_task(agent, "玄武门之变发生在哪一年?")
    assert text == "[stub 答复]玄武门之变发生在哪一年?"
    # 请求形状:JSON-RPC 2.0 + tasks/send + A2A 风味 message.parts
    req = stub_server.last_request
    body = req["body"]
    assert body["jsonrpc"] == "2.0" and body["method"] == "tasks/send"
    assert body["params"]["message"]["role"] == "user"
    assert body["params"]["message"]["parts"][0]["text"] == "玄武门之变发生在哪一年?"
    assert body["params"]["id"] == a2a.task_id_for("查资料", "玄武门之变发生在哪一年?")


def test_send_task_includes_briefing_metadata(stub_server):
    endpoint = f"http://127.0.0.1:{stub_server.server_port}/a2a"
    agent = a2a.ExternalAgent(name="查资料", endpoint=endpoint, desc="", timeout=5,
                              briefing="只答有出处的")
    a2a.send_task(agent, "随便问")
    assert stub_server.last_request["body"]["params"]["metadata"]["briefing"] == "只答有出处的"


def test_send_task_plain_text_fallback(stub_server):
    endpoint = f"http://127.0.0.1:{stub_server.server_port}/a2a-plain"
    agent = a2a.ExternalAgent(name="查资料", endpoint=endpoint, desc="", timeout=5, briefing="")
    assert a2a.send_task(agent, "问") == "[plain]问"


def test_send_task_jsonrpc_error(stub_server):
    endpoint = f"http://127.0.0.1:{stub_server.server_port}/a2a-error"
    agent = a2a.ExternalAgent(name="查资料", endpoint=endpoint, desc="", timeout=5, briefing="")
    with pytest.raises(a2a.A2AError, match="stub 内部炸了"):
        a2a.send_task(agent, "问")


def test_send_task_connection_refused():
    agent = a2a.ExternalAgent(name="查资料", endpoint="http://127.0.0.1:1/a2a",
                              desc="", timeout=2, briefing="")
    with pytest.raises(a2a.A2AError, match="连不上"):
        a2a.send_task(agent, "问")


def test_send_task_non_json_response(stub_server):
    endpoint = f"http://127.0.0.1:{stub_server.server_port}/a2a-bad"
    agent = a2a.ExternalAgent(name="查资料", endpoint=endpoint, desc="", timeout=5, briefing="")
    with pytest.raises(a2a.A2AError, match="不是 JSON"):
        a2a.send_task(agent, "问")


def test_send_task_rejects_non_http_scheme():
    agent = a2a.ExternalAgent(name="坏", endpoint="file:///etc/passwd", desc="", timeout=5, briefing="")
    with pytest.raises(a2a.A2AError, match="http"):
        a2a.send_task(agent, "问")


def test_task_id_deterministic():
    assert a2a.task_id_for("查资料", "问A") == a2a.task_id_for("查资料", "问A")
    assert a2a.task_id_for("查资料", "问A") != a2a.task_id_for("查资料", "问B")


# ── 领航员「问外部」工具 ───────────────────────────────────────────────

def test_wanwai_registered():
    assert "问外部" in REGISTRY
    spec = REGISTRY["问外部"]
    assert spec.mutates is False
    assert "对象" in spec.params and "任务" in spec.params


def test_render_contract_lists_wanwai():
    assert "问外部" in REGISTRY and "问外部" in __import__("loom.partner_tools", fromlist=["render_contract"]).render_contract()


def test_wanwai_no_agents_guidance(project: Path):
    ev = run_tool(project, "问外部", {"对象": "", "任务": ""}, ts="t")
    assert ev["t"] == "result"
    assert "agents/外部/" in ev["text"]   # 教作者怎么注册


def test_wanwai_lists_agents_when_target_empty(project: Path, stub_server):
    _register(project, endpoint=f"http://127.0.0.1:{stub_server.server_port}/a2a")
    ev = run_tool(project, "问外部", {"对象": "", "任务": ""}, ts="t")
    assert ev["t"] == "result"
    assert "查资料" in ev["text"] and "查历史事件" in ev["text"]


def test_wanwai_full_loop(project: Path, stub_server):
    """最小闭环:注册 → 领航员工具发 Task → stub 答复回喂成 result 事件。"""
    _register(project, endpoint=f"http://127.0.0.1:{stub_server.server_port}/a2a")
    ev = run_tool(project, "问外部", {"对象": "查资料", "任务": "玄武门之变发生在哪一年?"}, ts="t")
    assert ev["t"] == "result"
    assert "[stub 答复]玄武门之变发生在哪一年?" in ev["text"]
    assert stub_server.last_request is not None   # 真的打出去了


def test_wanwai_unknown_agent_error_lists_available(project: Path):
    _register(project)
    ev = run_tool(project, "问外部", {"对象": "不存在", "任务": "问"}, ts="t")
    assert "error" in ev
    assert "查资料" in ev["error"]   # 自纠提示带上已注册名


def test_wanwai_empty_task_raises(project: Path):
    _register(project)
    ev = run_tool(project, "问外部", {"对象": "查资料", "任务": ""}, ts="t")
    assert "error" in ev and "任务" in ev["error"]


def test_wanwai_unreachable_agent_becomes_error_event(project: Path):
    _register(project, endpoint="http://127.0.0.1:1/a2a")   # 连不上
    ev = run_tool(project, "问外部", {"对象": "查资料", "任务": "问"}, ts="t")
    assert "error" in ev and "连不上" in ev["error"]   # 不炸对话循环,回喂模型


def test_wanwai_reply_truncated_to_budget(project: Path, stub_server):
    _register(project, endpoint=f"http://127.0.0.1:{stub_server.server_port}/a2a-long")
    ev = run_tool(project, "问外部", {"对象": "查资料", "任务": "问"}, ts="t")
    assert ev["t"] == "result"
    assert "已截断" in ev["text"]
    assert len(ev["text"]) <= 3000 + len("外部 agent「查资料」答复:\n") + 80
