"""书房伙伴工具注册表 + v1a 三工具(spec §5.3):读文件/看地基/提设定。

设计(docs/superpowers/specs/2026-07-16-navigator-agent-design.md §5):
- **注册表单一真相**:工具在一处声明,同时渲染 prompt 契约段(render_contract)、
  驱动分发(run_tool)——prompt 与执行永不漂移(STAGES 表模式的延伸)。
- **路径守卫两层**:机制守卫(safe_join 锁书根 + 「路径任一段以『.』开头即拒」的通用规则,
  一条规则涵盖 .env/.loom_state.json/.伙伴对话//外置大脑/.拆书/ 等全部内部区)
  + 白名单谓词(外置大脑/skills/正文,只读;前缀从 paths.py 常量派生,不手拼字面量)。
  注意:brainedit.check_rel 是 AI 改写白名单(只放行世界观/人物,窄),职责不同,不复用不改动。
- **提设定不落盘**:mutates=True,产 proposal 事件记入返回 dict;真正落盘要等 P3 的
  拍板确认通道(§6),这里只负责产出候选载荷。
- handler 契约:mutates=False → 返回 str(结果文本,直接进 result 事件的 text 字段);
  mutates=True → 返回 dict(proposal 载荷字段,如 slot/content),run_tool 补 t/id 信封。
  v1a 只有「提设定」一个 mutates 工具,此处按其固定参数名(落点/内容)在 handler 里组装
  proposal 载荷;未来若新增第二个 mutates 工具,这个「handler 自产载荷字段」的形状已经
  是通用的(不用改 run_tool),不需要现在过度设计。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import journey, paths, slots
from .fsutil import safe_join

_READ_MAX_CHARS = 3000   # 单条工具结果预算(spec §4 常量表:单条工具结果 ≤3k 字)
_KANDIJI_TOP_K = 3       # 看地基每段展示的未填槽位数上限


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: tuple[str, ...]
    desc: str
    handler: Callable
    mutates: bool


# ── 路径守卫:safe_join(机制守卫①)+ 点开头段拒(机制守卫②)+ 白名单谓词 ──────────
# 前缀从 paths.py 常量派生(BRAIN_DIR/BODY_DIR),不手拼「外置大脑」「正文」字面量;
# 「skills」paths.py 没有对应常量(它是模板/题材库的概念,归 scaffold.py 的 GENRE_DIR 派生),
# 沿用仓库既有惯例(agents.py/draft.py/deconstruct.py 均手写该字面量)。
_READ_PREFIXES = (f"{paths.BRAIN_DIR}/", f"{paths.BODY_DIR}/", "skills/")


def _safe_read_path(root: Path | str, rel: str) -> Path:
    """把 rel 锁进读白名单:越界/点开头段/白名单外一律 ValueError。"""
    base = Path(root).resolve()
    r = str(rel or "").replace("\\", "/").strip()
    if not r:
        raise ValueError("路径不能为空。")
    # 通用规则:路径任一段以「.」开头即拒(点开头 = 引擎自动维护区,paths.py 顶注红线)。
    # 在 safe_join 之前查:即便某个含 .. 的路径最终 resolve 后仍落在书根内,也照拒——
    # 这条是「点段」黑名单,不只是「越界」检测,两把尺子各管各的。
    if any(seg.startswith(".") for seg in r.split("/") if seg):
        raise ValueError(f"路径不合法(点开头段是引擎自动维护区,拒绝访问):{rel}")
    target = safe_join(base, r)   # 越界(../、绝对路径顶掉 root)抛 ValueError
    rel_norm = target.relative_to(base).as_posix()
    if not rel_norm.startswith(_READ_PREFIXES):
        raise ValueError(f"路径不在只读白名单内(仅 {paths.BRAIN_DIR}/{paths.BODY_DIR}/skills):{rel}")
    return target


def _handle_read(root: Path, 路径: str = "", 起行: str = "", 止行: str = "", **_ignored) -> str:
    """返回文件正文;超 3k 字截断并提示带「起行/止行」参数重取指定行区间。"""
    p = _safe_read_path(root, 路径)
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在:{路径}")
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = int(起行) if str(起行).strip().isdigit() else None
    end = int(止行) if str(止行).strip().isdigit() else None
    if start or end:
        s = max(1, start or 1)
        e = min(len(lines), end or len(lines))
        text = "\n".join(lines[s - 1:e])
    if len(text) > _READ_MAX_CHARS:
        total_chars = len(text)
        text = (text[:_READ_MAX_CHARS]
                + f"\n\n…(已截断;此区间共 {len(lines)} 行、{total_chars} 字,超 {_READ_MAX_CHARS} 字预算。"
                  f"带「起行」「止行」参数重取指定行区间。)")
    return text


def _handle_kandiji(root: Path) -> str:
    """槽位扫描器摘要:遍历 journey.STAGES,每段一行「段名 未填N/总数:前几个未填 容器#键」。"""
    lines: list[str] = []
    for spec in journey.STAGES:
        stage_slot_list = slots.stage_slots(root, spec)
        if not stage_slot_list:
            continue
        unfilled = [s for s in stage_slot_list if not s.filled]
        line = f"【{spec.key}】未填 {len(unfilled)}/{len(stage_slot_list)}"
        if unfilled:
            line += "：" + "、".join(s.id for s in unfilled[:_KANDIJI_TOP_K])
        lines.append(line)
    return "\n".join(lines) if lines else "(暂无可扫描的槽位)"


def _handle_tishe(root: Path, 落点: str = "", 内容: str = "") -> dict:
    """产候选卡载荷(不写盘):校验落点/内容非空,返回 {"slot", "content"} 供 run_tool 组装 proposal。"""
    slot = str(落点 or "").strip()
    content = str(内容 or "").strip()
    if not slot:
        raise ValueError("提设定缺少「落点」参数(格式:容器#键,如 外置大脑/立项卡.md#题材)。")
    if not content:
        raise ValueError("提设定缺少「内容」参数。")
    return {"slot": slot, "content": content}


REGISTRY: dict[str, ToolSpec] = {
    "读文件": ToolSpec(
        name="读文件", params=("路径",),
        desc="返回文件正文(只读白名单:外置大脑/skills/正文);超 3000 字截断,可带「起行」「止行」重取。",
        handler=_handle_read, mutates=False,
    ),
    "看地基": ToolSpec(
        name="看地基", params=(),
        desc="槽位扫描器摘要:各段(立项/世界观/人物/卡章纲)未填槽位统计。",
        handler=_handle_kandiji, mutates=False,
    ),
    "提设定": ToolSpec(
        name="提设定", params=("落点", "内容"),
        desc="产出候选卡(proposal),不写盘;作者拍板确认才落盘。",
        handler=_handle_tishe, mutates=True,
    ),
}


def render_contract() -> str:
    """渲染进 prompt 的工具契约段(稳定前缀②):注册表单一真相,不手写第二份协议文案。"""
    lines = ["可用工具(每次最多用一个;格式:一行「用:工具名」,后接若干「键:值」参数行):"]
    for spec in REGISTRY.values():
        params_txt = "、".join(spec.params) if spec.params else "无"
        lines.append(f"- 用:{spec.name} | 参数:{params_txt} | {spec.desc}")
    return "\n".join(lines)


def run_tool(root: Path | str, name: str, params: dict | None, *, ts: str) -> dict:
    """执行一次工具调用 → 结果事件 dict(不落盘;提设定产 proposal,真正落盘走 P3 拍板通道)。

    id 由传入的 ts 派生(无 Date.now 依赖);同一轮内多次 mutates 调用的 ts 唯一性由调用方
    (对话循环)保证——本函数只做纯派生,不生成随机数、不读挂钟。
    """
    root = Path(root)
    params = dict(params or {})
    spec = REGISTRY.get(name)
    if spec is None:
        return {"t": "result", "error": f"未知工具:{name}"}
    try:
        result = spec.handler(root, **params)
    except TypeError as e:
        return {"t": "result", "error": f"参数不对(「{name}」需要 {spec.params}):{e}"}
    except (ValueError, FileNotFoundError, OSError) as e:
        return {"t": "result", "error": str(e)}
    if spec.mutates:
        return {"t": "proposal", "id": f"p-{ts}", **result}
    return {"t": "result", "text": result}
