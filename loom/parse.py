"""prompt↔解析器 共置面:模型输出的读侧解析收拢在此(S7)。

每个解析器上方的注释贴着对应 prompt 的输出格式约定——改 prompt 格式时解析器就在手边,
两侧一起改,不再散落 7 个文件各自漂移。原模块保留薄别名(from .parse import x),
既有 import 面(含 evalapi 门面、tests)不变。

索引(prompt → 解析器):
- gates.CRITIC_质检 / CRITIC_去AI味      → parse_verdict
- agents._TITLE_SYSTEM                  → clean_title
- agents/编辑.md(编辑留痕围栏/旧哨兵)   → split_edit_note / strip_edit_note
- recap._RECAP_SYSTEM                   → format_recap_block
- enrich._ENRICH_SYSTEM                 → parse_enrich_sections
- draft._DRAFT_SYSTEM                   → split_brain_draft
- fingerprint(anchor 例句段)的读侧在 aitell.load_anchors(挂名于此,不搬——它同时服务检测器)
"""

from __future__ import annotations

import re

# ── 编辑留痕围栏(agents/编辑.md + skills/评估自检.md 约定) ──────────────────
# prompt 约定(新契约):第一段干净正文;留痕用成对标签围起——
#   <LOOM:EDIT-NOTE>\n《本章改动留痕》…\n</LOOM:EDIT-NOTE>
# 读侧永久兼容三态:成对围栏(可校验闭合)/ 旧单点哨兵(老项目模板还在用)/ 无标记。
EDIT_NOTE_OPEN = "<LOOM:EDIT-NOTE>"
EDIT_NOTE_CLOSE = "</LOOM:EDIT-NOTE>"
EDIT_NOTE_SENTINEL = "<!--LOOM:EDIT-NOTE-->"   # 旧单点哨兵,读侧永不下线
EDIT_NOTE_MARKS = (EDIT_NOTE_OPEN, EDIT_NOTE_SENTINEL)   # 两种开标记(流式过滤同用)
EDIT_NOTE_UNCLOSED = "(围栏未闭合:以下按开标签后全部内容截取,可能混入非留痕)"


def split_edit_note(text: str) -> tuple[str, str]:
    """按留痕标记首次出现切分 →(干净正文 body, 留痕 note)。无标记则 (text, "")。

    三态:① 成对围栏:note=标签之间,闭合标签之后的尾巴丢弃(围栏的意义就是可校验);
    未闭合 → 取开标签后全部,并在留痕头部标注「围栏未闭合」。② 旧单点哨兵:哨兵后全部是
    note(原语义)。③ 无标记:全文是正文。两种开标记都在时按先出现者切。
    """
    i_new, i_old = text.find(EDIT_NOTE_OPEN), text.find(EDIT_NOTE_SENTINEL)
    if i_new == -1 and i_old == -1:
        return text, ""
    if i_old != -1 and (i_new == -1 or i_old < i_new):
        return text[:i_old].rstrip(), text[i_old + len(EDIT_NOTE_SENTINEL):].strip()
    body = text[:i_new].rstrip()
    rest = text[i_new + len(EDIT_NOTE_OPEN):]
    j = rest.find(EDIT_NOTE_CLOSE)
    if j == -1:
        note = rest.strip()
        return body, (EDIT_NOTE_UNCLOSED + "\n" + note).strip() if note else EDIT_NOTE_UNCLOSED
    return body, rest[:j].strip()


def strip_edit_note(text: str) -> str:
    """落盘前兜底:只保留标记前的干净正文(保护 learn 的 diff 源不被留痕污染)。"""
    return split_edit_note(text)[0] if any(m in text for m in EDIT_NOTE_MARKS) else text


# ── 复审员判词(gates.CRITIC_质检 / CRITIC_去AI味) ──────────────────────────
# prompt 约定:无硬伤只回一行「通过」;有则每条一行 `- 类别 | 一句话问题 | 证据:"原文短引"`。

# 复审员表示"没问题"的措辞:裸行回「通过」最常见,但偶尔会带 - 项目符号或句号。
# 命中即跳过,别把它当成一条硬伤而触发无谓回炉(质检/去AI味 共用此解析)。
_PASS_PHRASES = frozenset({"无硬伤", "通过", "无问题", "没问题", "没有硬伤", "无命中", "没有问题"})


def parse_verdict(raw: str) -> list:
    """解析复审员输出 → 硬伤清单(list[gates.Issue])。无硬伤(回「通过」等)返回空列表。

    宽容解析:每条形如 `- 类别 | 问题 | 证据:"…"`;只认以 - 开头的行。
    """
    from .gates import Issue   # 延迟 import:gates 模块级 import 本模块,避免环
    issues: list = []
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith(("-", "·", "•")):
            continue
        body = s.lstrip("-·• ").strip()
        if not body or body.rstrip("。.!！,，、;； \t") in _PASS_PHRASES:
            continue
        parts = [p.strip() for p in body.split("|")]
        kind = parts[0] if parts else "硬伤"
        desc = parts[1] if len(parts) > 1 else (parts[0] if parts else body)
        ev = ""
        if len(parts) > 2:
            ev = parts[2].split("证据:", 1)[-1].split("证据：", 1)[-1].strip().strip('"“”')
        issues.append(Issue(kind=kind, desc=desc, evidence=ev))
    return issues


# ── 章节标题(agents._TITLE_SYSTEM) ────────────────────────────────────────
# prompt 约定:只输出标题本身这一行;不带「第N章」章号、不带书名号/引号/星号包裹。


def clean_title(raw: str) -> str:
    """把模型返回收成一个干净标题:取首行、去包裹、去「第N章」前缀;太长/太短/像句子就当没有。"""
    if not raw or not raw.strip():
        return ""
    t = raw.strip().splitlines()[0].strip().lstrip("#").strip()
    t = t.strip("「」『』“”‘’《》<>#*`： ").strip()
    t = re.sub(r"^第\s*[0-9一二三四五六七八九十百零]+\s*章[:：、.\s]*", "", t).strip()
    return t if 1 < len(t) <= 24 else ""   # 太长多半是模型答非所问吐了一段话 → 回退无标题


# ── 写后摘要(recap._RECAP_SYSTEM) ─────────────────────────────────────────
# prompt 约定:两段——`摘要:<≤150字>` + `伏笔:`(下挂 `- [埋设/推进/回收] …` 行,没有则 `- 无`)。

_RECAP_MARK = "[AI回顾]"   # 物理隔离标记(recap 写侧同用,单一真相在这)


def format_recap_block(n: int, raw: str) -> str:
    # 把 LLM 两段输出折成卡章纲下的缩进子块;截断摘要 ≤150 字硬保险
    text = raw.strip()
    m = re.search(r"摘要[:：]\s*(.+?)(?=\n伏笔|$)", text, re.DOTALL)
    summary = (m.group(1).strip() if m else text)[:150]
    fm = re.search(r"伏笔[:：]?\s*\n(.+)$", text, re.DOTALL)
    fore = fm.group(1).strip() if fm else "- 无"
    foreshadow = "\n".join("    " + l.strip() for l in fore.splitlines() if l.strip())
    return (f"  - {_RECAP_MARK} 摘要:{summary}\n"
            f"    伏笔:\n{foreshadow}")


# ── 外置大脑生长(enrich._ENRICH_SYSTEM) ───────────────────────────────────
# prompt 约定:两段——`【世界观补充】` + `【人物卡补充】`,各段下是 `- ` 条目行,没有则 `- 无`。


def _clean_section(body: str) -> str:
    """只留 `- ` 条目行,滤掉「无」占位与空行;返回干净的多行块(可能为空串)。"""
    keep: list[str] = []
    for raw in body.splitlines():
        s = raw.strip()
        if not s.startswith(("-", "•", "・")):
            continue
        inner = s.lstrip("-•・ ").strip()
        if not inner or inner in ("无", "无。", "(无)", "(无)"):
            continue
        keep.append("- " + inner)
    return "\n".join(keep)


def parse_enrich_sections(raw: str) -> tuple[str, str]:
    """把 LLM 两段输出拆成 (世界观补充, 人物卡补充);各自已清洗,空段返回空串。"""
    text = raw.strip()
    wm = re.search(r"【世界观补充】\s*(.*?)(?=【人物卡补充】|$)", text, re.DOTALL)
    cm = re.search(r"【人物卡补充】\s*(.*)$", text, re.DOTALL)
    world = _clean_section(wm.group(1)) if wm else ""
    chars = _clean_section(cm.group(1)) if cm else ""
    return world, chars


# ── 外置大脑三件套起草(draft._DRAFT_SYSTEM) ────────────────────────────────
# prompt 约定:三段用 `===世界观=== / ===人物卡=== / ===卡章纲===` 分隔标记隔开。


def split_brain_draft(raw: str) -> dict:
    out: dict = {}
    for key in ("世界观", "人物卡", "卡章纲"):
        m = re.search(rf"==={key}===\s*(.*?)(?=\n===|\Z)", raw, re.DOTALL)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()
    return out


# ── 占位模板判定(立项即铺底):出厂模板里「写给作者的填写说明」──────────────────
# draft 写侧防覆盖(_is_blank_or_template)与 knowledge 读侧过滤共用这份标记,保证同一语义。
PLACEHOLDER_MARKS = ("占位示例", "待 seed", "待填充")

# 提示行=整行被（）/() 括起且含占位标记;正文里顺嘴提到标记词的句子不算,不许误剥。
_HINT_LINE_RE = re.compile(
    r"^\s*[（(].*(?:" + "|".join(PLACEHOLDER_MARKS) + r").*[)）]\s*$")
# 空表单行:「- 第N章:」「- 体系名称:」等冒号后没内容的骨架行(出厂模板的填写格),不算实质内容
_EMPTY_ROW_RE = re.compile(r"^-\s*[^:：]{0,40}[:：]\s*$")
# 行内括号注释段(全角/半角):表单行的说明文字,判「空表单行」前先剥掉——
# 「- 金手指(类型/…;短板:资源):」剥完是「- 金手指:」,和空章行同类
_PAREN_SPAN_RE = re.compile(r"（[^（）]*）|\([^()]*\)")


def strip_placeholder_hints(text: str) -> str:
    """剥掉占位提示行。真内容与提示混排的文件(如立项卡的平台行 + 各格括注)只丢提示、留内容
    ——不能按「文件含标记」整份误杀。"""
    return "\n".join(l for l in text.splitlines() if not _HINT_LINE_RE.match(l))


def is_substantive(text: str) -> bool:
    """剥占位提示后还有没有实质内容。标题/引用注释/空章行不算——出厂模板剥完只剩这些,
    不该冒充设定进 prompt(读侧过滤与 brain_ready 判定共用)。"""
    for line in strip_placeholder_hints(text).splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">"):
            continue
        if _EMPTY_ROW_RE.match(_PAREN_SPAN_RE.sub("", s)):
            continue
        return True
    return False
