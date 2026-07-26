"""A2A(Agent-to-Agent)通信试点:领航员代作者向外部 agent 发 Task(L2)。

- **注册**(用户自行创建):书根 `agents/外部/<名字>.md`,**文件名即 agent 名**(同
  「人物一人一卡,文件名即专名」惯例);frontmatter 三键:`端点`(http/https,必填)、
  `说明`(给领航员看的用途一句话)、`超时`(秒,可省,默认 30)。正文(可选)作为
  背景说明随任务一并发出(params.metadata.briefing)。
- **协议**(试点,不求完整 A2A 标准):JSON-RPC 2.0 信封、`method=tasks/send`,
  message 一个 text 段;响应按 A2A Task 形状取文本——`artifacts[].parts[].text` →
  `status.message.parts[].text` → `result.text`/裸 `{"text": ...}` 依次兜底,
  兼容「完整 A2A server」和「最简试点 stub」两端的实现厚度。
- **红线**:端点只来自用户手写的书内文件,**不接受模型拼 URL**(SSRF 面收敛到
  「用户写错了自己的文件」);只发 http/https;task_id 由内容哈希派生,不读挂钟、
  不生成随机数(与 partner_tools.run_tool 同一条纪律)。
- 失败的形状:一切网络/协议错误收敛成 `A2AError`(ValueError 子类)——
  partner_tools.run_tool 把它兜成 result 事件的 error 字段回喂模型自纠,不炸对话循环。
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .agents import _parse_frontmatter

EXTERNAL_DIR_REL = "agents/外部"   # 外部 agent 注册目录(相对书根;文件名即 agent 名)

_DEFAULT_TIMEOUT = 30   # 秒;frontmatter「超时」可覆盖
_MAX_TIMEOUT = 120      # 秒;手填超时钳制上界,防一个挂死的端点把整轮对话拖死


class A2AError(ValueError):
    """A2A 通信失败(网络/HTTP/协议形状)的统一出口;ValueError 子类,run_tool 直接兜。"""


@dataclass(frozen=True)
class ExternalAgent:
    name: str          # 文件名(去 .md),即注册名
    endpoint: str      # frontmatter「端点」
    desc: str          # frontmatter「说明」(给领航员挑 agent 用)
    timeout: int       # 秒
    briefing: str      # 正文(可选),随任务同发的背景说明


def _parse_agent_file(path: Path) -> ExternalAgent | None:
    """解析一份注册文件;缺「端点」返回 None(坏文件跳过,与 jsonl「坏行跳过」同纪律)。"""
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    endpoint = str(meta.get("端点", "") or "").strip()
    if not endpoint:
        return None
    try:
        timeout = int(str(meta.get("超时", "") or _DEFAULT_TIMEOUT))
    except ValueError:
        timeout = _DEFAULT_TIMEOUT
    timeout = max(1, min(_MAX_TIMEOUT, timeout))
    return ExternalAgent(
        name=path.stem,
        endpoint=endpoint,
        desc=str(meta.get("说明", "") or "").strip(),
        timeout=timeout,
        briefing=body.strip(),
    )


def list_agents(root: Path | str) -> list[ExternalAgent]:
    """书根 `agents/外部/` 下全部有效注册(名字排序稳定;缺端点的坏文件跳过)。"""
    d = Path(root) / EXTERNAL_DIR_REL
    if not d.is_dir():
        return []
    out: list[ExternalAgent] = []
    for p in sorted(d.glob("*.md")):
        agent = _parse_agent_file(p)
        if agent is not None:
            out.append(agent)
    return out


def task_id_for(agent_name: str, task_text: str) -> str:
    """确定性 task_id(内容哈希派生,不读挂钟/不生成随机数)。"""
    digest = hashlib.sha1(f"{agent_name}\n{task_text}".encode("utf-8")).hexdigest()
    return f"a2a-{digest[:12]}"


def _extract_text(payload: dict) -> str:
    """从 A2A 风味响应里取文本:剥 JSON-RPC 信封后,artifacts → status.message → text 兜底。"""
    if "error" in payload and payload["error"]:
        err = payload["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise A2AError(f"外部 agent 返回错误:{msg}")
    result = payload.get("result", payload)
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        raise A2AError("响应形状不认识(既不是文本也不是 Task)。")
    texts: list[str] = []
    for artifact in result.get("artifacts") or []:
        if isinstance(artifact, dict):
            for part in artifact.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
    if texts:
        return "\n".join(texts)
    status = result.get("status")
    if isinstance(status, dict):
        message = status.get("message")
        if isinstance(message, dict):
            for part in message.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
    if texts:
        return "\n".join(texts)
    if result.get("text"):
        return str(result["text"])
    raise A2AError("响应里没有可取的文本(artifacts/status.message/text 都空)。")


def send_task(agent: ExternalAgent, task_text: str, *, task_id: str | None = None) -> str:
    """向外部 agent 发一个 Task,取回答复文本。一切失败收敛成 A2AError。"""
    if not agent.endpoint.startswith(("http://", "https://")):
        raise A2AError(f"端点只支持 http/https:「{agent.endpoint}」。")
    tid = task_id or task_id_for(agent.name, task_text)
    params: dict = {
        "id": tid,
        "message": {"role": "user", "parts": [{"kind": "text", "text": task_text}]},
    }
    if agent.briefing:
        params["metadata"] = {"briefing": agent.briefing}
    envelope = {"jsonrpc": "2.0", "id": tid, "method": "tasks/send", "params": params}
    req = urllib.request.Request(
        agent.endpoint,
        data=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=agent.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise A2AError(f"外部 agent「{agent.name}」HTTP {e.code}:{e.reason}。") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise A2AError(f"连不上外部 agent「{agent.name}」({agent.endpoint}):{e}") from e
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise A2AError(f"外部 agent「{agent.name}」回的不是 JSON:{raw[:200]}") from e
    if not isinstance(payload, dict):
        raise A2AError(f"外部 agent「{agent.name}」响应形状不认识(顶层不是对象)。")
    return _extract_text(payload)
