"""创作旅程状态机:领航员访谈的阶段表 + 完成谓词 + 薄游标。

设计(docs/superpowers/specs/2026-07-10-journey-partner-design.md、ADR 0013):
- 出题以文件现状为准,不以问答历史为准;游标可丢弃(坏了当无,谓词重推)。
- 创作产出只落外置大脑 md(单一真相);游标只存不可派生的最少字段。
- 拓扑住代码侧表(同 agents.STEPS 模式),不下放用户可编辑文件。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .backends import LoomBackendError
from .fsutil import atomic_write_text
from .guard import DRAFT_SECTION, validate_output
from .parse import is_substantive, parse_journey_card
from .state import load_state, save_state

_MAX_QUESTIONS = 4   # 每段题数预算(交互从简;代码侧常量,不进 loom.toml)


@dataclass(frozen=True)
class StageSpec:
    key: str                  # 阶段名(面板展示 + 游标键)
    goal: str                 # 出题目标一句话,进领航员 user prompt
    reads: tuple[str, ...]    # 出题上下文(rel;也是缓存卡签名源;目录=读整目录)
    land: str                 # 落盘模式:field | sections | card_lines | seed
    target: str = ""          # field/card_lines 的目标文件;sections 的单文件形态
    target_dir: str = ""      # sections 的目录形态


STAGES: tuple[StageSpec, ...] = (
    StageSpec("立项", "问清这本书的定位:平台/分区/题材/对标意图/为什么选它",
              (paths.PROJECT_CARD_REL,), "field", target=paths.PROJECT_CARD_REL),
    StageSpec("世界观", "问出核心世界观:力量体系、金手指及其代价、关键地理与势力",
              (paths.WORLD_REL, paths.WORLD_DIR_REL), "sections",
              target=paths.WORLD_REL, target_dir=paths.WORLD_DIR_REL),
    StageSpec("人物", "问出主角与关键配角/反派:名字、动机、底牌、软肋",
              (paths.CHARS_REL, paths.CHARS_DIR_REL), "sections",
              target=paths.CHARS_REL, target_dir=paths.CHARS_DIR_REL),
    StageSpec("卡章纲", "问出开局钩子、前 5 章一句话章纲、全书大弧",
              (paths.CARD_REL,), "card_lines", target=paths.CARD_REL),
    StageSpec("voice", "喂 2-3 段你的真实样本让指纹像你(走 seed,不出题)",
              (), "seed"),
)

_CARD_FIELDS = ("分区", "题材", "对标意图", "为什么选它")
_CARD_LINE_RE = re.compile(r"^-\s*第(\d+)章[:：][ \t]*\S", re.M)

_NAME_SEP = ("·", "・", "•")   # 与 agents._NAME_SEP 同一口径:专名册只认带分隔符的「类型·名字」标题
_PROTAG_HEAD_RE = re.compile(r"^##\s*主角\s*[·・•]\s*\S", re.M)
_GATE_STAGES = ("立项", "世界观", "人物", "卡章纲")   # voice 不进门禁


def _all_h2(text: str) -> list[tuple[str, str]]:
    """粗切 (H2标题, 段落体) 列表——救导入立项卡的非标准 H2(如「## 来自:xxx」)。"""
    out: list[tuple[str, str]] = []
    for chunk in re.split(r"^##\s+", text, flags=re.M)[1:]:
        head, _, body = chunk.partition("\n")
        out.append((head.strip(), body))
    return out


def _stage_spec(key: str) -> StageSpec:
    for s in STAGES:
        if s.key == key:
            return s
    raise ValueError(f"未知阶段:{key}")


# ---- 完成谓词(全部文件派生,零存储) ----

def _h2_body(text: str, title: str) -> str:
    m = re.search(rf"^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def _project_card_done(root: Path) -> bool:
    """四格任一实质;或救导入——任一非模板 H2 段有实质(整卡兜底,不误吃模板占位/平台默认行)。"""
    p = root / paths.PROJECT_CARD_REL
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    if any(is_substantive(_h2_body(text, f)) for f in _CARD_FIELDS):
        return True
    return any(is_substantive(body) for head, body in _all_h2(text) if head not in _CARD_FIELDS)


def _protagonist_done(root: Path) -> bool:
    """至少一张「主角·名字」实质卡;只填反派/未命名/占位不算(同专名册口径)。"""
    form = paths.brain_form(root, paths.CHARS_REL, paths.CHARS_DIR_REL)
    if form == "dir":
        return any(f.name != paths.GROWTH_NAME and f.stem.startswith("主角")
                   and any(s in f.stem for s in _NAME_SEP) and "未命名" not in f.stem
                   and is_substantive(f.read_text(encoding="utf-8"))
                   for f in paths.brain_dir_files(root, paths.CHARS_DIR_REL))
    if form == "file":
        p = root / paths.CHARS_REL
        return p.is_file() and bool(_PROTAG_HEAD_RE.search(p.read_text(encoding="utf-8")))
    return False


def _rel_has_content(root: Path, rel: str) -> bool:
    p = root / rel
    if p.is_dir():
        return any(f.name != paths.GROWTH_NAME and is_substantive(f.read_text(encoding="utf-8"))
                   for f in sorted(p.glob("*.md")))
    return p.is_file() and is_substantive(p.read_text(encoding="utf-8"))


def stage_done(root: Path, spec: StageSpec) -> bool:
    if spec.land == "seed":
        return load_state(root).get("fingerprint_source", "default") != "default"
    if spec.land == "field":
        return _project_card_done(root)
    if spec.land == "card_lines":
        p = root / spec.target
        if not p.is_file():
            return False
        text = p.read_text(encoding="utf-8")
        return bool(_CARD_LINE_RE.search(text)) or is_substantive(text)   # 放宽:段落式章纲也算
    if spec.key == "人物":
        return _protagonist_done(root)   # 硬判主角,面板与门禁同口径(只填反派不算过)
    return any(_rel_has_content(root, rel) for rel in spec.reads)


# ---- 薄游标(挂 .loom_state.json 的 journey 键;整键可丢弃) ----

def _journey(st: dict) -> dict:
    j = st.get("journey")
    if not isinstance(j, dict):
        j = {}
    j.setdefault("skips", {})
    j.setdefault("asked", {})   # {stage: 已出题数}
    j.setdefault("card", None)  # 待答卡缓存 {stage,sig,question,options,...}
    j.setdefault("focus", "")   # goto 显式聚焦(空=按顺序派生)
    return j


def journey_state(root: Path) -> dict:
    st = load_state(root)
    j = _journey(st)
    stages = [{"key": s.key, "land": s.land,
               "done": stage_done(root, s),
               "skipped": bool(j["skips"].get(s.key)),
               "asked": int(j["asked"].get(s.key, 0))}
              for s in STAGES]
    open_keys = [x["key"] for x in stages if not x["done"] and not x["skipped"]]
    focusable = [x["key"] for x in stages if not x["skipped"]]   # 回头改压过 done,只避 skip(I1)
    current = j["focus"] if j["focus"] in focusable else ""
    pending = j["card"] or {}
    if not current and pending.get("stage") in open_keys:
        current = pending["stage"]   # 未答的卡钉住本段(哪怕本段预算已满)
    if not current:
        nxt = next((x for x in stages if x["key"] in open_keys and x["asked"] < _MAX_QUESTIONS), None)
        current = nxt["key"] if nxt else ""
    card = j["card"] if (j["card"] and j["card"].get("stage") == current) else None
    return {"stages": stages, "current": current or None, "card": card}


def goto(root: Path, stage: str, *, skip: bool = False) -> dict:
    _stage_spec(stage)   # 未知段名即 ValueError
    if skip and stage in _GATE_STAGES:
        return goto(root, stage, skip=False)   # 门禁段不许跳过,静默降级为「聚焦本段」,不写 skip 标记
    view = journey_state(root)
    if not skip and stage == view["current"]:
        return view   # 已在本段:幂等返回,不作废待答卡、不清预算(防误点重复计费,I2)
    st = load_state(root)
    j = _journey(st)
    if skip:
        j["skips"][stage] = True
        if j["focus"] == stage:
            j["focus"] = ""
    else:
        j["skips"].pop(stage, None)
        j["focus"] = stage
        j["asked"][stage] = 0   # 回头改=重开本段预算
    if j["card"] and j["card"].get("stage") == stage:
        j["card"] = None        # 换段/跳段即作废待答卡
    st["journey"] = j
    save_state(root, st)
    return journey_state(root)


# ---- 领航员(第六个角色;项目文件优先、包内模板回退——同 deconstruct._load_skill 先例) ----

def _navigator_system(root: Path) -> str:
    from .agents import _parse_frontmatter   # 薄别名惯例(同 draft.py 之于 parse.py)
    local = root / "agents" / "领航员.md"
    path = local if local.exists() else Path(__file__).parent / "templates" / "agents" / "领航员.md"
    _, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return body


# ---- 出题 ----

_NAV_MAX_CHARS = 300   # 一张卡的输出预算(短步骤,防思考型模型吃空正文)


def _sig(root: Path, spec: StageSpec) -> str:
    """缓存卡签名 = 阶段源文件全文哈希;文件一动签名即失配 → 重出题(防旧卡问馊问题)。"""
    h = hashlib.sha256()
    for rel in spec.reads:
        p = root / rel
        files = sorted(p.glob("*.md")) if p.is_dir() else ([p] if p.is_file() else [])
        for f in files:
            h.update(f.read_text(encoding="utf-8").encode("utf-8"))
    return h.hexdigest()[:12]


def _stage_context(root: Path, spec: StageSpec) -> str:
    from .agents import _read_files, _noop   # 复用:剥占位、跳空文件、目录展开
    return _read_files(root, list(spec.reads), _noop)


def next_card(root: Path, backend) -> dict:
    view = journey_state(root)
    cur = view["current"]
    if cur is None:
        return {"card": None, "state": view}
    spec = _stage_spec(cur)
    if spec.land == "seed":
        return {"card": {"stage": "voice", "static": "seed"}, "state": view}

    st = load_state(root)
    j = _journey(st)
    sig = _sig(root, spec)
    cached = j["card"]
    if cached and cached.get("stage") == cur and cached.get("sig") == sig and not cached.get("degraded"):
        return {"card": cached, "state": view}   # 降级卡不吃缓存,每次点「下一题」都真重试(I3)

    left = max(0, _MAX_QUESTIONS - int(j["asked"].get(cur, 0)))
    user = (f"阶段:{spec.key}\n目标:{spec.goal}\n这一段还能问 {left} 题。\n\n"
            f"资料现状:\n{_stage_context(root, spec) or '(全部空白)'}")
    parsed = None
    try:
        raw = backend.complete(_navigator_system(root), user, max_chars=_NAV_MAX_CHARS)
        parsed = parse_journey_card(raw)
    except LoomBackendError:
        parsed = None   # 断网/超时 → 降级卡,旅程不卡死

    if parsed and parsed.get("exhausted"):
        if stage_done(root, spec):
            j["skips"][cur] = True   # 真做完了才跳;游标可丢,丢了最多重问一次
            j["card"] = None
            st["journey"] = j
            save_state(root, st)
            return next_card(root, backend) if journey_state(root)["current"] else \
                {"card": None, "state": journey_state(root)}
        parsed = None   # 没做完却报无题 → 模型误判,降级卡兜底,给自由输入出口,别死锁

    if parsed:
        card = {"stage": cur, "sig": sig, "question": parsed["question"],
                "options": parsed["options"]}
        if "field" in parsed:
            card["field"] = parsed["field"]
        j["asked"][cur] = int(j["asked"].get(cur, 0)) + 1   # 只有成卡才烧预算
    else:
        card = {"stage": cur, "sig": sig, "options": [], "degraded": True,
                "question": f"关于「{spec.key}」,你想先定下什么?(出题失败,直接写你的决定)"}
    j["card"] = card
    st["journey"] = j
    save_state(root, st)
    return {"card": card, "state": journey_state(root)}


# ---- 答案落盘(作者拍板过的答案=人写主体;人写优先,答案绝不丢) ----

_DIGEST_SYSTEM = (
    "你是写作伙伴的记录员。把作者对一个创作问题的回答,整理成要落进资料文件的正式文本。\n"
    "红线:只整形作者说的内容,绝不添加作者没说的设定事实;不加客套、不加解释。\n"
    "输出格式严格按任务里的要求。"
)
_DIGEST_MAX_CHARS = 400


def land_answer(root: Path, answer: str, backend) -> dict:
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("答案是空的。")
    st = load_state(root)
    j = _journey(st)
    card = j["card"]
    if not card or "static" in card:
        raise ValueError("没有待答的问题卡,先出题。")
    spec = _stage_spec(card["stage"])
    if spec.land == "field":
        landed = _land_field(root, card.get("field", ""), answer)
    elif spec.land == "sections":
        landed = _land_sections(root, spec, card["question"], answer, backend)
    else:   # card_lines
        landed = _land_card_lines(root, card["question"], answer, backend)
    j["card"] = None
    st["journey"] = j
    save_state(root, st)
    return {"landed": landed, "state": journey_state(root)}


def _replace_h2_body(text: str, title: str, new_body: str) -> str:
    """占位格 → 换成答案;已有人写内容 → 在格尾追加(人写优先);缺格 → 文末补格。"""
    old = _h2_body(text, title)
    if not re.search(rf"^##\s*{re.escape(title)}\s*$", text, flags=re.M):
        return text.rstrip() + f"\n\n## {title}\n{new_body}\n"
    if is_substantive(old):
        replacement = old.rstrip() + f"\n\n{new_body}\n"
    else:
        replacement = f"\n{new_body}\n"
    return re.sub(rf"(^##\s*{re.escape(title)}\s*$).*?(?=^##\s|\Z)",
                  lambda m: m.group(1) + replacement + "\n", text, count=1, flags=re.M | re.S)


def _land_field(root: Path, field: str, answer: str) -> str:
    p = root / paths.PROJECT_CARD_REL
    text = p.read_text(encoding="utf-8") if p.is_file() else "# 立项卡\n"
    if field == "平台":
        # 平台行整行替换是裁量:答题即作者本人拍板换值(区别于 H2 格的人写只追加)
        text, n = re.subn(r"^平台[:：].*$", f"平台:{answer}", text, count=1, flags=re.M)
        if not n:
            text = text.rstrip() + f"\n\n平台:{answer}\n"
    else:
        if field not in _CARD_FIELDS:
            field = "题材"   # 领航员出了怪格名 → 落最通用的格,答案绝不丢
        text = _replace_h2_body(text, field, answer)
    atomic_write_text(p, text)
    return paths.PROJECT_CARD_REL


def _digest(backend, question: str, answer: str, format_ask: str) -> str:
    """一次消化调用;失败或过不了 guard 返回空串(调用方落原答案兜底)。"""
    user = f"问题:{question}\n作者的回答:{answer}\n\n{format_ask}只用作者给的信息。"
    try:
        body = backend.complete(_DIGEST_SYSTEM, user, max_chars=_DIGEST_MAX_CHARS)
    except LoomBackendError:
        return ""
    return "" if validate_output(body, DRAFT_SECTION) else body


_H2_SPLIT_RE = re.compile(r"^(?=## )", re.M)


def _split_h2(body: str) -> list[str]:
    """消化产物 → H2 节列表(每项含「## 标题」头);H2 前导语丢弃,与 _write_sections_into_dir 口径一致。"""
    return [p for p in _H2_SPLIT_RE.split(body) if p.strip().startswith("## ")]


def _fallback_title(question: str) -> str:
    return re.sub(r'[\\/:*?"<>|。,]', "", question)[:12] or "访谈补充"


def _land_sections(root: Path, spec: StageSpec, question: str, answer: str, backend) -> str:
    from .draft import _write_sections_into_dir   # 只写空白/模板文件,人写的一律不碰
    body = _digest(backend, question, answer,
                   "整理成 markdown:每个主题一节,以「## 标题」开头(标题即文件名,如「## 金手指」「## 主角·林潜」),标题下写正文。")
    if not body:
        body = f"## {_fallback_title(question)}\n{answer}"
    segs = _split_h2(body)
    if not segs:   # 消化产物没按格式出 H2 → 整段当一节,绝不丢
        segs = [f"## {_fallback_title(question)}\n{body.strip()}"]
    form = paths.brain_form(root, spec.target, spec.target_dir)
    if form != "file":
        written: list[str] = []
        leftover: list[str] = []
        for seg in segs:   # 逐节落盘:哪节撞上人写成品,哪节进兜底——绝不整批丢
            got = _write_sections_into_dir(root, spec.target_dir, "\n" + seg,
                                           drop_unnamed=(spec.key == "人物"))
            if got:
                written.extend(got)
            else:
                leftover.append(seg.strip())
        rel = f"{spec.target_dir}/访谈补充.md"      # 同名文件已是人写成品 → 兜底追加,绝不覆盖
        if leftover:
            p = root / rel
            old = p.read_text(encoding="utf-8") if p.is_file() else "# 访谈补充\n"
            atomic_write_text(p, old.rstrip() + "\n\n" + "\n\n".join(leftover) + "\n")
        if written:
            return f"{spec.target_dir}/{written[0]}.md"
        return rel
    p = root / spec.target                          # 单文件形态的老书
    old = p.read_text(encoding="utf-8") if p.is_file() else ""
    atomic_write_text(p, (old.rstrip() + "\n\n" if old.strip() else "") + body.strip() + "\n")
    return spec.target


def _bulleted(answer: str) -> str:
    """答案逐行 bullet 化,兜底用(消化异常/过不了 guard 两处同用)。"""
    return "\n".join(f"- {l.strip()}" for l in answer.splitlines() if l.strip())


def _land_card_lines(root: Path, question: str, answer: str, backend) -> str:
    body = _digest(backend, question, answer,
                   "整理成卡章纲行:每行「- 第N章:这章完成什么+章末钩子」;不属于具体某章的规划(如全书大弧),输出「- 大弧:一句话」。")
    if not body:
        body = _bulleted(answer)
    p = root / paths.CARD_REL
    text = p.read_text(encoding="utf-8") if p.is_file() else "# 卡章纲\n"
    landed_any = False   # 消化产物哪怕不合规(散文/漏行),答案也绝不静默丢(C1)
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- ") or line == "-":
            continue
        m = re.match(r"^-\s*第(\d+)章[:：]\s*(.*)$", line)
        if m and m.group(2).strip():
            n, content = m.group(1), m.group(2).strip()
            empty_pat = re.compile(rf"^-\s*第{n}章[:：]\s*$", re.M)
            if empty_pat.search(text):
                text = empty_pat.sub(f"- 第{n}章:{content}", text, count=1)
                landed_any = True
            elif not re.search(rf"^-\s*第{n}章[:：]\s*\S", text, flags=re.M):
                text = text.rstrip() + f"\n- 第{n}章:{content}\n"
                landed_any = True
            # 已有人写内容的章行 → 跳过,绝不覆盖
        elif re.search(rf"^{re.escape(line)}\s*$", text, flags=re.M) is None:
            # 整行精确匹配判重(而非子串):新行是已有行前缀时不再被误吞
            text = text.rstrip() + f"\n{line}\n"
            landed_any = True
    if not landed_any:
        text = text.rstrip() + f"\n{_bulleted(answer)}\n"   # 最后兜底:原答案全量追加,答案绝不丢
    atomic_write_text(p, text)
    return paths.CARD_REL


def writing_unlocked(root: Path) -> tuple[bool, list[str]]:
    """起书完整性:立项+世界观+主角+卡章纲 是否齐;返回 (解锁?, 缺项 STAGES key 列表)。纯文件派生。"""
    missing = [s.key for s in STAGES if s.key in _GATE_STAGES and not stage_done(root, s)]
    return (not missing, missing)
