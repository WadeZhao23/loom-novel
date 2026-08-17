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

from . import backends as _backends
from . import journey, parse as parse_mod, partner_context, partner_store, partner_tools
from .parse import _TOOL_KV_RE, _TOOL_USE_RE, parse_tool_blocks  # noqa: F401  引用面保留

_MAX_TOOL_ROUNDS = 6   # 每轮工具调用上限(spec §4 常量表:每轮工具调用 ≤6 次)
_MAX_TOOL_FAIL_STREAK = 2   # 连续「解析失败」(botched 工具调用)上限(spec §5.2)
_MAX_TOOLS_PER_MSG = 3   # FB-B:一条消息里最多执行几个「用:」块(多候选护栏,防刷屏)


# 后端能力探测搬进 backends.py(两条 agent 通道共用);这里保薄别名保引用面。
_accepts_kwarg = _backends.accepts_kwarg


# 流式协议行纪律(spec §5.2 critical)搬进 parse.py:写章通道(writeloop)与伙伴通道
# 共用同一份判据——「协议行绝不许漏到作者屏幕」这条只能有一个实现,不许各写一份会漂的。
# 这里保薄别名保引用面(同 S7 的老做法)。
_is_trigger_line = parse_mod.is_trigger_line
_strip_protocol_lines = parse_mod.strip_protocol_lines
_stream_line_relay = parse_mod.stream_line_relay


def run_turn(root, user_text, backend, *, emit, ts, should_cancel=None) -> None:
    """一轮:追加 user 事件 → assemble → complete(流式行缓冲) → 解析说话+工具 →
    有工具则执行+回喂再 complete(≤6 次) → 无工具则终结。emit(event) 转发给调用方(P3 的 ndjson)。
    两轮之间零挂起。ts 由调用方给(无 Date.now)。

    should_cancel(可选,spec §10.3):无参可调,返回 True 则在**轮边界**(while 顶)提前
    return——「停」的落点。正跑的 `backend.complete()` 不在此处中断(不碰 Protocol);取消
    在下一次 complete 前生效。**只在本地判定,绝不传给 `backend.complete()`**(测试替身/CLI
    后端签名里没这参数,传了会 TypeError)。默认 None → 行为与加此参数前逐字一致。"""
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

    user_text = (user_text or "").strip()
    if not user_text:
        # spec §2 开场幂等(第二道保险,前端 _partnerAutoOpened 是第一道):空 text 绝不
        # 落一条永久空 user 事件——真开场(jsonl 尚无事件)仍要往下跑,让伙伴开场发言。
        # bug4下一步:落盘后(末事件=confirm)的空 text 是「自动引下一格」,放行让领航员接着
        # 按固定顺序引导(不落假 user 气泡);其余「已有事件」的空 text 才是重复触发 → no-op。
        events = partner_store.read_events(root)
        last = events[-1] if events else None
        if events and not (last and last.get("t") == "confirm"):
            return
    else:
        _persist({"t": "user", "text": user_text})

    tool_rounds = 0
    tool_fail_count = 0   # 连续「解析失败」(botched 工具调用)计数;成卡/成工具即清零
    complete_kwargs: dict = {}
    if _accepts_kwarg(backend, "agent_mode"):
        # 伙伴通道:解除 CLI 后端的反 agent 护栏——允许输出一个「用:」工具块 + 反问
        # (spec §3)。真实工具执行始终留在 loom 服务端(见 partner_tools.run_tool),
        # 这里传的只是 prompt 层面的护栏开关。
        complete_kwargs["agent_mode"] = True

    def _on_reasoning(text: str) -> None:
        # v2 思考层:思考型后端(DeepSeek)的思维链 → transient reasoning_delta(emit 不 _persist,
        # 与 assistant_delta 同性质:纯 UI 灰字,不落盘、不进 assemble 回喂,免撑大归档/污染上下文)。
        if text.strip():
            emit({"t": "reasoning_delta", "ts": ts, "text": text})
    if _accepts_kwarg(backend, "on_reasoning"):
        complete_kwargs["on_reasoning"] = _on_reasoning
    while True:
        if should_cancel is not None and should_cancel():
            return   # 轮边界取消(spec §10.3):user 事件已落,正跑的 complete 不在此处
        tail = partner_store.read_events(root)
        system, user = partner_context.assemble(root, tail)
        on_chunk, flush = _stream_line_relay(_preview)
        raw = backend.complete(system, user, on_chunk=on_chunk, **complete_kwargs)
        flush()

        # known_params(终审①critical,与写章通道 writeloop 同一份纪律):白名单外的键立刻停手
        # 转 body,防中文对白行(合法的「键:值」形状)被 params 扫描误吞。
        say, tools = parse_tool_blocks(raw, valid_names=set(partner_tools.REGISTRY),
                                       known_params={n: s.params for n, s in partner_tools.REGISTRY.items()})
        # critical(spec §5.2):say 里可能混入未被选中的「用:」协议行(工具名瞎编、或
        # 误触发块排在真工具前)——落盘/emit 前必须过滤掉,绝不许漏到作者屏幕。
        say, botched = _strip_protocol_lines(say)
        if say:
            _persist({"t": "assistant", "text": say})

        if tools:
            # FB-B 多候选:一条消息可连发多个「用:提设定」,逐个执行、各 emit 一张卡(引子 say
            # 已在上面先落,故顺序=话在前、卡在后)。超 _MAX_TOOLS_PER_MSG 截断防刷屏;
            # 每个工具计入 tool_rounds,撞 _MAX_TOOL_ROUNDS 立即收尾(总量上界不变)。
            tool_fail_count = 0
            emitted_proposal = False
            for tool in tools[:_MAX_TOOLS_PER_MSG]:
                tool_rounds += 1
                _persist({"t": "tool", "name": tool["name"], "params": tool["params"]})
                result_ev = partner_tools.run_tool(root, tool["name"], tool["params"],
                                                    ts=f"{ts}-{tool_rounds}")
                _persist(result_ev)
                if result_ev.get("t") == "proposal":
                    emitted_proposal = True
                if tool_rounds >= _MAX_TOOL_ROUNDS:
                    return
            if emitted_proposal:
                # 提了候选卡=交给作者拍板,本轮到此终结,不再 re-complete。真机实测:若继续
                # 重新 complete,模型会「二次质疑自己的格式、重提同样的卡」→ 重复候选卡(3→6)。
                # 读类工具(看地基/读文件)出的是 result 不是 proposal,不触发终结,仍 continue
                # 让模型据结果继续(如看完地基再提设定)。
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
