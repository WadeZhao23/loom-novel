"""S4 golden 三件套:钉死 run_pipeline 的等价面——prompt 逐字节 + 事件序列 + 落盘文件。

用途:STEPS 表化(S4)、签名 v2(S5)、上下文预算器(S6)这类重排主循环的重构,
必须在这份快照下逐字节等价(S6 有意改 prompt 时,重生成快照并人工审 diff——
这正是评审要求的「prompt 回放断言」护栏)。

重新生成快照:LOOM_GOLDEN_WRITE=1 python3 -m pytest tests/test_golden_pipeline.py
(生成后必须人工审 tests/golden/pipeline_v1.json 的 diff 再提交,不许盲刷。)
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from loom.agents import run_pipeline
from loom.config import load_config
from loom.parse import EDIT_NOTE_CLOSE, EDIT_NOTE_OPEN

GOLDEN = Path(__file__).parent / "golden" / "pipeline_v1.json"

# 每棒的固定产出(避开违禁词表与「不是A而是B」翻转句,保证 detector 路径确定性为零命中)
_SETTER = "本章设定锚点:主角沈砚在矿场;境界凡境;金手指为重生记忆。"
_OUTLINE = "分镜一:醒来验伤。分镜二:遇周楠。分镜三:章末钩(危机迫近)。"
_DRAFT = "寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀。"
_EDITED = ("寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀,也记得谁递的刀。\n"
           + EDIT_NOTE_OPEN + "\n《本章改动留痕》\n- 补了一句悬念,钩子更硬。\n" + EDIT_NOTE_CLOSE)
_POLISHED = "寅时三刻,铜锣未响。\n\n沈砚睁开眼,矿灯昏黄。\n\n他记得三年后的那一刀,也记得递刀的人。"
_PASS = "通过"
_TITLE = "矿灯"

_FULL_RUN = [_SETTER, _OUTLINE, _DRAFT, _EDITED, _PASS, _POLISHED, _PASS, _TITLE]


class RecordingBackend:
    """按脚本顺序吐产出;记录每次调用的 (system_sha, user, max_chars)。脚本耗尽即炸=调用数契约。"""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
        if not self.script:
            raise AssertionError("RecordingBackend 脚本耗尽:调用次数超出 golden 契约")
        out = self.script.pop(0)
        self.calls.append({
            "system": hashlib.sha256(system.encode("utf-8")).hexdigest()[:12],
            "user": user, "max_chars": max_chars,
        })
        if on_chunk and out:
            on_chunk(out)
        return out


def _files_snapshot(root: Path) -> dict[str, str]:
    """正文/留痕全量落盘快照;排除 .历史(文件名带时间戳)与回收站。"""
    out: dict[str, str] = {}
    for base in ("正文", ".审稿留痕"):
        d = root / base
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            rel = p.relative_to(root).as_posix()
            if p.is_dir() or "/.历史/" in f"/{rel}/" or "/.回收站/" in f"/{rel}/":
                continue
            out[rel] = p.read_text(encoding="utf-8")
    return out


def test_pipeline_golden(project: Path):
    # 终稿最短闸=目标×12%(地板40):把目标压到 200,让短脚本产出可过闸、快照体积可控
    toml = project / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"章节字数" = 800', '"章节字数" = 200'),
                    encoding="utf-8")
    cfg = load_config(project)
    assert cfg.chapter_chars == 200, "loom.toml 目标字数替换失败(模板措辞变了?)"
    record: dict = {"scenarios": {}}

    def run(name: str, chapter: int, script: list[str], *, resume: bool) -> None:
        be = RecordingBackend(script)
        evs: list[dict] = []
        run_pipeline(project, chapter, be, cfg, progress=evs.append, resume=resume)
        assert not be.script, f"{name}: 脚本剩余 {len(be.script)} 条未消费(调用数少于契约)"
        record["scenarios"][name] = {"calls": be.calls, "events": evs}

    # A 全新首章(黄金开篇 reads,全 5 棒 + 双 critic + 标题 = 8 调)
    run("A_ch1_fresh", 1, list(_FULL_RUN), resume=True)
    # B 续跑全跳(五棒 ledger 均命中,只重起标题 = 1 调)
    run("B_ch1_resume_all_skip", 1, [_TITLE], resume=True)
    # C 第二章(prev 注入大纲师/写手)
    run("C_ch2_with_prev", 2, list(_FULL_RUN), resume=True)
    # D 细纲 WYSIWYG 旁路(手写细纲已存在 → 大纲师不调模型,7 调)
    from loom import paths as _paths
    outline3 = _paths.outline_path(project, 3)
    outline3.parent.mkdir(parents=True, exist_ok=True)
    outline3.write_text("手改细纲:只留两场,末场倒计时钩。\n", encoding="utf-8")
    run("D_ch3_outline_bypass", 3,
        [_SETTER, _DRAFT, _EDITED, _PASS, _POLISHED, _PASS, _TITLE], resume=False)

    record["files"] = _files_snapshot(project)

    # 归一化:事件里的绝对路径(edit_note/chapter_done 的 path 字段)按项目根替换,快照才可复现
    blob = json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True).replace(str(project), "<ROOT>")

    if os.environ.get("LOOM_GOLDEN_WRITE") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(blob, encoding="utf-8")
        return

    assert GOLDEN.is_file(), "缺 golden 快照:LOOM_GOLDEN_WRITE=1 生成并人工审后提交"
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    got = json.loads(blob)
    for sc in want["scenarios"]:
        w, g = want["scenarios"][sc], got["scenarios"].get(sc)
        assert g is not None, f"场景缺失:{sc}"
        assert len(g["calls"]) == len(w["calls"]), f"{sc}: 调用数 {len(g['calls'])} != {len(w['calls'])}"
        for i, (wc, gc) in enumerate(zip(w["calls"], g["calls"])):
            assert gc == wc, (f"{sc} 第{i}次调用不等价\nmax_chars: {gc['max_chars']} vs {wc['max_chars']}\n"
                              f"system_sha: {gc['system']} vs {wc['system']}\n"
                              f"user diff 首异位置: {_first_diff(gc['user'], wc['user'])}")
        assert g["events"] == w["events"], f"{sc}: 事件序列不等价"
    assert got["files"] == want["files"], "落盘文件不等价"


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"offset {i}: ...{a[max(0, i - 40):i + 40]!r}... vs ...{b[max(0, i - 40):i + 40]!r}..."
    return f"长度不同 {len(a)} vs {len(b)}(前缀相同)"
