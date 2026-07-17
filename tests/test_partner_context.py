import hashlib
from loom.partner_context import assemble, env_snapshot


def _sha(s): return hashlib.sha256(s.encode()).hexdigest()[:12]


def test_prefix_stable_when_files_unchanged(project):
    s1, _ = assemble(project, [])
    s2, _ = assemble(project, [{"t": "user", "text": "hi", "ts": "x"}])
    assert _sha(s1) == _sha(s2)      # 对话尾变,前缀不变


def test_prefix_changes_when_persona_edited(project):
    s1, _ = assemble(project, [])
    p = project / "agents/领航员.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n补一句人设\n", encoding="utf-8")
    s2, _ = assemble(project, [])
    assert _sha(s1) != _sha(s2)      # 人设改了前缀变(立即生效)


def test_env_snapshot_has_gate_and_bounded(project):
    snap = env_snapshot(project)
    assert "立项" in snap and "未填" in snap
    assert len(snap) <= 500          # ≤400字硬约束留余量


def test_body_change_only_touches_suffix(project):
    s1, u1 = assemble(project, [])
    (project / "外置大脑/世界观/金手指.md").write_text("# 金手指\n\n吞噬万物\n", encoding="utf-8")
    s2, u2 = assemble(project, [])
    assert _sha(s1) == _sha(s2)      # 前缀不含正文/外置大脑明细


def test_snapshot_current_stage_unfilled_slots_carry_hint(project):
    # 当前工作段(新书=立项)未填槽带 hint,让模型知道每格含义;预算仍守 400 字,门禁信息不丢
    snap = env_snapshot(project)
    assert "分区" in snap
    assert "不是平台" in snap        # 分区 hint 的关键字眼透出来了
    assert len(snap) <= 400
    assert "门禁" in snap or "未填" in snap


def test_snapshot_keeps_gate_even_with_long_idea(project):
    from loom.config import load_config, save_config
    cfg = load_config(project); cfg.idea = "设" * 450; save_config(project, cfg)
    snap = env_snapshot(project)
    assert len(snap) <= 400
    assert "门禁" in snap or "未填" in snap or "立项" in snap   # 门禁信息没被长idea挤没
