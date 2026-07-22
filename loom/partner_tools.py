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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import journey, paths, slots
from .fsutil import safe_join

_READ_MAX_CHARS = 3000   # 单条工具结果预算(spec §4 常量表:单条工具结果 ≤3k 字)


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
    """把 rel 锁进读白名单:越界/点开头段/白名单外一律 ValueError。

    点段检查跑两遍,缺一都留后门:
    ①原始请求串——挡字面写 外置大脑/.拆书/x.md 这种直球。
    ②safe_join resolve 后、相对 root 的真实路径——挡「请求串字面干净、但是个符号链接,
      resolve 跟随后落进点目录」的绕过(书内 外置大脑/link.md 指向 外置大脑/.拆书/secret.md,
      字符串本身不含点段、①放行,不补②就能读到 .拆书 里的机密)。
    白名单前缀检查同样基于②算出的真实相对路径,不基于原始请求串——防链接指向白名单外。
    root 自身可能是符号链接(macOS /tmp -> /private/tmp):这里的 base 和 safe_join 内部
    第二次 resolve 出的 base 是同一个值(对已 resolve 的路径再 resolve 是幂等的),
    两边比较口径一致,不会因 root 自身是链接而把合法子路径误判越界或误判点段。
    """
    base = Path(root).resolve()
    r = str(rel or "").replace("\\", "/").strip()
    if not r:
        raise ValueError("路径不能为空。")
    # 点段检查①:查原始请求串。即便某个含 .. 的路径最终 resolve 后仍落在书根内,也照拒——
    # 这条是「点段」黑名单,不只是「越界」检测,两把尺子各管各的。
    if any(seg.startswith(".") for seg in r.split("/") if seg):
        raise ValueError(f"路径不合法(点开头段是引擎自动维护区,拒绝访问):{rel}")
    target = safe_join(base, r)   # 越界(../、绝对路径顶掉 root)抛 ValueError;target 已 resolve,符号链接已跟随
    rel_norm = target.relative_to(base).as_posix()
    # 点段检查②:查 resolve 后的真实路径(挡符号链接 resolve 后落入点目录的绕过)。
    if any(seg.startswith(".") for seg in rel_norm.split("/") if seg):
        raise ValueError(f"路径不合法(解析后落入引擎自动维护区,拒绝访问):{rel}")
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
        # 提示语本身也要计入预算(之前正文截到 3000 字后再拼提示语,总长会超红线)——
        # 先把提示语拼出来,正文按「预算减提示语长度」截断,最后再钳一次兜底。
        suffix = (f"\n\n…(已截断;此区间共 {len(lines)} 行、{total_chars} 字,超 {_READ_MAX_CHARS} 字预算。"
                  f"带「起行」「止行」参数重取指定行区间。)")
        body_budget = max(0, _READ_MAX_CHARS - len(suffix))
        text = text[:body_budget] + suffix
        text = text[:_READ_MAX_CHARS]
    return text


def _handle_kandiji(root: Path) -> str:
    """槽位扫描器全量明细(spec §4/§5.3:看地基=全量明细,区别于环境快照的缩略只读投影)。

    每段列出全部槽位(不只未填的前几个),每槽一行:容器#键 + 已填/未填 + preview
    (已填值前若干字)。环境快照(T4 会建)才是「每段一行未填N/总数」的缩略版,
    两者刻意不同——伙伴细看某格要看到实际内容,靠的就是这份全量明细。
    """
    lines: list[str] = []
    for spec in journey.STAGES:
        stage_slot_list = slots.stage_slots(root, spec)
        if not stage_slot_list:
            continue
        filled_n = sum(1 for s in stage_slot_list if s.filled)
        lines.append(f"【{spec.key}】共 {len(stage_slot_list)} 槽,已填 {filled_n}/未填 {len(stage_slot_list) - filled_n}")
        for s in stage_slot_list:
            if s.filled:
                mark = f"已填：{s.preview}"
            else:
                # 未填槽附 hint(如「不是平台」),让模型知道这格填什么——已填槽 preview 已够说明,不重复附
                mark = f"未填 — {s.hint}" if s.hint else "未填"
            lines.append(f"  {s.id}：{mark}")
    return "\n".join(lines) if lines else "(暂无可扫描的槽位)"


def _handle_tishe(root: Path, 落点: str = "", 内容: str = "") -> dict:
    """产候选卡载荷(不写盘):校验落点/内容非空+落点存在,返回 {"slot", "content", "before"} 供
    run_tool 组装 proposal。落点不存在则抛 ValueError(LLM 自纠,不等 confirm 才炸)。
    before=落点当前 preview(现扫 stage_slots 取),confirm 落盘前会用快照守卫比对,
    防止「提案挂起期间作者手改了这一格」被覆盖(P1 快照守卫,见 partner_confirm)。"""
    slot = str(落点 or "").strip()
    content = str(内容 or "").strip()
    if not slot:
        raise ValueError("提设定缺少「落点」参数(格式:容器#键,如 外置大脑/立项卡.md#题材)。")
    if not content:
        raise ValueError("提设定缺少「内容」参数。")
    before = ""
    found_slot = None
    for spec in journey.STAGES:
        found = next((s for s in slots.stage_slots(root, spec) if s.id == slot), None)
        if found is not None:
            # bug4:占位模板不算「已有值」——只有实质内容(filled)才算 before。占位当 before
            # 会让候选卡显「现在是:(占位示例…)」+ 按钮变「替换」(误导)。必须与 usecases.
            # _slot_preview 的 filled 门同口径,否则 confirm 时 current!=before 误判 stale。
            before = found.preview if found.filled else ""
            found_slot = found
            break
    if found_slot is None:
        raise ValueError(f"落点不存在:「{slot}」。去用「看地基」获取有效落点,从中复制完整 ID,不要自己构造。")
    return {"slot": slot, "content": content, "before": before}


# ── 全文搜索(搜正文/搜设定) ──────────────────────────────────────────

_SEARCH_MAX_RESULTS = 10      # 最多返回 10 条
_SEARCH_MAX_CHARS = 200       # 单条 ≤200 字
_SEARCH_CONTEXT_LINES = 2     # 匹配行前后各 2 行


def _search_files(root: Path, rel_glob: str) -> list[Path]:
    """按 glob 搜文件,按文件名数字序排序(正文文件)或字典序(设定)。"""
    base = Path(root)
    return sorted(
        [p for p in base.glob(rel_glob) if p.is_file()],
        key=lambda p: (
            int(m.group(1)) if (m := re.search(r"第(\d+)章", p.stem)) else 0,
            p.name,
        ),
    )


def _extract_lines(text: str, match_line: int, total_lines: int) -> str:
    """从文本中提取匹配行前后各 2 行的上下文,裁到 ≤200 字。"""
    lines = text.splitlines()
    start = max(0, match_line - _SEARCH_CONTEXT_LINES)
    end = min(len(lines), match_line + _SEARCH_CONTEXT_LINES + 1)
    snippet = "\n".join(lines[start:end])
    if len(snippet) > _SEARCH_MAX_CHARS:
        snippet = snippet[:_SEARCH_MAX_CHARS] + "…"
    return snippet


def _handle_search_text(root: Path, query: str, chapter: str = "") -> str:
    """搜索正文/目录下 md 文件,按文件名数字序排序,全文扫描返回匹配结果。"""
    if not query:
        raise ValueError("搜正文需要关键词(query)。")
    q = query.strip()
    body_root = Path(root) / paths.BODY_DIR
    if not body_root.is_dir():
        return "(暂无正文章节)"
    files = _search_files(root, f"{paths.BODY_DIR}/*.md")
    if chapter:
        files = [f for f in files if chapter in f.stem]
    results: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.search(re.escape(q), line, re.IGNORECASE) and len(results) < _SEARCH_MAX_RESULTS:
                snippet = _extract_lines(text, i, len(lines))
                results.append(f"{f.stem} | L{i+1}:{snippet}")
        if len(results) >= _SEARCH_MAX_RESULTS:
            break
    if not results:
        return f"(在正文中未找到「{q}」相关结果)"
    return "\n---\n".join(results)


def _search_brain_file(root: Path, rel: str) -> list[Path]:
    """返回外置大脑目标文件/目录下的 .md 文件。"""
    p = Path(root) / rel
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(p.glob("*.md"))
    return []


def _handle_search_brain(root: Path, query: str) -> str:
    """搜索外置大脑设定文件:世界观/人物/卡章纲/违禁词等。"""
    if not query:
        raise ValueError("搜设定需要关键词(query)。")
    q = query.strip()
    # 外置大脑设定文件清单
    brain_targets: list[str] = [
        paths.WORLD_REL,
        paths.CHARS_REL,
        paths.CARD_REL,
        paths.BANNED_REL,
        paths.PROJECT_CARD_REL,
        paths.STATEBOOK_REL,
        paths.WORLD_DIR_REL,
        paths.CHARS_DIR_REL,
    ]
    results: list[str] = []
    for rel in brain_targets:
        files = _search_brain_file(root, rel)
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if re.search(re.escape(q), line, re.IGNORECASE) and len(results) < _SEARCH_MAX_RESULTS:
                    snippet = _extract_lines(text, i, len(lines))
                    results.append(f"{f.parent.name}/{f.stem} | L{i+1}:{snippet}")
                if len(results) >= _SEARCH_MAX_RESULTS:
                    break
            if len(results) >= _SEARCH_MAX_RESULTS:
                break
        if len(results) >= _SEARCH_MAX_RESULTS:
            break
    if not results:
        return f"(在外置大脑中未找到「{q}」相关结果)"
    return "\n---\n".join(results)


REGISTRY: dict[str, ToolSpec] = {
    "读文件": ToolSpec(
        name="读文件", params=("路径",),
        desc="返回文件正文(只读白名单:外置大脑/skills/正文);超 3000 字截断,可带「起行」「止行」重取。",
        handler=_handle_read, mutates=False,
    ),
    "看地基": ToolSpec(
        name="看地基", params=(),
        desc="槽位扫描器全量明细:各段(立项/世界观/人物/卡章纲)每个槽位的完整ID(容器#键)、已填/未填、preview。"
              "落点必须从本工具的返回值中完整复制,不要自己构造 ID 或路径。",
        handler=_handle_kandiji, mutates=False,
    ),
    "提设定": ToolSpec(
        name="提设定", params=("落点", "内容"),
        desc="产出候选卡(proposal),不写盘;作者拍板确认才落盘。",
        handler=_handle_tishe, mutates=True,
    ),
    "搜正文": ToolSpec(
        name="搜正文", params=("query", "chapter"),
        desc="全文搜索正文中的关键词(大小写不敏感),可选限定章名;返回匹配段落及其上下文(前后各2行),单条≤200字,最多10条。",
        handler=_handle_search_text, mutates=False,
    ),
    "搜设定": ToolSpec(
        name="搜设定", params=("query",),
        desc="全文搜索外置大脑设定文件中的关键词(大小写不敏感),包括世界观、人物卡、卡章纲、违禁词等;返回匹配段落及其上下文(前后各2行),单条≤200字,最多10条。",
        handler=_handle_search_brain, mutates=False,
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
