"""写章通道的工具注册表(与 `partner_tools` 成对:伙伴通道 vs 写章通道)。

设计(docs/superpowers/specs/2026-08-16-loom-continual-harness-design.md §3.2/§4):
- **注册表单一真相**:工具在一处声明,同时渲染 prompt 契约段(`render_contract`)、驱动分发
  (`run_tool`)——prompt 里写着的工具与实际能跑的工具永不漂。这条是 partner_tools 已经
  根治过一次的老毛病,照搬。
- **只读取数 + 提交落产物**:今天 `agents._build_user_prompt` 把设定/硬设定/状态账本/上一章/
  工作区全量拼成一个大字符串;改成按需取之后,每轮 prompt 反而更小。
- **护栏挂在提交上**(`artifacts.ARTIFACTS`),不挂在「棒」上——agent 自己决定先干什么、
  要不要回头重来,但它绕不过提交这道门。
- `run_tool` **绝不抛**:任何失败都返回 error 事件,由调用方回喂给模型自愈(§4 第一行)。

与 `partner_tools` 的一处刻意差异:那边是无状态的(root + 参数即可),这边要带一个 `Session`
——「本章工作区」是一次跑动期间的可变状态,不落盘就没法让下游人格读到上游产物。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import artifacts, events
from .config import Config


def _noop(_event: dict) -> None:
    pass


@dataclass
class Session:
    """一次写章跑动的上下文。工作区是这次跑动累积的已提交产物,与 `agents` 的同名概念一致。

    `backend` 给了才跑质量关卡(复审/回炉要发 LLM);`critic_backend` 给了就让复审走它
    (通常是便宜模型,同 run_pipeline 的路由哲学:评估走便宜的、写作留主模型)。
    """

    root: Path
    chapter_n: int
    config: Config
    workspace: list[tuple[str, str]] = field(default_factory=list)
    persona: str = ""            # 最近取过的人格:进度事件按它点亮对应头像(UI 的五个人还在)
    backend: object | None = None
    critic_backend: object | None = None
    progress: Callable[[dict], None] = _noop
    # 本次跑动是否已经写过审稿留痕。首次写截断、之后追加——于是重跑同一章不会把上一次的
    # 留痕残留在文件里,而「留痕」与「关卡残留」谁先提交都不会互相覆盖(agent 化后顺序不固定)。
    _note_touched: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: tuple[str, ...]
    desc: str
    handler: Callable
    mutates: bool = False
    body_param: str = ""   # 该参数缺省时取「块正文体」(整章散文塞不进一行 键:值,见 parse.parse_tool_blocks)


# 注:这里【没有】partner_tools 那样的单条结果字数上限。那边读的是任意文件、要防手滑读进一本书;
# 这边三个取数各有不可截断的理由——硬设定截断即违 ADR 0010 的「逐字」、工作区截断会丢上游产物、
# 取人格截断会丢设定。体量控制靠 `budget` 的折叠/取代规则(见 _handle_workspace),不靠一刀切截断。


def _handle_hardfacts(sess: Session) -> str:
    """硬设定逐字块。**复用 `agents._hardfacts_for`,不另写一份切片逻辑**——
    「境界/金手指代价/地名势力 + 人物专名册逐字直送、反转段 deny 压过 allow」是 ADR 0010
    的语义,再实现一遍就等于给它开第二个会漂的真相。"""
    from .agents import _hardfacts_for
    return _hardfacts_for(sess.root) or "(这本书的世界观里还没有可逐字直送的硬设定小节)"


def _handle_statebook(sess: Session) -> str:
    """状态账本摘录:物品消耗/规则数值的现状,截至上一章。"""
    from . import statebook
    return statebook.snapshot_for(sess.root, sess.chapter_n - 1) or "(状态账本还是空的)"


def _handle_prev(sess: Session) -> str:
    """上一章【手改后的】正文(不是 .原稿 快照),去标题只给正文体。

    尾部 1500 字即可——要的是接住章末钩子,不是通读全章(同 `_build_user_prompt` 的老口径)。
    """
    from .agents import _prev_chapter
    prev = _prev_chapter(sess.root, sess.chapter_n)
    return prev[-1500:] if prev else "(这是第一章,没有上一章)"


def _handle_workspace(sess: Session) -> str:
    """本章工作区:到目前为止已提交的产物(累积,非纯链式——丢了设定锚点会设定漂移)。

    过一道 `budget.drop_superseded`:全文稿只留最新一份、锚点/细纲逐字全保留。
    agent 化后它能回头重来、工作区可能累积更多轮稿,这道比流水线时代更要紧
    ——不然一次取数就把三份同一章正文塞回 prompt。
    """
    if not sess.workspace:
        return "(工作区还是空的,还没提交过任何产物)"
    from . import budget
    return "\n\n".join(f"### {label}\n{text}"
                       for label, text in budget.drop_superseded(sess.workspace))


def _handle_persona(sess: Session, 角色: str = "") -> str:
    """取一个人格:它的系统提示词 + 它 `reads:` 声明的设定/方法论。

    人格就是今天的 `agents/<角色>.md`——五个角色从「工序」降级为「人格」是内部重构,
    这份文件的形状、用户改它立即生效的语义、以及各自的 reads 边界(写手 voice 侧只读
    写作指纹/网文大神/文风参考)全部原样保留。
    """
    from .agents import _knowledge_prompt
    role = (角色 or "").strip()
    if not role:
        raise ValueError(f"取人格缺少「角色」参数。可选:{'、'.join(a.persona for a in artifacts.ARTIFACTS if a.persona)}")
    # deny_spoiler=True(终审②critical):这次取到的原文会进 writeloop 的 trail、
    # 每一轮都重新拼进 prompt——冰山真相类反转段绝不能经这条路混进写手落字那次调用(ADR 0010)。
    agent, knowledge = _knowledge_prompt(sess.root, sess.chapter_n, role, deny_spoiler=True)
    sess.persona = role   # 进度事件按它归属:UI 的五个头像照旧一个个点亮
    sess.progress(events.agent_start(role))
    parts = [f"【人格·{agent.name}】\n{agent.system_prompt}"]
    if knowledge:
        parts.append(f"【它要遵循的设定/方法论】\n{knowledge}")
    return "\n\n".join(parts)


def artifact_sig(sess: Session, spec) -> str:
    """这件产物的**上游签名**:人格提示词 + 它 reads 的文件 + 已提交产物 + 上一章 + config 三项。

    直接复用流水线那套 `resume.sig_v2`(结构化逐项哈希、注入安全、reads 顺序不敏感)——
    续跑的正确性底线是「上游变了必须重算」,这条不该有两套算法。

    没有人格的附属产物(留痕)返回空串:它不进工作区、也不值得重放。
    注:**必须在 append 进 workspace 之前算**——签的是「产它时的上游」,不含它自己。
    """
    if not spec.persona:
        return ""
    from . import agents, resume
    agent, items = agents._knowledge_items(sess.root, sess.chapter_n, spec.persona)
    prev = agents._prev_chapter(sess.root, sess.chapter_n)
    cfg_bits = {"chapter_chars": sess.config.chapter_chars,
                "gate_rounds": sess.config.gate_rounds, "title": sess.config.title}
    return resume.sig_v2(agent.system_prompt, items, list(sess.workspace), prev, cfg_bits)


def _have(sess: Session, artifact_name: str) -> bool:
    """这件前置产物有没有。工作区里有就算;细纲还认盘上那份——

    作者自己在 `正文/.细纲/` 写好细纲、没让 agent 产,那也是细纲(ADR 0008 的 WYSIWYG),
    不该因为「本次跑动没提交过」就拦着他。
    """
    if any(label == artifact_name for label, _ in sess.workspace):
        return True
    try:
        req = artifacts.spec_for(artifact_name)
    except KeyError:
        return False
    if req.outline_file:
        from . import paths
        p = paths.outline_path(sess.root, sess.chapter_n)
        return p.is_file() and bool(p.read_text(encoding="utf-8").strip())
    return False


def _note_path(sess: Session):
    """审稿留痕文件,并保证本次跑动首次写入时先截断(见 Session._note_touched)。"""
    from . import paths
    p = paths.review_note_path(sess.root, sess.chapter_n)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not sess._note_touched:
        p.write_text("", encoding="utf-8")
        sess._note_touched = True
    return p


def _run_gate(sess: Session, spec, text: str) -> str:
    """跑该产物挂着的质量关卡,返回(可能已回炉的)稿。

    语义与 `run_pipeline` 里那段逐字一致:挑硬伤→回炉、不打分、跑满仍残留【不阻断】,
    残留追加进审稿留痕交作者定夺(ADR-0006)。只是挂点从「棒」换成了「提交」。
    """
    from . import agents, gates
    g = artifacts.GATES[spec.gate]
    knowledge = agents._read_files(sess.root, list(g.reads), lambda _e: None)
    if g.wants_prev:
        prev = agents._prev_chapter(sess.root, sess.chapter_n)
        if prev:
            knowledge += "\n\n【上一章章末(看本章有没有接住它的钩子)】\n" + prev[-800:]
    res = gates.run_gate(
        sess.backend, label=g.label, owner_role=spec.persona or spec.name,
        critic_system=g.critic_system, revise_system=g.revise_system,
        draft=text, knowledge=knowledge, produces=spec.name,
        rounds=sess.config.gate_rounds, max_chars=sess.config.chapter_chars,
        progress=sess.progress, critic_backend=sess.critic_backend,
        detector=agents._deslop_detector(sess.root, sess.chapter_n) if spec.deslop else None,
    )
    if res.remaining:
        _note_path(sess)   # 截断纪律:与留痕提交共用一份「本次跑动首写即清」的语义
        agents._save_gate_remaining(sess.root, sess.chapter_n, g.label,
                                    res.remaining, sess.progress)
    return res.text


def _handle_commit(sess: Session, 产物: str = "", 内容: str = "") -> dict:
    """提交一件产物:校验 → 过关卡 → 落地。

    不合格返回原因(回喂让它重交),绝不抛、绝不半截落盘。**关卡由这里强制触发**——
    agent 不能选择不跑,这是 §4 把护栏从「棒」搬到「提交」的全部意义。
    """
    spec = artifacts.spec_for(产物)
    missing = [r for r in spec.requires if not _have(sess, r)]
    if missing:
        raise ValueError(
            f"得先有「{'」「'.join(missing)}」才能提交「{spec.name}」——"
            "篇幅是靠细纲的场次预算控住的,没有它正文篇幅没有任何结构约束。"
            "先提交细纲(按目标定场次、每场标「约X字」),再回来提交这一件。")
    reasons = artifacts.check_commit(spec, 内容, chapter_target=sess.config.chapter_chars)
    if reasons:
        raise ValueError("；".join(reasons) + " 请照契约重新提交这件产物。")
    text = (内容 or "").strip()
    sig = artifact_sig(sess, spec)   # 必须在进工作区【之前】算:签的是产它时的上游

    if spec.review_note:   # 留痕:盘外文件,不过关卡、不进工作区
        with _note_path(sess).open("a", encoding="utf-8") as f:
            f.write(text + "\n")
        return {"t": "committed", "产物": spec.name}

    if spec.outline_file:
        # ADR 0008 的 WYSIWYG:细纲落盘成可看可改的文件。作者改了它,下次重写本章就按他的来
        # (读侧在 writeloop._assemble)。原子写,与流水线同一个落点。
        from . import paths
        from .fsutil import atomic_write_text
        atomic_write_text(paths.outline_path(sess.root, sess.chapter_n), text + "\n")

    gated = False
    if spec.gate and sess.config.gate_rounds > 0 and sess.backend is not None:
        text = _run_gate(sess, spec, text)
        gated = True
    # 篇幅的确定性校验(§4「篇幅三管齐下」的后两管):细纲查场次预算标注、终稿查超长。
    # 两条都只 warn / 只留痕,绝不阻断出稿(ADR-0006);异常一律吞掉,附赠类检查不拖累提交。
    from . import agents
    if spec.contract_fn is not None:
        agents._check_scene_budget(sess.root, sess.chapter_n, text,
                                   sess.config.chapter_chars, False, sess.progress)
    if spec.is_final:
        _note_path(sess)   # 与留痕/关卡残留共用「本次跑动首写即清」的截断纪律
        agents._flag_overlong(sess.root, sess.chapter_n, text,
                              sess.config.chapter_chars, sess.progress)
    if spec.foreshadow_after:
        agents._flag_stale_foreshadow(sess.root, sess.chapter_n, sess.config, sess.progress)
    if spec.into_workspace:
        sess.workspace.append((spec.name, text))
    if sig:
        # 记【过完关卡之后】的文本:重放时不再重跑质检/去AI味,免得为同一份稿重复付复审的钱
        from . import trail
        trail.record_commit(sess.root, sess.chapter_n, spec.name, text, sig)
    return {"t": "committed", "产物": spec.name, "过关卡": gated}


REGISTRY: dict[str, ToolSpec] = {
    "取人格": ToolSpec(
        name="取人格", params=("角色",),
        desc="拿到某个人格的写法要求 + 它该遵循的设定/方法论(设定师/大纲师/写手/编辑/润色师)。"
             "动手写某件产物前先取对应人格。",
        handler=_handle_persona,
    ),
    "查硬设定": ToolSpec(
        name="查硬设定", params=(),
        desc="境界阶梯/金手指代价/地名势力 + 人物专名册的【原文】。这些必须一字不改地照抄,"
             "不许自己新造等级或改名。写正文前必查。",
        handler=_handle_hardfacts,
    ),
    "查状态账本": ToolSpec(
        name="查状态账本", params=(),
        desc="截至上一章的物品消耗/规则数值现状。不许复活已消耗的物品、不许改规则数值。",
        handler=_handle_statebook,
    ),
    "读上一章": ToolSpec(
        name="读上一章", params=(),
        desc="上一章正文的结尾部分,用来接住它的章末钩子——别重复、别断裂。",
        handler=_handle_prev,
    ),
    "看工作区": ToolSpec(
        name="看工作区", params=(),
        desc="本章到目前为止已提交的全部产物。",
        handler=_handle_workspace,
    ),
    "提交": ToolSpec(
        name="提交", params=("产物", "内容"),
        desc="提交一件产物(见下方产物表)。写法:「用:提交」下一行「产物:<名字>」,空一行后直接写正文。"
             "不合格会被打回并告诉你原因,照原因重交即可。",
        handler=_handle_commit, mutates=True, body_param="内容",
    ),
}


def draft_chars(workspace: list[tuple[str, str]]) -> int:
    """工作区里【最近一份全文稿】的实测字数(去标题去空白,与 evals/_flag_overlong 同口径)。

    压缩授权靠它开关(见 artifacts._revise_contract):LLM 自己数不准字数,得由 Loom 现算。
    """
    from .chaptertext import strip_title
    for label, text in reversed(workspace):
        if any(k in label for k in ("初稿", "改稿", "终稿")):
            return len("".join(strip_title(text).split()))
    return 0


def render_contract(chapter_target: int = 0, actual_chars: int = 0) -> str:
    """渲染进 prompt 的工具契约段 + 产物表。注册表与产物表是唯一真相,不手写第二份协议文案。

    `actual_chars` 让产物表里的篇幅契约随「当前上游稿多长」变——压缩授权只在真超标时给出
    (真机教训:无条件给,合格稿会被连压两道到 −25%)。
    """
    # 【真机教训 2026-08-16】清单行里【绝不能】出现「用:xxx | 参数:yyy」这种形状:
    # 模型会照抄这个**展示格式**发出 `用:取人格 | 参数:编辑`,解析器认不出工具名 → 0 工具 →
    # 空转到撞轮数上界、整章报废。展示行长得像协议行,模型就仿写它。
    # 所以清单只写名字,调用格式交给下面这段【可以直接照抄的范例】去教。
    lines = [
        "调用格式(严格照抄这个形状:第一行「用:工具名」,之后每行一个「键:值」):",
        "",
        "用:取人格",
        "角色:写手",
        "",
        "提交正文类产物时,参数行之后空一行,再直接写正文:",
        "",
        "用:提交",
        "产物:本章初稿",
        "",
        "(这里直接写正文,可以很多段)",
        "",
        "可用工具:",
    ]
    for spec in REGISTRY.values():
        params_txt = "、".join(spec.params) if spec.params else "(无参数)"
        lines.append(f"- {spec.name} 〔参数:{params_txt}〕{spec.desc}")
    lines.append("")
    lines.append("产物表(「提交」的「产物」参数只能填下面这些名字,一字不差):")
    for a in artifacts.ARTIFACTS:
        who = f"({a.persona})" if a.persona else "(附属)"
        contract = artifacts.commit_contract(a, chapter_target, actual_chars)
        lines.append(f"- {a.name} {who}" + (f" | {contract}" if contract else ""))
    return "\n".join(lines)


def run_tool(sess: Session, name: str, params: dict | None) -> dict:
    """执行一次工具调用 → 结果事件 dict。**绝不抛**:失败一律回 error 事件供回喂自愈。"""
    params = dict(params or {})
    spec = REGISTRY.get(name)
    if spec is None:
        return {"t": "result", "error": f"未知工具:{name}。可用:{'、'.join(REGISTRY)}"}
    try:
        result = spec.handler(sess, **params)
    except TypeError as e:
        return {"t": "result", "error": f"参数不对(「{name}」需要 {spec.params}):{e}"}
    except (KeyError, ValueError, FileNotFoundError, OSError) as e:
        return {"t": "result", "error": str(e)}
    return result if isinstance(result, dict) else {"t": "result", "text": result}
