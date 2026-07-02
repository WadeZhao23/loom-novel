"""Agent 链:按顺序跑 5 个工序,累积一个"本章工作区",每步读到目前为止的全部产物。

Agent 的系统提示词写在 agents/<角色>.md 里(顶部 YAML 声明 reads),不硬编码进这里。
引擎不依赖任何前端:进度通过 progress(event: dict) 回调发出,CLI / 桌面端各自渲染。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import gates
from .backends import Backend, LoomBackendError
from .chaptertext import compose, strip_title
from .config import Config
from .errors import render
from .fsutil import atomic_write_text, snapshot_chapter
from .guard import STEP, chapter_profile, validate_output

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


# 质检/去AI味 关卡:挂在某一棒产出之后。挑硬伤→回炉,不打分、不硬阻断(见 ADR-0006)。
# role -> (人看的名字, 复审提示词, 回炉提示词, 复审要读的设定/方法论, 是否带上一章看钩子)
_GATES: dict[str, tuple[str, str, str, list[str], bool]] = {
    "编辑": ("质检", gates.CRITIC_质检, gates.REVISE_质检,
            ["skills/评估自检.md", "外置大脑/人物卡.md", "外置大脑/世界观.md", "外置大脑/卡章纲.md"], True),
    "润色师": ("去AI味", gates.CRITIC_去AI味, gates.REVISE_去AI味,
             ["skills/去AI味.md", "外置大脑/写作指纹.md"], False),
}


# 流水线顺序(角色名,不是题材名词)
PIPELINE = ["设定师", "大纲师", "写手", "编辑", "润色师"]

_PRODUCES = {
    "设定师": "本章设定锚点",
    "大纲师": "本章场景骨头(分镜细纲)",
    "写手": "本章初稿",
    "编辑": "本章改稿",
    "润色师": "本章终稿",
}
_SHORT = {"设定师": 350, "大纲师": 450}  # 其余按 config.chapter_chars

# 编辑产出"改稿 + 《本章改动留痕》",用哨兵分隔。留痕给作者看,绝不进正文/快照/写作指纹。
EDIT_NOTE_SENTINEL = "<!--LOOM:EDIT-NOTE-->"


def _split_edit_note(text: str) -> tuple[str, str]:
    """按哨兵首次出现切分 →(干净正文 body, 留痕 note)。无哨兵则 (text, "")。"""
    idx = text.find(EDIT_NOTE_SENTINEL)
    if idx == -1:
        return text, ""
    return text[:idx].rstrip(), text[idx + len(EDIT_NOTE_SENTINEL):].strip()


def _strip_edit_note(text: str) -> str:
    """落盘前兜底:只保留哨兵前的干净正文(保护 learn 的 diff 源不被留痕污染)。"""
    return _split_edit_note(text)[0] if EDIT_NOTE_SENTINEL in text else text


def _save_edit_note(project_root: Path, chapter_n: int, note: str, progress: Progress) -> None:
    """留痕落盘外的 .审稿留痕/(人可读可改,绝不被任何 learn/写作指纹流程读取)。"""
    path = project_root / ".审稿留痕" / f"第{chapter_n}章.md"
    atomic_write_text(path, note + "\n")
    progress({"type": "edit_note", "chapter": chapter_n, "path": str(path)})


def _save_gate_remaining(project_root: Path, chapter_n: int, label: str,
                         remaining: list, progress: Progress, *, header: str | None = None) -> None:
    """gate 跑满轮数仍未解决的硬伤 → 追加进审稿留痕(不阻断,只留痕给作者看)。

    header 给了就用它当小标题(伏笔悬空提醒复用此函数,但措辞不同、与"跑满复审轮数"无关)。
    """
    path = project_root / ".审稿留痕" / f"第{chapter_n}章.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header or f"\n## {label}未解决项(跑满复审轮数仍残留,未阻断,供你定夺)"]
    for i in remaining:
        ev = f" | 证据:「{i.evidence}」" if getattr(i, "evidence", "") else ""
        lines.append(f"- {i.kind}:{i.desc}{ev}")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    progress({"type": "edit_note", "chapter": chapter_n, "path": str(path)})


def _flag_stale_foreshadow(project_root: Path, chapter_n: int, config: Config, progress: Progress) -> None:
    """编辑棒后顺手扫一遍卡章纲:埋了很久仍无推进/回收的伏笔 → 进审稿留痕提醒。

    纯本地、不发 LLM、不打分、不回炉、不阻断(它读卡章纲、质检回炉改的是正文,放回炉只会空转)。
    任何异常都吞掉——附赠类提醒绝不拖累出稿(同 _scan_sensitive)。卡章纲没 recap 伏笔行时自然为空。
    """
    if getattr(config, "foreshadow_distance", 0) <= 0:
        return
    try:
        from .hooks import stale
        issues = stale(project_root, chapter_n, config.foreshadow_distance)
    except Exception:
        return
    if not issues:
        return
    _save_gate_remaining(
        project_root, chapter_n, "伏笔悬空", issues, progress,
        header="\n## 伏笔悬空提醒(非阻断,供你定夺;若本章正回收可忽略)",
    )


def _edit_stream_filter(progress: Progress) -> Callable[[str], None]:
    """编辑棒的流式过滤:只把哨兵【之前】的干净改稿流给前端,哨兵及其后的留痕不外流。

    哨兵可能被切成多个 delta,故按累计串判断、并留一个尾窗防止半截哨兵漏判。
    """
    st = {"buf": "", "emitted": 0, "cut": False}

    def cb(delta: str) -> None:
        if st["cut"]:
            return
        st["buf"] += delta
        idx = st["buf"].find(EDIT_NOTE_SENTINEL)
        if idx == -1:
            clean = st["buf"][: max(0, len(st["buf"]) - len(EDIT_NOTE_SENTINEL))]
        else:
            clean = st["buf"][:idx]
        new = clean[st["emitted"]:]
        if new:
            progress({"type": "agent_chunk", "role": "编辑", "delta": new})
            st["emitted"] += len(new)
        if idx != -1:
            st["cut"] = True

    return cb


@dataclass
class Agent:
    name: str
    reads: list[str] = field(default_factory=list)
    reads_first_chapter: list[str] = field(default_factory=list)
    produces: str = ""
    system_prompt: str = ""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """极简 YAML frontmatter 解析(只够解析本项目自己的 agents/*.md)。"""
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    meta: dict = {}
    current_key: str | None = None
    for raw in fm.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            meta.setdefault(current_key, []).append(line.lstrip()[2:].strip())
        elif ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            current_key = key
            meta[key] = val if val else []
    return meta, body.strip()


def load_agent(project_root: Path, role: str) -> Agent:
    path = project_root / "agents" / f"{role}.md"
    if not path.exists():
        from .errors import render
        raise FileNotFoundError(render("agent_prompt_missing", detail=str(path)))
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return Agent(
        name=meta.get("name", role) or role,
        reads=meta.get("reads", []) or [],
        reads_first_chapter=meta.get("reads_first_chapter", []) or [],
        produces=meta.get("produces", _PRODUCES.get(role, "")),
        system_prompt=body,
    )


def _read_files(project_root: Path, rels: list[str], progress: Progress) -> str:
    blocks = []
    for rel in rels:
        p = project_root / rel
        if p.is_dir():
            # 目录型 reads(如 skills/题材):读其中所有 .md(跳过 README,排序保证签名稳定)
            for f in sorted(p.glob("*.md")):
                if f.stem != "README":
                    blocks.append(f"【{rel}/{f.name}】\n{f.read_text(encoding='utf-8').strip()}")
        elif p.exists():
            blocks.append(f"【{rel}】\n{p.read_text(encoding='utf-8').strip()}")
        else:
            progress({"type": "warn", "message": f"跳过缺失文件 {rel}"})
    return "\n\n".join(blocks)


def _prev_chapter(project_root: Path, chapter_n: int) -> str:
    """读上一章【手改后的】正文做行文衔接(不是 .原稿 快照);去掉标题行,只喂正文体。"""
    if chapter_n <= 1:
        return ""
    p = project_root / "正文" / f"第{chapter_n - 1}章.md"
    return strip_title(p.read_text(encoding="utf-8")).strip() if p.exists() else ""


# 二级标题行(`## 标题`,容忍前导空格与「##标题」无空格;### 不算):切世界观小节用。
_H2_RE = re.compile(r"^\s{0,3}##\s*(?!#)(.+?)\s*$")
_H3_RE = re.compile(r"^\s{0,3}###\s*(?!#)(.+?)\s*$")
# 三级及更深标题行(### ~ ######):剔反转子块时要知道层级,才能"剔到同级/更浅标题为止"。
_H3PLUS_RE = re.compile(r"^\s{0,3}(#{3,6})\s*(.+?)\s*$")

# 世界观里【必须逐字照搬】的硬设定小节——按标题(H2,H2 没命中再看其内 H3)含这些词命中,
# 整段原文透传给大纲师/写手。只圈"规则 + 专名"(境界阶梯/金手指代价/地名势力):这些一旦被
# 复述就漂(F~SSS 凭空多出"一阶0级"、"一中"写成"二中")。故意不圈「一句话定位」(情绪基调、本就该意译)。
_HARDFACT_KW = ("力量", "体系", "境界", "等级", "修为", "实力", "修炼", "金手指",
                "地理", "势力", "阵营", "地图", "区域")

# 反转/真相/底牌类小节:即便标题撞上硬设定关键词(如「## 势力背后的真相」),也绝不逐字喂写手
# ——逐字喂等于提前抖包袱,踩本功能唯一的硬红线。deny 压过 allow,且连嵌进 ### 的反转一并剥掉。
_SPOILER_KW = ("冰山", "真相", "反转", "伏笔", "底牌", "终局", "结局", "隐藏", "暗线", "秘密")

# 人物卡里「类型 · 名字」的名字分隔符:专名册只认带它的标题,免得把「## 主角」占位标题、
# learn 追加的「## AI 补充…」段名当人名喂写手。
_NAME_SEP = ("·", "・", "•")


def _md_sections(md: str, head_re: re.Pattern) -> list[tuple[str, str]]:
    """按 head_re 命中的标题行切成 [(标题文本, 含标题行的整段)];前言忽略,更深层标题归属其上段。"""
    sections: list[tuple[str, str]] = []
    head: str | None = None
    buf: list[str] = []
    for ln in md.splitlines():
        m = head_re.match(ln)
        if m:
            if head is not None:
                sections.append((head, "\n".join(buf).rstrip()))
            head, buf = m.group(1), [ln.rstrip()]
        elif head is not None:
            buf.append(ln.rstrip())
    if head is not None:
        sections.append((head, "\n".join(buf).rstrip()))
    return sections


def _md_h2_sections(md: str) -> list[tuple[str, str]]:
    """把 markdown 按二级标题切;H1 与前言忽略,### 归属其上层 H2。"""
    return _md_sections(md, _H2_RE)


def _drop_spoiler_subsections(section: str) -> str:
    """从一段里剔掉标题命中 _SPOILER_KW 的子块(### 及更深都算,连同其子孙),
    直到出现同级或更浅的标题为止——只认 ### 会被写进 #### 的反转绕过。"""
    out: list[str] = []
    skip = 0  # >0 = 正在剔除,值为命中反转的标题层级
    for ln in section.splitlines():
        m = _H3PLUS_RE.match(ln)
        if m:
            level = len(m.group(1))
            if skip and level <= skip:
                skip = 0
            if not skip and any(s in m.group(2) for s in _SPOILER_KW):
                skip = level
        if not skip:
            out.append(ln)
    return "\n".join(out).rstrip()


def _name_roster(card_path: Path) -> str:
    """从人物卡抓「## 类型 · 名字」式专名册——只认带名字分隔符的标题,顺手滤掉 learn 追加的
    「## AI 补充…」段与「## 主角」这类没填名的占位标题:宁可空,也绝不把段名当人名喂写手。"""
    if not card_path.is_file():
        return ""
    names = [head for head, _ in _md_h2_sections(card_path.read_text(encoding="utf-8"))
             if any(s in head for s in _NAME_SEP) and "补充" not in head]
    return "\n".join(f"- {n}" for n in names)


def _pick_hardfacts(md: str) -> list[str]:
    """世界观里命中 _HARDFACT_KW 的小节。H2 优先;H2 没命中再看其内的 H3(用户把硬设定写在
    三级标题下);整份没用 ## 时按 H3 顶层切。deny(_SPOILER_KW)一律压过 allow。"""
    def hard(h: str) -> bool: return any(kw in h for kw in _HARDFACT_KW)
    def spoiler(h: str) -> bool: return any(s in h for s in _SPOILER_KW)
    picked: list[str] = []
    h2s = _md_h2_sections(md)
    for head, body in h2s:
        if spoiler(head):
            continue
        if hard(head):
            picked.append(_drop_spoiler_subsections(body))
        else:
            picked += [_drop_spoiler_subsections(b) for h, b in _md_sections(body, _H3_RE)
                       if hard(h) and not spoiler(h)]
    if not h2s:  # 整份世界观没写 ##、只用了 ###
        picked = [_drop_spoiler_subsections(b) for h, b in _md_sections(md, _H3_RE)
                  if hard(h) and not spoiler(h)]
    return [p for p in picked if p.strip()]


def _hardfacts_for(project_root: Path, progress: Progress = _noop) -> str:
    """确定性切出【硬设定】原文,绕开设定师的有损复述,逐字透传给大纲师/写手:
    世界观里命中 _HARDFACT_KW 的小节(境界阶梯/金手指代价/地名势力)+ 人物卡专名册。

    红线:纯字符串切片,不调 LLM、不打分、不建实体库;空/缺失一律返回空串(附加增强,绝不阻断出稿)。
    反转段(_SPOILER_KW)deny 压过 allow,绝不逐字喂写手。
    世界观有内容却一节都没命中 → 发 warn 提示检查标题写法(只提示,照旧不阻断)。
    注:learn 自动追加到「## AI 补充」段的新层级/新势力【不】进逐字块(那段标题不含硬设定关键词,
    且自动追加块不该被当真相喂写手);要让它们逐字护身,把它们手并进 ## 力量体系 / ## 地理 等正式段。
    """
    blocks: list[str] = []
    wv = project_root / "外置大脑" / "世界观.md"
    if wv.is_file():
        picked = _pick_hardfacts(wv.read_text(encoding="utf-8"))
        if picked:
            blocks.append("\n\n".join(picked))
        else:
            progress({"type": "warn", "message":
                      "世界观里没识别到硬设定小节(如「## 力量体系」「## 地理 / 势力」),"
                      "等级/专名这次没有逐字保护——请检查标题写法"})
    roster = _name_roster(project_root / "外置大脑" / "人物卡.md")
    if roster:
        blocks.append("【人物专名册(照此写,别改名/别另造名)】\n" + roster)
    return "\n\n".join(b for b in blocks if b.strip())


# 标题生成(附赠动作:用户选了「自动起标题」。失败/空一律静默回退无标题,绝不阻断出稿)
_TITLE_SYSTEM = (
    "你是网文编辑,给这一章起一个【章节标题】。要求:6-16 字,贴合内容、有点钩子、不剧透章末反转;"
    "不要带「第N章/第一章」之类章号,不要书名号/引号/星号包裹,只输出标题本身这一行,别的什么都不要输出。"
)


def _clean_title(raw: str) -> str:
    """把模型返回收成一个干净标题:取首行、去包裹、去「第N章」前缀;太长/太短/像句子就当没有。"""
    if not raw or not raw.strip():
        return ""
    t = raw.strip().splitlines()[0].strip().lstrip("#").strip()
    t = t.strip("「」『』“”‘’《》<>#*`： ").strip()
    t = re.sub(r"^第\s*[0-9一二三四五六七八九十百零]+\s*章[:：、.\s]*", "", t).strip()
    return t if 1 < len(t) <= 24 else ""   # 太长多半是模型答非所问吐了一段话 → 回退无标题


def _generate_title(backend: Backend, prose: str) -> str:
    """给本章起个标题。任何失败(网络/空响应/格式不对)都吞掉、回退空串——绝不让附赠动作拖累出稿。"""
    try:
        raw = backend.complete(_TITLE_SYSTEM, f"这一章的正文如下,给它起个标题:\n\n{prose[:1200]}", max_chars=24)
    except Exception:
        return ""
    return _clean_title(raw)


def _outline_path(project_root: Path, chapter_n: int) -> Path:
    """本章细纲(大纲师的分镜)落盘处:可看可改。一旦存在,大纲师就读它(WYSIWYG)——
    你改了它,重写本章就按你的来;想要新方案,清空它或点「重新生成细纲」。"""
    return project_root / "正文" / ".细纲" / f"第{chapter_n}章.md"


def _knowledge_for(project_root: Path, chapter_n: int, role: str) -> tuple[Agent, str]:
    a = load_agent(project_root, role)
    rels = list(a.reads) + (a.reads_first_chapter if chapter_n == 1 else [])
    return a, _read_files(project_root, rels, _noop)


def _build_user_prompt(chapter_n: int, role: str, agent: Agent, knowledge: str,
                       prev: str, workspace: list[tuple[str, str]], hardfacts: str = "") -> str:
    parts = [f"# 你要写的是第 {chapter_n} 章。"]
    if knowledge:
        parts.append("## 你要遵循的设定/方法论\n" + knowledge)
    if hardfacts and role in ("大纲师", "写手"):
        parts.append("## 硬设定(逐字照搬,等级/境界名、专名、金手指代价一字不改、不许新增体系)\n"
                     + hardfacts)
    if prev and role in ("大纲师", "写手"):
        parts.append("## 上一章正文(接住它的结尾钩子,别重复、别断裂)\n" + prev[-1500:])
    if workspace:
        ctx = "\n\n".join(f"### {label}\n{text}" for label, text in workspace)
        parts.append("## 本章工作区(上游工序已产出,基于它继续)\n" + ctx)
    parts.append(f"## 你的任务\n产出【{agent.produces}】。只输出这一项,不要解释你在做什么。")
    return "\n\n".join(parts)


def run_pipeline(
    project_root: Path,
    chapter_n: int,
    backend: Backend,
    config: Config,
    progress: Progress = _noop,
    *,
    slow: float = 0.0,
    resume: bool = True,
    critic_backend: Backend | None = None,
) -> tuple[Path, str]:
    """跑一章。返回 (终稿路径, 终稿文本)。进度通过 progress 回调发出。

    resume=True 时跳过 ledger 里"已完成且上游未变"的工序(断点续跑,省 DeepSeek 计费);
    上游(reads 文件 / 已累积产物 / 上一章正文)任一变化,从该工序起重算。

    critic_backend 给了就让质检/去AI味的**复审员**走它(通常是便宜模型);写作/回炉仍用 backend。
    """
    from . import ledger

    progress({"type": "pipeline_start", "chapter": chapter_n, "roles": PIPELINE})
    prev = _prev_chapter(project_root, chapter_n)
    hardfacts = _hardfacts_for(project_root, progress)  # 硬设定逐字块,进大纲师/写手 prompt

    # 注:hardfacts 故意不进续跑签名。它只取自 世界观.md / 人物卡.md,而这两份都在设定师
    # (永远是 PIPELINE[0])的 reads 里——改硬设定必先让设定师签名失配、从下标 0 全量重跑,
    # 大纲师/写手自然吃到新硬设定。再折进签名只会白白冲掉在跑章节的 ledger、触发无谓重计费。
    # 唯一缺口:纯代码改了 _HARDFACT_KW/切片逻辑而世界观文件没动时,半截章续跑会沿用旧切法的
    # 写手稿——属升级期一次性、自愈(--force/--no-resume 或动一下世界观即重算),不值得为它毁 ledger。
    def _sig(knowledge: str, ws: list[tuple[str, str]]) -> str:
        return ledger.sha(knowledge + "\x1f" + "\n".join(t for _, t in ws) + "\x1f" + prev)

    def _upstream_of(role: str, ws: list[tuple[str, str]]) -> str:
        _, knowledge = _knowledge_for(project_root, chapter_n, role)
        return _sig(knowledge, ws)

    if resume:
        start_idx, workspace = ledger.resume_point(project_root, chapter_n, _upstream_of)
        for role in PIPELINE[:start_idx]:
            progress({"type": "agent_skip", "role": role, "reason": "已完成且上游未变"})
    else:
        start_idx, workspace = 0, []

    for role in PIPELINE[start_idx:]:
        agent, knowledge = _knowledge_for(project_root, chapter_n, role)
        progress({"type": "agent_start", "role": role})
        up_sha = _sig(knowledge, workspace)  # 记录入此工序时的上游签名(供下次续跑比对)

        max_chars = _SHORT.get(role, config.chapter_chars)
        outline_path = _outline_path(project_root, chapter_n) if role == "大纲师" else None
        if outline_path and outline_path.is_file() and outline_path.read_text(encoding="utf-8").strip():
            # 已有细纲(多半你手改过)→ 直接用它,不再调大纲师;改它/清空它即重新生成(WYSIWYG)。
            output = outline_path.read_text(encoding="utf-8").strip()
            progress({"type": "agent_chunk", "role": role, "delta": output})
            progress({"type": "info", "message": f"第 {chapter_n} 章沿用你的细纲(在「本章细纲」里改它 / 重新生成)"})
        else:
            user_prompt = _build_user_prompt(chapter_n, role, agent, knowledge, prev, workspace, hardfacts)
            # 编辑棒的输出含哨兵+留痕,流式时只放哨兵前的干净改稿;其余棒原样透传。
            chunk_cb = (_edit_stream_filter(progress) if role == "编辑"
                        else (lambda d, r=role: progress({"type": "agent_chunk", "role": r, "delta": d})))
            output = backend.complete(agent.system_prompt, user_prompt, max_chars=max_chars, on_chunk=chunk_cb)
            if outline_path:  # 大纲师首次生成 → 落一份可看可改的细纲,之后就读这份
                atomic_write_text(outline_path, output.strip() + "\n")
        if role == "编辑":
            output, note = _split_edit_note(output)  # 留痕切出,只把干净正文交给下游润色师
            if note:
                _save_edit_note(project_root, chapter_n, note, progress)

        # 质检/去AI味 关卡:独立复审→回炉(挑硬伤、不打分、不硬阻断)。残留写进留痕,继续往下。
        if role in _GATES and config.gate_rounds > 0:
            label, critic, revise, gate_reads, need_prev = _GATES[role]
            gk = _read_files(project_root, gate_reads, _noop)
            if need_prev and prev:
                gk += "\n\n【上一章章末(看本章有没有接住它的钩子)】\n" + prev[-800:]
            gres = gates.run_gate(
                backend, label=label, owner_role=role, critic_system=critic, revise_system=revise,
                draft=output, knowledge=gk, produces=agent.produces,
                rounds=config.gate_rounds, max_chars=max_chars, progress=progress,
                critic_backend=critic_backend,
                detector=_deslop_detector(project_root, chapter_n) if role == "润色师" else None,
            )
            output = gres.text
            if gres.remaining:
                _save_gate_remaining(project_root, chapter_n, label, gres.remaining, progress)

        # 伏笔悬空提醒:编辑棒后扫卡章纲,埋了很久仍没还的伏笔进留痕(纯提示,独立于上面的 gate、绝不回炉)
        if role == "编辑":
            _flag_stale_foreshadow(project_root, chapter_n, config, progress)

        # 每棒非空闸:任一棒返回空/拒答都不该静默落盘、再被下游与 learn 二次污染——直接报错刹住,
        # 已完成的工序已进 ledger,修好(换模型)后续跑只重算这一棒,不浪费前面的字数计费。
        reasons = validate_output(output, STEP)
        if reasons:
            raise LoomBackendError(render("model_output_invalid", detail=f"{role}:" + "；".join(reasons)),
                                   code="model_output_invalid")
        ledger.record_step(project_root, chapter_n, role, output, up_sha)  # 即时落盘=断点可续
        workspace.append((agent.produces, output))
        progress({"type": "agent_done", "role": role, "produces": agent.produces})
        if slow:
            time.sleep(slow)

    final_body = _strip_edit_note(workspace[-1][1])  # 兜底:终稿/快照绝不含留痕哨兵
    # 终稿非空硬闸:别把空/残废正文写进 正文+.原稿(空快照会让下次 learn 学到空、二次污染指纹)
    reasons = validate_output(final_body, chapter_profile(config.chapter_chars))
    if reasons:
        raise LoomBackendError(render("model_output_invalid", detail="；".join(reasons)),
                               code="model_output_invalid")
    # 自动起标题(附赠,失败回退无标题);标题进正文首行 H1,且 .原稿快照/ledger 都同口径带上它
    title = _generate_title(backend, final_body)
    final = compose(title, final_body)
    path = _save_chapter(project_root, chapter_n, final)
    ledger.record_snapshot(project_root, chapter_n, final)  # 与 正文/.原稿 同口径(都含 H1),不会误判 drifted
    _scan_sensitive(project_root, chapter_n, final_body, progress)  # 违禁词扫正文体即可(标题不必扫)
    progress({
        "type": "chapter_done",
        "chapter": chapter_n,
        "path": str(path),
        "title": title,
        "chars": len(final_body),
        "preview": final_body[:300],
        "text": final,
    })
    return path, final


def _deslop_detector(project_root: Path, chapter_n: int):
    """给「去AI味」关卡的确定性预筛:句内 AI 翻转句(aitell) + 跨章重复/腔调(fatigue)。

    两者互补:aitell 抓**句内**「不是A而是B」,fatigue 抓**跨章**章首章末雷同/整句复用。命中前都先
    比对写作指纹 anchor 豁免作者签名句;每轮在当前稿上重扫(回炉擦净自然归零)。任何异常都吞掉、
    返回空——附赠类检测绝不拖累出稿(同 _scan_sensitive)。
    """
    try:
        from .aitell import load_anchors
        anchors = load_anchors(project_root)
    except Exception:
        anchors = []

    def _run(text: str):
        out: list = []
        try:
            from .aitell import detect
            out += detect(text, anchors)
        except Exception:
            pass
        try:
            from .fatigue import scan
            out += scan(project_root, chapter_n, text, anchors)
        except Exception:
            pass
        return out

    return _run


def _scan_sensitive(project_root: Path, chapter_n: int, text: str, progress: Progress) -> None:
    """本章终稿过一遍违禁词粗筛;命中只发提示事件,绝不阻断(平台审核终归靠人)。"""
    try:
        from .sensitive import scan
        hits = scan(text, project_root)
    except Exception:
        return
    if hits:
        progress({"type": "sensitive", "chapter": chapter_n,
                  "count": sum(h["count"] for h in hits), "hits": hits[:20]})


def _save_chapter(project_root: Path, chapter_n: int, final: str) -> Path:
    out = project_root / "正文" / f"第{chapter_n}章.md"
    snap = project_root / "正文" / ".原稿" / f"第{chapter_n}章.md"
    snapshot_chapter(project_root, f"正文/第{chapter_n}章.md")  # 覆盖前留旧稿历史(force 重写时保住手改)
    atomic_write_text(out, final + "\n")
    atomic_write_text(snap, final + "\n")  # AI 原稿快照,只给 learn 做 diff
    return out


def regen_outline(project_root: Path, chapter_n: int, backend: Backend,
                  config: Config, progress: Progress = _noop) -> str:
    """重新生成第 N 章细纲:跑 设定师→大纲师,覆盖写 正文/.细纲/第N章.md,返回细纲文本。

    只刷细纲、不碰正文——用于"我想要个新的分镜方案"。之后重写本章会按这份新细纲来。
    设定师此刻会读到最新的世界观/人物卡/卡章纲,所以改了上游再「重新生成细纲」就能吃到。
    """
    prev = _prev_chapter(project_root, chapter_n)
    hardfacts = _hardfacts_for(project_root, progress)
    workspace: list[tuple[str, str]] = []
    outline = ""
    for role in ("设定师", "大纲师"):
        agent, knowledge = _knowledge_for(project_root, chapter_n, role)
        progress({"type": "agent_start", "role": role})
        user_prompt = _build_user_prompt(chapter_n, role, agent, knowledge, prev, workspace, hardfacts)
        out = backend.complete(
            agent.system_prompt, user_prompt, max_chars=_SHORT.get(role, config.chapter_chars),
            on_chunk=lambda d, r=role: progress({"type": "agent_chunk", "role": r, "delta": d}),
        )
        workspace.append((agent.produces, out))
        progress({"type": "agent_done", "role": role, "produces": agent.produces})
        outline = out
    if not outline.strip():  # 模型这次没出细纲 → 不拿空覆盖你原来的细纲
        raise LoomBackendError(render("model_output_invalid", detail="细纲:模型这次返回空"),
                               code="model_output_invalid")
    atomic_write_text(_outline_path(project_root, chapter_n), outline.strip() + "\n")
    progress({"type": "outline_done", "chapter": chapter_n})
    return outline.strip()
