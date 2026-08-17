"""写作 agent 循环:一个 agent、五个人格、循环到终稿提交。

spec 2026-08-16 §3.2。**形状照搬 `partner.run_turn`**(已在 claude/codex/DeepSeek 三类后端
上跑通,不是新路子):每轮 = 一次 `complete()`;模型按文本协议输出「用:」块;Loom 侧执行工具、
回喂结果、再 complete。真实读写永远在 Loom 服务端(见 `write_tools.run_tool`),模型自己
没有 shell/文件能力,`agent_mode=True` 只是解掉 CLI 后端 prompt 层面的反 agent 护栏。

与流水线时代的两处根本差异:
- **没有固定拓扑**。五个角色降级成人格,agent 自己决定先干什么、要不要回头重来
  ——「可回头」是付这次重构代价的理由:今天写手写崩了只能整章重跑。
- **护栏挂在产物提交上**(`artifacts.ARTIFACTS`),不挂在棒上。agent 绕不过提交这道门。

两条纪律原样继承伙伴通道:
- **流式行缓冲**(spec 2026-07-16 §5.2 critical):协议行绝不许漏到作者屏幕
  (`parse.stream_line_relay`,与伙伴通道共用同一份判据)。
- **每轮重建、零挂起**:本模块不留任何跨调用的进程内状态,轨迹在 `Session` 里,
  杀进程最多丢正在写的一轮。
"""

from __future__ import annotations

from . import artifacts, events, write_tools
from .backends import LoomBackendError
from .errors import render
from .parse import parse_tool_blocks, stream_line_relay, strip_protocol_lines

# 一章的调用上界(spec §9 第一风险:自主循环的成本必须定死)。
# 定 24 的依据:五件产物 + 每件前面一次取数 ≈ 10 轮是顺跑的量,留一倍余量给「回头重来」
# (改一次细纲重写一次正文 ≈ +6 轮),再留几轮给提交被打回的自愈。撞到就是真跑飞了。
MAX_ROUNDS = 24

_SYSTEM = """你在为一本网文写一章。你不是助手、不是聊天机器人——你的每一次输出都直接进入生产流程。

你有五个可以戴的人格(设定师/大纲师/写手/编辑/润色师)。动手写某件产物之前,先「取人格」拿到
它的写法要求和它该遵循的设定。你可以按自己的判断决定顺序,**也可以回头重来**——比如写完初稿
发现细纲不好,就重新提交一份细纲再重写。

硬规矩:
1. 只能通过下面的工具做事。想要什么材料就去取,别猜、别编。
2. 写正文前必须「查硬设定」,境界名/专名/金手指代价一字不改照抄,不许自己新造体系。
3. 每件产物都要「提交」。提交会被校验,不合格会被打回并告诉你原因——照原因改好重交即可。
4. 提交「本章终稿」就是收工信号,交完不要再做别的。
5. 除了工具块和一句简短说明,不要输出任何旁白、解释、或「我接下来要…」这类话。
"""


# 回喂窗口(字符)。按【总量】裁,不按条数裁,更不截单条——
# 真机实测 2026-08-16:把单条工具结果截到 400 字,agent 连取了 4 次「设定师」人格,
# 因为它压根没看见人格内容。取数结果被截断 = 这个工具等于不存在。
_TRAIL_BUDGET = 16000


def _trim_trail(trail: list[str]) -> list[str]:
    """从尾往前收,收到预算为止。**单条永不截断**:宁可少给几条,也不给半条。"""
    kept: list[str] = []
    total = 0
    for line in reversed(trail):
        if kept and total + len(line) > _TRAIL_BUDGET:
            break
        kept.append(line)
        total += len(line)
    return list(reversed(kept))


def _existing_outline(sess: write_tools.Session) -> str:
    """作者手上那份细纲(`正文/.细纲/第N章.md`)。没有/读不了就当没有——绝不因此拖累出稿。"""
    from . import paths
    try:
        p = paths.outline_path(sess.root, sess.chapter_n)
        return p.read_text(encoding="utf-8").strip() if p.is_file() else ""
    except (OSError, UnicodeDecodeError):
        # UnicodeDecodeError 继承自 ValueError 而非 OSError,裸 `except OSError` 抓不到,
        # 编码损坏的细纲(如作者用 GBK 存过)会直接抛穿、agent 化每一轮 _assemble 都踩到,
        # 整章跑不了(同 mirror.py 已踩过的坑,这里显式并列,不用裸 except Exception)。
        return ""


def _assemble(sess: write_tools.Session, trail: list[str]) -> tuple[str, str]:
    """拼这一轮的 (system, user)。

    与今天 `_build_user_prompt` 的根本差异:设定/硬设定/上一章/工作区**不再全量拼进来**,
    改由 agent 按需取——于是每轮 prompt 比流水线时代更小,不是更大。
    """
    # 上游稿实测字数随轮次变 → 篇幅契约也随之变(压缩授权只在真超标时才给)
    actual = write_tools.draft_chars(sess.workspace)
    system = _SYSTEM + "\n" + write_tools.render_contract(sess.config.chapter_chars, actual)
    head = (f"# 你要写的是《{sess.config.title}》第 {sess.chapter_n} 章。"
            if (sess.config.title or "").strip()
            else f"# 你要写的是第 {sess.chapter_n} 章。")
    parts = [head, f"本章正文目标约 {sess.config.chapter_chars} 字。"]
    done = [label for label, _ in sess.workspace]
    parts.append("已提交的产物:" + ("、".join(done) if done else "(还没有)"))
    existing = _existing_outline(sess)
    if existing and not any("细纲" in label for label in done):
        # ADR 0008 的 WYSIWYG 读侧:细纲文件已在(多半是作者手改过)→ 按他的来,别自顾自重拆。
        parts.append("## 作者已经给了本章细纲(照它写,不要重拆)\n" + existing)
    if trail:
        parts.append("## 刚才发生了什么\n" + "\n".join(_trim_trail(trail)))
    parts.append("## 现在\n继续推进,直到提交「本章终稿」。")
    return system, "\n\n".join(parts)


def _tool_params(tool: dict) -> dict:
    """工具参数:声明了 body_param 的工具(提交),「内容」缺省时取块正文体。

    整章正文是多行散文,塞不进一行 `键:值`——故走 `parse_tool_blocks` 给的 body。
    两者都给时以显式参数优先(短产物模型爱写成一行,别让 body 顶掉它)。
    """
    spec = write_tools.REGISTRY.get(tool["name"])
    params = dict(tool.get("params") or {})
    bp = getattr(spec, "body_param", "") if spec else ""
    if bp and not params.get(bp) and tool.get("body"):
        params[bp] = tool["body"]
    return params


def _replay(sess: write_tools.Session) -> str | None:
    """产物级续跑:按提交序重放【已提交且上游未变】的产物,撞到第一个签名失配即停。

    流水线那套是「每棒 sha + 上游签名」;agent 化后没有棒,但提交序是有的,于是判据平移成
    「重放轨迹的合法前缀」。上游变了(改了人格提示词/设定/上一章/章字数)必须重算——
    这是续跑的正确性底线,不然作者的改动被静默吃掉。

    返回终稿文本 = 整章都重放完了、连收工产物都在(此时一次调用都不必发);否则 None。
    """
    from . import trail as trail_store
    for c in trail_store.read_commits(sess.root, sess.chapter_n):
        try:
            spec = artifacts.spec_for(c.get("产物", ""))
        except KeyError:
            break                     # 轨迹里有本版本不认识的产物名 → 保守起见就此打住
        if not c.get("sig") or c["sig"] != write_tools.artifact_sig(sess, spec):
            break                     # 上游变了 → 从这件产物起重算
        if spec.into_workspace:
            sess.workspace.append((spec.name, c.get("text", "")))
        sess.progress(events.agent_skip(spec.persona or spec.name, "已提交且上游未变"))
        if spec.is_final:
            return c.get("text", "")
    return None


def run_chapter(sess: write_tools.Session, *, max_rounds: int = MAX_ROUNDS,
                should_cancel=None) -> str:
    """跑一章,返回终稿文本。撞轮数上界仍没有终稿 → 报错(绝不静默交一章空的)。

    `should_cancel`(可选):无参可调,返回 True 则在**轮边界**提前抛停止——同伙伴通道的
    「停」落点,正跑的 `complete()` 不在此处中断(不碰 Backend Protocol)。
    """
    from .backends import accepts_kwarg
    final = _replay(sess)
    if final is not None:
        return final          # 上游一点没变 → 整章重放完毕,一次调用都不发
    trail: list[str] = []
    kwargs: dict = {}
    if accepts_kwarg(sess.backend, "agent_mode"):
        # 解掉 CLI 后端(claude/codex)prompt 层面的反 agent 护栏:允许输出工具块。
        # 真实文件读写始终锁在 loom 服务端,这里传的只是护栏开关。
        kwargs["agent_mode"] = True

    for _round in range(max_rounds):
        if should_cancel is not None and should_cancel():
            raise LoomBackendError("这一章已停下(作者取消)。", code="cancelled")
        system, user = _assemble(sess, trail)
        persona = sess.persona or "写手"
        on_chunk, flush = stream_line_relay(
            lambda line, r=persona: sess.progress(events.agent_chunk(r, line + "\n")))
        raw = sess.backend.complete(system, user, max_chars=sess.config.chapter_chars,
                                    on_chunk=on_chunk, **kwargs)
        flush()

        # known_params(终审①critical):白名单外的键立刻停手转 body,防中文对白行(合法的
        # 「键:值」形状,如「林三：「你来晚了。」」)被 params 扫描误吞、吃掉正文首行。
        say, tools = parse_tool_blocks(raw, valid_names=set(write_tools.REGISTRY),
                                       known_params={n: s.params for n, s in write_tools.REGISTRY.items()})
        # critical:say 里可能混入没被选中的「用:」协议行(工具名瞎编、或误触发块排在真工具前)
        # ——绝不许漏到作者屏幕。
        say, botched = strip_protocol_lines(say)

        if not tools:
            # 光说话不动手:回喂一句推一下。botched(想调工具但名字没认出来)也走这条。
            trail.append(f"你说:{say[:200]}" if say else "你什么也没做。")
            # 光说「格式不对」不够——真机证明模型会去抄它看得见的形状,所以每次都把形状原样摆出来。
            trail.append(
                "系统:这一轮没有解析出可执行的工具块。工具调用必须是【独立成行】的两行,"
                "参数不能写在同一行里。照这个形状来:\n"
                "用:取人格\n角色:写手\n"
                f"可用工具:{'、'.join(write_tools.REGISTRY)}")
            continue

        if say:
            trail.append(f"你说:{say[:200]}")
        for tool in tools:
            ev = write_tools.run_tool(sess, tool["name"], _tool_params(tool))
            if ev.get("error"):
                trail.append(f"系统:「{tool['name']}」没成——{ev['error']}")
                continue
            if ev.get("t") == "committed":
                name = ev["产物"]
                sess.progress(events.agent_done(sess.persona or name, name))
                trail.append(f"系统:「{name}」已提交。")
                if artifacts.spec_for(name).is_final:
                    return sess.workspace[-1][1]
            else:
                # 完整回喂,不截断(见 _TRAIL_BUDGET 的真机教训);总量控制交给 _trim_trail。
                trail.append(f"系统:「{tool['name']}」返回:\n{ev.get('text', '')}")

    raise LoomBackendError(
        render("model_output_invalid",
               detail=f"跑满 {max_rounds} 轮仍没有提交「本章终稿」(已提交:"
                      f"{'、'.join(l for l, _ in sess.workspace) or '无'})"),
        code="model_output_invalid")
