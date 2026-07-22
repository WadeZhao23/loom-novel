"""引擎进度事件契约——引擎↔CLI↔webui 三端的**单一真相**。

引擎(agents/gates/fingerprint/draft/enrich/recap/rewrite/deconstruct/server)只通过
progress(event: dict) 回调发事件;每种事件在这里有且只有一个构造函数,type 值 = 函数名。
新增/改名事件只改这里 + 消费端,tests/test_events_contract.py 会钉住:
  ① 每个构造函数的键集合;② CLI(_render)/webui(app.js handleEvent)的消费覆盖;
  ③ 引擎源码里不许再出现内联 {"type": ...}(防回潮)。

既有不变量:事件是 fire-and-forget——引擎的正确性**绝不依赖**事件被谁消费;
没人听也照常出稿(CLI / webui 各自只挑自己关心的渲染)。

消费口径备忘(哪端有意不听哪些,豁免清单同步在契约测试里):
- outline_done:CLI 打一行提示;webui **有意不消费**(重新生成细纲走 /api/outline/regen
  的 JSON 响应 + 自己的按钮态,不走事件流)。
- seed_done / learn_done / recap_* / enrich_* / draft_done:webui 侧这些流程走 JSON
  端点(server 收集或干脆不传 progress),不走 ndjson 事件流,故 handleEvent 不认识它们。
"""

from __future__ import annotations

from typing import Callable

# type 值 → 构造函数 的注册表(全部事件类型的清单,契约测试遍历它)
EVENT_TYPES: dict[str, Callable[..., dict]] = {}


def _event(fn: Callable[..., dict]) -> Callable[..., dict]:
    """登记构造函数:函数名即事件 type 值。"""
    EVENT_TYPES[fn.__name__] = fn
    return fn


# ── 织章流水线(agents.run_pipeline / regen_outline) ──────────────────────────

@_event
def pipeline_start(chapter: int, roles: list) -> dict:
    """流水线开跑:本章 + 角色棒次表(webui 用它画 pill 进度条)。"""
    return {"type": "pipeline_start", "chapter": chapter, "roles": roles}


@_event
def agent_start(role: str) -> dict:
    return {"type": "agent_start", "role": role}


@_event
def agent_chunk(role: str, delta: str) -> dict:
    """流式增量:某一棒边写边吐的一段字。"""
    return {"type": "agent_chunk", "role": role, "delta": delta}


@_event
def agent_done(role: str, produces: str) -> dict:
    return {"type": "agent_done", "role": role, "produces": produces}


@_event
def agent_skip(role: str, reason: str) -> dict:
    """断点续跑:该棒已完成且上游未变,跳过。"""
    return {"type": "agent_skip", "role": role, "reason": reason}


@_event
def edit_note(chapter: int, path) -> dict:
    """审稿留痕已落盘(编辑留痕 / gate 残留 / 超长提醒共用)。"""
    return {"type": "edit_note", "chapter": chapter, "path": str(path)}


@_event
def overlong(chapter: int, chars: int, target: int) -> dict:
    """终稿超长(超目标 1.25x):独立提醒事件,前端可专门标「可能注水」。非阻断。"""
    return {"type": "overlong", "chapter": chapter, "chars": chars, "target": target}


@_event
def debug_report(chapter: int, issues: list, path) -> dict:
    """除虫报告(非阻断附赠):issues 为 BugItem.as_dict 列表,空列表=未发现矛盾。"""
    return {"type": "debug_report", "chapter": chapter, "issues": issues, "path": str(path)}


@_event
def sensitive(chapter: int, count: int, hits: list) -> dict:
    """违禁词粗筛命中:只提示、绝不阻断(hits 里每条含 word/count)。"""
    return {"type": "sensitive", "chapter": chapter, "count": count, "hits": hits}


@_event
def chapter_done(chapter: int, path, title: str, chars: int, preview: str, text: str) -> dict:
    """本章终稿已落盘(chars=正文体字数;preview=前 300 字;text=含 H1 的全文)。"""
    return {"type": "chapter_done", "chapter": chapter, "path": str(path), "title": title,
            "chars": chars, "preview": preview, "text": text}


@_event
def outline_done(chapter: int) -> dict:
    """细纲重新生成完成(agents.regen_outline)。CLI 打一行提示;webui 有意不消费(见模块头)。"""
    return {"type": "outline_done", "chapter": chapter}


# ── 质量关卡(gates.run_gate;issues 里每条是 Issue.as_dict:类别/问题/证据) ──

@_event
def gate_start(label: str, role: str, round: int) -> dict:
    return {"type": "gate_start", "label": label, "role": role, "round": round}


@_event
def gate_pass(label: str, role: str, round: int) -> dict:
    return {"type": "gate_pass", "label": label, "role": role, "round": round}


@_event
def gate_issues(label: str, role: str, round: int, issues: list, issues_detail: list | None = None) -> dict:
    """复审挑出硬伤清单(中文键 类别/问题/证据 是既有前端契约,别动)。

    issues_detail(可选):每条 {category, severity, paragraph_index, original_text, suggestion}
    的增强数据,供前端审稿报告面板使用。
    """
    ev = {"type": "gate_issues", "label": label, "role": role, "round": round, "issues": issues}
    if issues_detail is not None:
        ev["issues_detail"] = issues_detail
    return ev


@_event
def gate_revise(label: str, role: str, round: int) -> dict:
    return {"type": "gate_revise", "label": label, "role": role, "round": round}


@_event
def gate_exhausted(label: str, role: str, rounds: int, issues: list) -> dict:
    """跑满轮数仍有残留:留痕、不阻断(注意键是 rounds 总轮数,不是 round)。"""
    return {"type": "gate_exhausted", "label": label, "role": role, "rounds": rounds, "issues": issues}


# ── 外置大脑三件套起草(draft.draft_brain) ───────────────────────────────────

@_event
def draft_done(written: list, skipped: list) -> dict:
    """起草收尾:written=写入的名字列表,skipped=你已填真内容而跳过的。"""
    return {"type": "draft_done", "written": written, "skipped": skipped}


# ── 写作指纹(fingerprint.seed_* / learn) ───────────────────────────────────

@_event
def seed_done(path, source: str) -> dict:
    """指纹种子已落盘(source: sample/reference/inherit)。"""
    return {"type": "seed_done", "path": str(path), "source": source}


@_event
def learn_done(path, chapter: int, shrink_warning: str) -> dict:
    """learn 完成(shrink_warning:疑似磨短嗓音的软提示,可为空串/None)。"""
    return {"type": "learn_done", "path": str(path), "chapter": chapter,
            "shrink_warning": shrink_warning}


# ── 写后摘要(recap)/ 外置大脑随章生长(enrich)——learn 的附赠动作 ────────────

@_event
def recap_done(chapter: int, path) -> dict:
    return {"type": "recap_done", "chapter": chapter, "path": str(path)}


@_event
def recap_skip(chapter: int) -> dict:
    return {"type": "recap_skip", "chapter": chapter}


@_event
def enrich_done(chapter: int, 世界观: str, 人物卡: str) -> dict:
    """世界观/人物卡补充已写入(中文键是既有契约,值为本次补充的正文,可为空串)。"""
    return {"type": "enrich_done", "chapter": chapter, "世界观": 世界观, "人物卡": 人物卡}


@_event
def enrich_skip(chapter: int) -> dict:
    return {"type": "enrich_skip", "chapter": chapter}


# ── 通用:提示 / 警告 / 错误 ──────────────────────────────────────────────────

@_event
def info(message: str) -> dict:
    return {"type": "info", "message": message}


@_event
def warn(message: str) -> dict:
    return {"type": "warn", "message": message}


@_event
def error(message: str, code: str | None = None) -> dict:
    """流式管道里的错误兜底(server 的 /api/write worker 用;引擎内错误走异常)。

    code(可选)指向 errors.py 错误目录,前端据此附可操作提示;None 不出键,既有事件字节不变。
    """
    ev = {"type": "error", "message": message}
    if code:
        ev["code"] = code
    return ev
