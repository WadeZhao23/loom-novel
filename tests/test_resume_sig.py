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


# ── 续跑 × WYSIWYG 细纲:手改细纲后不许静默沿用旧的(spec §10.3) ────────────
# 真 bug:细纲文件不在大纲师 reads → 不进 sig_v2 → 半截章续跑时大纲师被判「上游未变」
# 跳过,workspace 回填 ledger 里的【旧】细纲,作者手改的那份根本没被读。
# 修法不碰 sig_v2(细纲首跑时尚未落盘,折进签名会让每本书第一次续跑都从大纲师重算),
# 而是给 resume_point 加「本地可编辑产物已陈旧」的判定。

def _outline(project, n=1):
    from loom.agents import _outline_path
    return _outline_path(project, n)


def test_resume_reruns_outliner_when_author_edited_the_outline(project):
    """作者在半截章上手改了细纲 → 写手必须读到【新】细纲,不许沿用 ledger 里的旧的。

    走 run_pipeline 而不是直接调 resume_point:stale_local 回调是在 run_pipeline 里
    按 STEPS 表构造的(WYSIWYG 属工序行为、只住代码侧),直接调 resume_point 测不到真实接线。
    """
    from loom.gates import CRITIC_去AI味, CRITIC_质检
    cfg = _run_once(project)

    p = _outline(project)
    assert p.is_file(), "大纲师首跑应落一份可看可改的细纲"
    NEW = "作者手改后的细纲:分镜一改成雨夜,分镜二矿灯灭,分镜三门被推开。"
    p.write_text(NEW + "\n", encoding="utf-8")

    be = FakeBackend(lambda s, u: "通过" if s in (CRITIC_质检, CRITIC_去AI味) else (_OUT * 3))
    run_pipeline(project, 1, be, cfg, resume=True)

    writer_prompts = [u for s_, u in be.calls if "本章初稿" in u or "本章场景骨头" in u]
    assert writer_prompts, "写手/下游应被重跑,却一次都没调用——细纲改动被静默吞了"
    assert any(NEW in u for _, u in be.calls), \
        "写手拿到的仍是旧细纲:作者手改的那份没进 workspace(spec §10.3 的真 bug)"


def test_resume_still_skips_all_when_outline_only_differs_by_whitespace(project):
    """只差首尾空白不算「改过」——ledger 存的是模型原文、文件存的是 strip 后的,
    不做双向 strip 会每次续跑都误判改动、白重跑写手及下游(烧钱红线)。"""
    cfg = _run_once(project)
    v2, v1 = _mk_upstreams(project, cfg)
    p = _outline(project)
    p.write_text("\n\n" + p.read_text(encoding="utf-8").strip() + "  \n\n", encoding="utf-8")
    assert resume_point(project, 1, v2, v1)[0] == len(PIPELINE), "只差空白不该触发重跑"


def test_resume_skips_all_when_outline_untouched(project):
    """回归护栏:没动细纲就该全跳,别因为新判定引入无条件重跑。"""
    cfg = _run_once(project)
    v2, v1 = _mk_upstreams(project, cfg)
    assert resume_point(project, 1, v2, v1)[0] == len(PIPELINE)
