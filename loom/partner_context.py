"""上下文组装:每轮 `assemble(root, 对话尾部) -> (system, user)`。

设计(docs/superpowers/specs/2026-07-16-navigator-agent-design.md §4):
- system(稳定前缀,吃 DeepSeek 前缀缓存)= ①人设(journey._navigator_system,书内
  agents/领航员.md 优先、包内模板兜底)+ ②工具契约(partner_tools.render_contract(),
  注册表单一真相,prompt 与执行永不漂移)+ ③skills 索引(skills/ 下各 .md 的标题,
  不给正文——正文靠「读文件」工具按需拉,拉取优于塞入)。
  「文件不变则字节不变」是**弱保证**,不是冻结:作者中途改 领航员.md 或增删 skills/
  应当**立即生效**(与 journey._sig「文件一动签名即失配」同一条纪律)——见 T4 测试
  test_prefix_changes_when_persona_edited。
- user(动态后缀,每轮现算,绝不存)= ④环境快照(env_snapshot:书名/一句话设定/
  门禁完成度/未填槽位摘要/章节数,≤400 字)+ ⑤对话尾部(jsonl 事件渲成可读文本,
  超预算掐头保留最近)+ ⑥工具结果(与⑤同一份 tail 里的 result 事件一起渲染;单条
  已在 partner_tools._handle_read 侧封顶 3k 字,这里不重复截断)。
- 纯派生零存储:system/user 任何时刻都能从「书文件现状 + jsonl 尾部」重建;
  正文/外置大脑明细绝不进 system(否则前缀随写作节奏抖动,缓存全废)。
"""
from __future__ import annotations

from pathlib import Path

from . import journey, partner_tools, paths, slots
from .config import load_config

_SNAPSHOT_MAX = 400   # 环境快照预算(字);spec §4 常量表
_SNAPSHOT_TOP_K = 3   # 每段展示的未填槽位数量上限(快照只给「前 K 个」,细看用「看地基」工具)
_IDEA_MAX = 80        # 一句话设定的独立小配额(字);超了截断补「…」,绝不挤占门禁/未填槽位预算
_TAIL_MAX = 12000     # 对话尾部预算(字);spec §4 常量表


def _skills_index(root: Path) -> str:
    """skills/ 下各 .md 的标题(首行 H1),不给正文——正文靠「读文件」工具按需拉。

    非递归(glob("*.md")):题材速查库在 skills/题材/ 子目录,init 只按选中题材单拷一份,
    不是「每轮都该现列」的方法论 skill,不进索引。
    """
    d = root / "skills"
    files = sorted(d.glob("*.md")) if d.is_dir() else []
    if not files:
        return "可用 skills:(暂无)"
    lines = ["可用 skills(标题;正文用「读文件」工具按需读取,如 skills/<标题文件名>.md):"]
    for p in files:
        first_line = next((l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()), "")
        title = first_line.lstrip("#").strip() or p.stem
        lines.append(f"- {title}(skills/{p.name})")
    return "\n".join(lines)


def _system_prefix(root: Path) -> str:
    parts = [journey._navigator_system(root), partner_tools.render_contract(), _skills_index(root)]
    return "\n\n".join(p for p in parts if p.strip())


def env_snapshot(root: Path) -> str:
    """≤400 字只读投影:门禁完成度/未填槽位摘要/章节数/书名/一句话设定。

    与「看地基」工具共用 slots.stage_slots(单一真相,绝不建第二个扫描器)——区别在于
    快照只列每段「未填N/总数」+ 前 K 个未填槽位 id(容器#键),不带 filled/preview;
    伙伴靠快照就能「直奔空格发问」,细看某格上下文靠「看地基」/「读文件」工具。

    唯一例外:**当前工作段**(=按 STAGES 顺序第一个还有未填槽的段)的未填槽位带 hint
    (`id(hint)`),让模型当下就知道这格填什么(如「分区」不是「平台」)——其余段仍是光秃
    id。400 字预算带不起「每段都带 hint」,只给当前决策相关的那段够用、也够省。

    预算分配:门禁完成度+未填槽位摘要+章节数是快照核心目的,**先拼、优先保留**;
    书名/一句话设定(idea 来自 loom.toml,作者可以写任意长)放最后、且 idea 单独
    截到 _IDEA_MAX——避免一句长「设定」把门禁信息挤出 400 字预算之外。
    """
    cfg = load_config(root)

    lines = []
    unlocked, missing = journey.writing_unlocked(root)
    gate = "已解锁" if unlocked else f"未解锁(缺{'/'.join(missing)})"
    lines.append(f"起书门禁:{gate}")

    current_stage_marked = False   # 只有第一个「有未填槽」的段算当前工作段,才带 hint
    for spec in journey.STAGES:
        stage_slot_list = slots.stage_slots(root, spec)
        if not stage_slot_list:
            continue
        unfilled = [s for s in stage_slot_list if not s.filled]
        line = f"{spec.key} 未填{len(unfilled)}/{len(stage_slot_list)}"
        is_current = bool(unfilled) and not current_stage_marked
        if unfilled:
            current_stage_marked = True
        if is_current:
            top = "、".join(f"{s.id}({s.hint})" if s.hint else s.id for s in unfilled[:_SNAPSHOT_TOP_K])
        else:
            top = "、".join(s.id for s in unfilled[:_SNAPSHOT_TOP_K])
        if top:
            line += f":{top}"
        lines.append(line)

    lines.append(f"章节数:{len(paths.chapter_numbers(root))}")

    idea = cfg.idea.strip()
    if len(idea) > _IDEA_MAX:
        idea = idea[:_IDEA_MAX] + "…"
    lines.append(f"书名:{cfg.title}" + (f" | 设定:{idea}" if idea else ""))

    return "\n".join(lines)[:_SNAPSHOT_MAX]   # 硬约束兜底;书名/设定殿后,兜底优先砍掉它们而非门禁信息


def _render_event(ev: dict) -> str:
    """一条 jsonl 事件 → 一行可读文本;meta 等非对话内容返回空串(协议裁剪,不进 prompt)。"""
    t = ev.get("t", "")
    if t == "user":
        return f"作者:{ev.get('text', '')}"
    if t == "assistant":
        return f"你:{ev.get('text', '')}"
    if t == "tool":
        params = ev.get("params") or {}
        args = "、".join(f"{k}:{v}" for k, v in params.items())
        return f"[调用工具]{ev.get('name', '')}" + (f"({args})" if args else "")
    if t == "result":
        return f"[工具结果]{ev.get('text') or ev.get('error', '')}"
    if t == "proposal":
        return f"[候选卡 {ev.get('id', '')}]{ev.get('slot', '')} → {ev.get('content', '')}"
    if t == "confirm":
        return f"[已拍板]{ev.get('id', '')}"
    if t == "summary":
        return f"[更早对话摘要]{ev.get('text', '')}"
    return ""


def _render_tail(tail: list[dict]) -> str:
    """对话尾部渲染成文本;超预算掐头保留最近部分(更早的进 UI 不进 prompt,spec §4⑤)。"""
    text = "\n".join(l for l in (_render_event(ev) for ev in tail) if l)
    if len(text) > _TAIL_MAX:
        text = "……(更早的对话未载入)\n" + text[-_TAIL_MAX:]
    return text


def assemble(root: Path, tail: list[dict]) -> tuple[str, str]:
    """(system, user)。system=稳定前缀(人设+工具契约+skills索引);
    user=动态后缀(环境快照+对话尾部+工具结果)。纯派生零存储。"""
    system = _system_prefix(root)
    tail_text = _render_tail(tail)
    user = env_snapshot(root) + (f"\n\n{tail_text}" if tail_text else "")
    return system, user
