"""对话循环:一轮 = 追加 user 事件 → assemble → complete(流式行缓冲) → 解析说话+工具 →
有工具则执行+回喂再 complete(≤6 次) → 无工具则终结(spec §3)。

**每轮重建,两轮之间零挂起**(ADR 0013「答案单点注入」的形状平移):本模块不留任何
进程内状态——`run_turn` 一次调用做完一整轮就返回,下一轮从 `.伙伴对话/当前.jsonl`
尾部 + 书文件现状重建一切。崩溃语义平庸化:任何时刻杀进程,最多丢正在写的一行。

**流式行缓冲纪律**(spec §5.2,critical:协议行绝不许漏到作者屏幕上):`backend.complete()`
的 `on_chunk` 增量按行缓冲——整行落定且(剥装饰后)以「用:」开头才停止对外转发;
在此之前的所有整行**照发**给 `emit()`(预览态,不落盘;真正落盘的说话段来自
`complete()` 返回的完整文本经 `parse.parse_tool_block` 解析出的结果,两者内容一致,
预览只是让调用方(P3 的 ndjson)能在生成过程中就把安全的文字转发出去)。chunk 可能
在行内截断(如「用」与「:」分两个 chunk 到达)——只在遇到换行符时才判行,天然免疫;
流结束时缓冲区残留的未终结行,非触发行则随最后一批照发(`_stream_line_relay` 的
`flush`)。

**ts 由调用方给**(无 Date.now 依赖):同一 `ts` 贯穿一整轮的所有事件;工具执行的
`ts` 按轮内序号派生(`f"{ts}-{轮次}"`),满足 `partner_tools.run_tool` 文档要求的
「同一轮内多次 mutates 调用的 ts 唯一性由调用方保证」,不引入挂钟。
"""
from __future__ import annotations

from pathlib import Path

from . import journey, partner_context, partner_store, partner_tools
from .parse import _TOOL_USE_RE, parse_tool_block

_MAX_TOOL_ROUNDS = 6   # 每轮工具调用上限(spec §4 常量表:每轮工具调用 ≤6 次)
_MAX_TOOL_FAIL_STREAK = 2   # 连续「解析失败」(botched 工具调用)上限(spec §5.2)


def _is_trigger_line(line: str) -> bool:
    """一行(剥装饰后)是否以「用:」开头——流式转发的停发判据。

    刻意比 `parse_tool_block` 的 `valid_names` 校验更粗(只认前缀,不校验工具名是否在
    注册表内):streaming 预览宁可少发也不可漏发协议行,即便某行最终被 `parse_tool_block`
    判定不是真正的工具触发(名字不在注册表、当普通说话处理),那部分文字也早已经由
    `complete()` 返回的完整文本走最终解析、正确地进了持久化的 assistant 事件——预览层
    漏发一行不影响正确性,只是这一行没能提前显现。
    """
    return _TOOL_USE_RE.match(line) is not None


def _strip_protocol_lines(text: str) -> tuple[str, bool]:
    """剥掉 `say` 里混入的协议形状整行(剥装饰后以「用:」开头,但没被 `parse_tool_block`
    选中——工具名瞎编/误触发块排在真工具前时会有这种残留)。

    `parse_tool_block` 拿 `valid_names` 校验后,「说话段」只保证不含**被选中**的那个工具块,
    不保证不含其它未被选中的 `用:` 行(它们仍在 say 里原样躺着)。这些行是协议行的形状,
    绝不许漏到作者屏幕(spec §5.2 critical)——不管它是不是真工具触发。

    返回 `(过滤后文本, 是否剥掉过至少一行)`:后者是「模型想调工具但名字没认出来」的判据,
    供调用方决定要不要走「解析失败回喂」(spec §5.2)。
    """
    kept: list[str] = []
    dropped = False
    for line in text.splitlines():
        if _TOOL_USE_RE.match(line):
            dropped = True
            continue
        kept.append(line)
    return "\n".join(kept).strip(), dropped


def _stream_line_relay(sink):
    """返回 `(on_chunk, flush)`。`sink(line)` 在整行落定且非触发行时被调用一次(该行
    文本,不含换行符)。一旦遇到触发行,后续所有增量与残留行一律不再转发——工具块交给
    `complete()` 返回的完整文本统一解析,不依赖这里的增量重建。

    chunk 可能在行内截断(如「用」与「:」分两个 chunk 到达):这里只在遇到 `\\n` 时才
    判定一整行,天然免疫——`buf` 持续累积,不管上一个 chunk 在哪个字符断开。
    """
    state = {"buf": "", "triggered": False}

    def on_chunk(delta: str) -> None:
        if state["triggered"] or not delta:
            return
        state["buf"] += delta
        while "\n" in state["buf"]:
            line, state["buf"] = state["buf"].split("\n", 1)
            if _is_trigger_line(line):
                state["triggered"] = True
                return
            sink(line)

    def flush() -> None:
        """流结束收尾:缓冲区残留的未终结行(没有尾随换行符的最后一行),非触发行则冲出。"""
        if state["triggered"]:
            return
        rest, state["buf"] = state["buf"], ""
        if rest.strip() and not _is_trigger_line(rest):
            sink(rest)

    return on_chunk, flush


def run_turn(root, user_text, backend, *, emit, ts) -> None:
    """一轮:追加 user 事件 → assemble → complete(流式行缓冲) → 解析说话+工具 →
    有工具则执行+回喂再 complete(≤6 次) → 无工具则终结。emit(event) 转发给调用方(P3 的 ndjson)。
    两轮之间零挂起。ts 由调用方给(无 Date.now)。"""
    root = Path(root)

    def _persist(event: dict) -> None:
        event.setdefault("ts", ts)
        partner_store.append_event(root, event)
        emit(event)

    def _preview(text: str) -> None:
        # 实时增量预览(P3 渐进渲染用),不落盘、不是权威说话段——权威的那条来自下面
        # `_persist({"t": "assistant", ...})`,每条回复恰好一条,两者事件类型分开、不重复。
        if text.strip():
            emit({"t": "assistant_delta", "ts": ts, "text": text})

    _persist({"t": "user", "text": user_text})

    tool_rounds = 0
    tool_fail_count = 0   # 连续「解析失败」(botched 工具调用)计数;成卡/成工具即清零
    while True:
        tail = partner_store.read_events(root)
        system, user = partner_context.assemble(root, tail)
        on_chunk, flush = _stream_line_relay(_preview)
        raw = backend.complete(system, user, on_chunk=on_chunk)
        flush()

        say, tool = parse_tool_block(raw, valid_names=set(partner_tools.REGISTRY))
        # critical(spec §5.2):say 里可能混入未被选中的「用:」协议行(工具名瞎编、或
        # 误触发块排在真工具前)——落盘/emit 前必须过滤掉,绝不许漏到作者屏幕。
        say, botched = _strip_protocol_lines(say)
        if say:
            _persist({"t": "assistant", "text": say})

        if tool is not None:
            tool_fail_count = 0
            tool_rounds += 1
            _persist({"t": "tool", "name": tool["name"], "params": tool["params"]})
            result_ev = partner_tools.run_tool(root, tool["name"], tool["params"],
                                                ts=f"{ts}-{tool_rounds}")
            _persist(result_ev)
            if tool_rounds >= _MAX_TOOL_ROUNDS:
                return
            continue

        if say:
            return   # 有实质说话内容,正常终结(模型说完话、没有下一步动作)

        if not botched:
            return   # 真无话可说也没有协议行残留,平常终结

        # 解析失败回喂(spec §5.2):模型想调工具但名字没认出来,say 被剥空——不当静默
        # 死轮:回喂纠正让模型自我纠正,计入轮内次数;连续 2 次 → 终结本轮并留痕。
        tool_fail_count += 1
        tool_rounds += 1
        if tool_fail_count >= _MAX_TOOL_FAIL_STREAK:
            journey._nav_trace(root, stage="", sig="", why="tool_unparsed", backend=backend, raw=raw)
            return
        if tool_rounds >= _MAX_TOOL_ROUNDS:
            return
        names = "、".join(partner_tools.REGISTRY)
        _persist({"t": "result", "error": f"工具名没认出来。可用工具:{names}"})
