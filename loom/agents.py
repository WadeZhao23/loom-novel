"""Agent 链:按顺序跑 5 个工序,累积一个"本章工作区",每步读到目前为止的全部产物。

Agent 的系统提示词写在 agents/<角色>.md 里(顶部 YAML 声明 reads),不硬编码进这里。
引擎不依赖任何前端:进度通过 progress(event: dict) 回调发出,CLI / 桌面端各自渲染。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .backends import Backend
from .config import Config

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note + "\n", encoding="utf-8")
    progress({"type": "edit_note", "chapter": chapter_n, "path": str(path)})


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
    """读上一章【手改后的】正文做行文衔接(不是 .原稿 快照)。"""
    if chapter_n <= 1:
        return ""
    p = project_root / "正文" / f"第{chapter_n - 1}章.md"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def run_pipeline(
    project_root: Path,
    chapter_n: int,
    backend: Backend,
    config: Config,
    progress: Progress = _noop,
    *,
    slow: float = 0.0,
    resume: bool = True,
) -> tuple[Path, str]:
    """跑一章。返回 (终稿路径, 终稿文本)。进度通过 progress 回调发出。

    resume=True 时跳过 ledger 里"已完成且上游未变"的工序(断点续跑,省 DeepSeek 计费);
    上游(reads 文件 / 已累积产物 / 上一章正文)任一变化,从该工序起重算。
    """
    from . import ledger

    progress({"type": "pipeline_start", "chapter": chapter_n, "roles": PIPELINE})
    prev = _prev_chapter(project_root, chapter_n)

    def _knowledge_for(role: str) -> tuple[Agent, str]:
        a = load_agent(project_root, role)
        rels = list(a.reads) + (a.reads_first_chapter if chapter_n == 1 else [])
        return a, _read_files(project_root, rels, _noop)

    def _sig(knowledge: str, ws: list[tuple[str, str]]) -> str:
        return ledger.sha(knowledge + "\x1f" + "\n".join(t for _, t in ws) + "\x1f" + prev)

    def _upstream_of(role: str, ws: list[tuple[str, str]]) -> str:
        _, knowledge = _knowledge_for(role)
        return _sig(knowledge, ws)

    if resume:
        start_idx, workspace = ledger.resume_point(project_root, chapter_n, _upstream_of)
        for role in PIPELINE[:start_idx]:
            progress({"type": "agent_skip", "role": role, "reason": "已完成且上游未变"})
    else:
        start_idx, workspace = 0, []

    for role in PIPELINE[start_idx:]:
        agent, knowledge = _knowledge_for(role)
        progress({"type": "agent_start", "role": role})
        up_sha = _sig(knowledge, workspace)  # 记录入此工序时的上游签名(供下次续跑比对)

        parts = [f"# 你要写的是第 {chapter_n} 章。"]
        if knowledge:
            parts.append("## 你要遵循的设定/方法论\n" + knowledge)
        if prev and role in ("大纲师", "写手"):
            parts.append("## 上一章正文(接住它的结尾钩子,别重复、别断裂)\n" + prev[-1500:])
        if workspace:
            ctx = "\n\n".join(f"### {label}\n{text}" for label, text in workspace)
            parts.append("## 本章工作区(上游工序已产出,基于它继续)\n" + ctx)
        parts.append(f"## 你的任务\n产出【{agent.produces}】。只输出这一项,不要解释你在做什么。")

        max_chars = _SHORT.get(role, config.chapter_chars)
        output = backend.complete(
            agent.system_prompt, "\n\n".join(parts), max_chars=max_chars,
            on_chunk=lambda d, r=role: progress({"type": "agent_chunk", "role": r, "delta": d}),
        )
        if role == "编辑":
            output, note = _split_edit_note(output)  # 留痕切出,只把干净正文交给下游润色师
            if note:
                _save_edit_note(project_root, chapter_n, note, progress)
        ledger.record_step(project_root, chapter_n, role, output, up_sha)  # 即时落盘=断点可续
        workspace.append((agent.produces, output))
        progress({"type": "agent_done", "role": role, "produces": agent.produces})
        if slow:
            time.sleep(slow)

    final = _strip_edit_note(workspace[-1][1])  # 兜底:终稿/快照绝不含留痕哨兵
    path = _save_chapter(project_root, chapter_n, final)
    ledger.record_snapshot(project_root, chapter_n, final)
    progress({
        "type": "chapter_done",
        "chapter": chapter_n,
        "path": str(path),
        "chars": len(final),
        "preview": final[:300],
        "text": final,
    })
    return path, final


def _save_chapter(project_root: Path, chapter_n: int, final: str) -> Path:
    out = project_root / "正文" / f"第{chapter_n}章.md"
    snap = project_root / "正文" / ".原稿" / f"第{chapter_n}章.md"
    snap.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(final + "\n", encoding="utf-8")
    snap.write_text(final + "\n", encoding="utf-8")  # AI 原稿快照,只给 learn 做 diff
    return out
