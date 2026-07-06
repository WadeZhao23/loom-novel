"""S5 签名 v2 的三组专项(评审要求先行):
① 老账本(v1)零重跑且原位升级;② 改 agent 提示词必重跑;③ reads 顺序/末尾换行不重跑。
外加:config(终稿字数)入签——改了必重算。
"""
from __future__ import annotations

import json

from loom import ledger, paths
from loom.agents import PIPELINE, _knowledge_for, _prev_chapter, run_pipeline
from loom.config import load_config
from loom.resume import SIG_PREFIX, resume_point, sig_v1, sig_v2
from tests.conftest import FakeBackend

_OUT = "各棒统一产出,长度足够过 STEP 闸。"


def _run_once(project):
    cfg = load_config(project)
    # 压小目标字数,让短产出过终稿闸
    toml = project / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"章节字数" = 800', '"章节字数" = 120'),
                    encoding="utf-8")
    cfg = load_config(project)
    from loom.gates import CRITIC_去AI味, CRITIC_质检
    be = FakeBackend(lambda s, u: "通过" if s in (CRITIC_质检, CRITIC_去AI味) else (_OUT * 3))
    run_pipeline(project, 1, be, cfg, resume=True)
    return load_config(project)


def _mk_upstreams(project, cfg):
    prev = _prev_chapter(project, 1)
    bits = {"chapter_chars": cfg.chapter_chars, "gate_rounds": cfg.gate_rounds, "title": cfg.title}

    def v2(role, ws):
        from loom.agents import _knowledge_items
        a, items = _knowledge_items(project, 1, role)
        return sig_v2(a.system_prompt, items, ws, prev, bits)

    def v1(role, ws):
        _, knowledge = _knowledge_for(project, 1, role)
        return sig_v1(knowledge, ws, prev)

    return v2, v1


def test_v1_ledger_zero_rerun_and_upgraded_inplace(project):
    cfg = _run_once(project)
    v2, v1 = _mk_upstreams(project, cfg)
    # 把账本降级成 v1 签名(模拟老书):逐工序按 v1 算法改写 upstream_sha
    led = ledger.load_ledger(project, 1)
    ws: list = []
    for role in PIPELINE:
        led["steps"][role]["upstream_sha"] = v1(role, ws)
        ws.append((role, led["steps"][role]["output"]))  # produces 名不影响 v1
    ledger.save_ledger(project, 1, led)

    idx, workspace = resume_point(project, 1, v2, v1)
    assert idx == len(PIPELINE), "老账本必须零重跑(升级日不烧用户一分钱)"
    assert len(workspace) == len(PIPELINE)
    upgraded = ledger.load_ledger(project, 1)
    assert all(str(e["upstream_sha"]).startswith(SIG_PREFIX)
               for e in upgraded["steps"].values()), "命中后必须原位升级为 v2 签名"


def test_prompt_change_forces_rerun(project):
    cfg = _run_once(project)
    v2, v1 = _mk_upstreams(project, cfg)
    idx, _ = resume_point(project, 1, v2, v1)
    assert idx == len(PIPELINE)
    # 改写手的 system prompt(v1 的缺口:根本不入签)→ 必须从写手(下标2)重跑
    wp = project / "agents" / "写手.md"
    wp.write_text(wp.read_text(encoding="utf-8") + "\n多用短句。\n", encoding="utf-8")
    v2b, v1b = _mk_upstreams(project, cfg)
    idx, _ = resume_point(project, 1, v2b, v1b)
    assert idx == PIPELINE.index("写手"), "改提示词必须触发该棒重跑(v1 静默吃旧稿的缺口)"


def test_sig_v2_order_and_trailing_newline_invariant():
    items = [("b.md", "乙\n"), ("a.md", "甲")]
    ws = [("初稿", "正文")]
    s1 = sig_v2("sys", items, ws, "prev", {"chapter_chars": 800})
    s2 = sig_v2("sys", [("a.md", "甲\n\n"), ("b.md", "乙")], ws, "prev", {"chapter_chars": 800})
    assert s1 == s2, "reads 顺序与末尾换行不得影响签名(误全量重跑=白烧钱)"
    # 注入安全:两项拼接歧义必须区分
    sa = sig_v2("sys", [("a.md", "甲乙")], ws, "prev", {})
    sb = sig_v2("sys", [("a.md", "甲"), ("a.md", "乙")], ws, "prev", {})
    assert sa != sb


def test_config_change_forces_rerun(project):
    cfg = _run_once(project)
    v2, v1 = _mk_upstreams(project, cfg)
    assert resume_point(project, 1, v2, v1)[0] == len(PIPELINE)
    toml = project / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"章节字数" = 120', '"章节字数" = 500'),
                    encoding="utf-8")
    cfg2 = load_config(project)
    v2b, v1b = _mk_upstreams(project, cfg2)
    assert resume_point(project, 1, v2b, v1b)[0] == 0, "改终稿字数必须全量重算(v1 缺口)"
