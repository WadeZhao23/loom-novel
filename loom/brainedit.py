"""设定文件的 AI 改写/续写:设定师口径,只生成候选、绝不落盘(落盘走编辑器保存链路,作者确认才算数)。

与 rewrite.py(正文局部重写,写手口径+快照铁律)是并列通道:设定是 what 不是 voice(ADR 0002),
这里不读写作指纹、不涉 .原稿 快照、learn 红线无涉。
rel 守卫住在本模块:只放行 世界观/人物 的设定文件(单文件老书 + 目录新书),
写作指纹/正文/卡章纲/成长档案(learn 的 AI 自留地)一律拒绝——别的文件各有专门通道。
"""

from __future__ import annotations

from pathlib import Path

from .backends import Backend, LoomBackendError
from .config import load_config
from .errors import render
from .guard import STEP, validate_output

_ALLOWED_FILES = ("外置大脑/世界观.md", "外置大脑/人物卡.md")
_ALLOWED_PREFIXES = ("外置大脑/世界观/", "外置大脑/人物/")

_REWRITE_SYSTEM = """你是这本书的设定师。我给你整份设定文件作上下文、作者选中要改写的一段、以及作者的指令。
按指令改写【选中段】,与该文件其余设定、书名自洽,不发明与现有设定冲突的新规则,不动选中段之外的内容。
只输出改写后的那一段本身,保持原有的 Markdown 结构(标题层级/列表符号),不要解释。"""

_CONTINUE_SYSTEM = """你是这本书的设定师。我给你整份设定文件作上下文、以及作者的指令。
按指令在这份设定的末尾【续写】一段新内容,与已有设定、书名自洽,不重复已有条目,不发明冲突设定。
只输出新增内容本身(带合适的 Markdown 小节标题或列表),不要解释。"""


def check_rel(rel: str) -> None:
    r = rel.replace("\\", "/")
    if ".." in r.split("/"):
        raise ValueError("设定文件路径不合法(不允许 .. 段)。")
    if r in _ALLOWED_FILES:
        return
    if r.startswith(_ALLOWED_PREFIXES) and r.endswith(".md") and not r.endswith("成长档案.md"):
        return
    raise ValueError("只有 世界观/人物 的设定文件支持 AI 改写/续写(正文、写作指纹、卡章纲各有专门通道)。")


def _title(project_root: Path) -> str:
    return (load_config(project_root).title or "").strip() or "（未命名）"


def _checked(out: str, what: str) -> str:
    out = out.strip()
    reasons = validate_output(out, STEP)
    if reasons:
        raise LoomBackendError(render("model_output_invalid", detail=f"{what}:" + "；".join(reasons)),
                               code="model_output_invalid")
    return out


def rewrite_section(project_root: Path, rel: str, full_text: str, span: str,
                    instruction: str, backend: Backend) -> str:
    check_rel(rel)   # 防御纵深:端点已先查,这里再查一次(直调本模块的路径也守住)
    if not span.strip():
        raise ValueError("没选中要改写的段落。先在设定里选一段。")
    user = (
        f"## 书名\n《{_title(project_root)}》\n\n"
        f"## 整份设定文件({rel},供自洽,别整份输出)\n{full_text}\n\n"
        f"## 要改写的选中段\n{span}\n\n"
        f"## 作者指令\n{instruction.strip() or '(改得更具体、能落地,别改变原意)'}"
    )
    return _checked(backend.complete(_REWRITE_SYSTEM, user, max_chars=len(span) + 400), "设定改写")


def continue_section(project_root: Path, rel: str, full_text: str,
                     instruction: str, backend: Backend) -> str:
    check_rel(rel)   # 防御纵深:端点已先查,这里再查一次(直调本模块的路径也守住)
    user = (
        f"## 书名\n《{_title(project_root)}》\n\n"
        f"## 整份设定文件({rel},在它末尾续写)\n{full_text}\n\n"
        f"## 作者指令\n{instruction.strip() or '(顺着现有设定,补一节最缺的:如反派动机、地理空白、力量代价)'}"
    )
    return _checked(backend.complete(_CONTINUE_SYSTEM, user, max_chars=700), "设定续写")
