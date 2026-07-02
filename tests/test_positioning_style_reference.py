"""3.0.0 三条通道回归:立项卡(定位/基线松紧)、文风参考(写手·阀②·护栏)、seed --参考(起点指纹)。

红线:立项卡只进设定师、文风参考只进写手且绝不进 learn/其余棒;违禁词基线粗粒度二档、缺卡不崩;
learn 学习信号唯一是你的手改,fingerprint_source='reference' 不改这一点。
"""
from __future__ import annotations

from pathlib import Path

from loom.agents import load_agent
from loom.doctor import BRAIN_FILES, OPTIONAL_BRAIN, report, run_checks
from loom.scaffold import TEMPLATES_DIR
from loom.sensitive import load_words

from conftest import FakeBackend, const

TPL_BRAIN = TEMPLATES_DIR / "外置大脑"


# ── scaffold:两份可选卡随 init 拷进项目,内容与模板逐字一致(init 从不回写)──────────

def test_scaffold_ships_positioning_and_style_reference_verbatim(project: Path):
    for name in ("立项卡.md", "文风参考.md"):
        shipped = project / "外置大脑" / name
        assert shipped.is_file(), f"init 没拷 外置大脑/{name}"
        assert shipped.read_text(encoding="utf-8") == (TPL_BRAIN / name).read_text(encoding="utf-8"), \
            f"外置大脑/{name} 被 init 改写了(应逐字等于模板)"


# ── agents reads:立项卡只进设定师、文风参考只进写手 ─────────────────────────────

def test_setupper_reads_positioning_card(project: Path):
    a = load_agent(project, "设定师")
    assert "外置大脑/立项卡.md" in a.reads
    assert "外置大脑/文风参考.md" not in a.reads      # 红线:文风参考绝不进设定师


def test_writer_reads_style_reference(project: Path):
    a = load_agent(project, "写手")
    assert "外置大脑/文风参考.md" in a.reads
    assert "外置大脑/立项卡.md" not in a.reads         # 红线:立项卡绝不进写手


def test_positioning_and_style_reference_not_read_by_other_roles(project: Path):
    for role in ("大纲师", "编辑", "润色师"):
        reads = load_agent(project, role).reads
        assert "外置大脑/文风参考.md" not in reads, f"{role} 不该读文风参考"
        assert "外置大脑/立项卡.md" not in reads, f"{role} 不该读立项卡"


def test_writer_prompt_body_carries_valve2_and_guardrail(project: Path):
    body = load_agent(project, "写手").system_prompt
    assert "指纹压范文" in body                          # 阀②
    assert "护栏" in body and "整句原文" in body          # 护栏(专名/原句)


def test_agent_load_survives_missing_positioning_card(project: Path):
    # 手删两份可选卡:load_agent 只解析 frontmatter,不该因文件缺失崩(reads 声明仍在,读时才跳过)
    (project / "外置大脑" / "立项卡.md").unlink()
    (project / "外置大脑" / "文风参考.md").unlink()
    assert "外置大脑/立项卡.md" in load_agent(project, "设定师").reads
    assert "外置大脑/文风参考.md" in load_agent(project, "写手").reads


# ── sensitive:立项卡平台字段 → 基线粗粒度二档(严/默认),缺卡/坏卡兜底 ─────────────

_STRICT_WORD = "傻逼"   # 只在严格档额外并入


def _clear_forbidden(project: Path) -> None:
    """删掉项目自带的 违禁词.md,逼 load_words 走内置基线(才能验立项卡定的松紧)。"""
    p = project / "外置大脑" / "违禁词.md"
    if p.exists():
        p.unlink()


def test_baseline_default_when_no_card(project: Path):
    _clear_forbidden(project)
    (project / "外置大脑" / "立项卡.md").unlink()          # 无卡 → 默认档
    words = load_words(project)
    assert "自杀" in words                                # 默认基线仍在
    assert _STRICT_WORD not in words                      # 未叠严格档


def test_baseline_strict_when_platform_qidian(project: Path):
    _clear_forbidden(project)
    (project / "外置大脑" / "立项卡.md").write_text(
        "# 立项卡\n\n平台:起点\n\n## 分区\n玄幻\n", encoding="utf-8")
    words = load_words(project)
    assert "自杀" in words                                # 默认基线仍在
    assert _STRICT_WORD in words                          # 起点 → 叠严格档


def test_baseline_strict_when_platform_fanqie(project: Path):
    _clear_forbidden(project)
    (project / "外置大脑" / "立项卡.md").write_text(
        "# 立项卡\n\n平台:番茄\n", encoding="utf-8")
    assert _STRICT_WORD in load_words(project)            # 番茄也算严格档


def test_baseline_default_for_other_platform(project: Path):
    _clear_forbidden(project)
    (project / "外置大脑" / "立项卡.md").write_text(
        "# 立项卡\n\n平台:晋江\n", encoding="utf-8")
    assert _STRICT_WORD not in load_words(project)        # 非起点/番茄 → 不叠严格档


def test_baseline_falls_back_gracefully_on_malformed_card(project: Path):
    _clear_forbidden(project)
    # 卡里没有「平台:」行、纯乱内容 → 不该抛错,走默认档
    (project / "外置大脑" / "立项卡.md").write_text("乱七八糟\n没有平台行\n###", encoding="utf-8")
    words = load_words(project)
    assert "自杀" in words and _STRICT_WORD not in words


def test_baseline_no_crash_when_card_is_directory(project: Path):
    _clear_forbidden(project)
    card = project / "外置大脑" / "立项卡.md"
    card.unlink()
    card.mkdir()                                          # 误建成目录 → 兜底 False、不崩
    assert "自杀" in load_words(project) and _STRICT_WORD not in load_words(project)


# ── doctor:四件套仍强制,两份可选卡有无都 ok、绝不阻断 ─────────────────────────────

def test_doctor_brain_files_still_four():
    assert BRAIN_FILES == ["世界观", "人物卡", "卡章纲", "写作指纹"]
    assert "立项卡" in OPTIONAL_BRAIN and "文风参考" in OPTIONAL_BRAIN


def test_doctor_ok_unaffected_by_optional_card_presence(project: Path):
    # 有卡时:可选检查项全 ok=True
    checks_with = run_checks(project)
    assert all(c.ok for c in checks_with if "(可选)" in c.name)
    # 删掉两份可选卡:可选检查项照样 ok=True(present-or-absent 都 ok)
    (project / "外置大脑" / "立项卡.md").unlink()
    (project / "外置大脑" / "文风参考.md").unlink()
    checks_without = run_checks(project)
    optional = [c for c in checks_without if "(可选)" in c.name]
    assert optional and all(c.ok for c in optional)
    # 四件套强制项的裁决没被可选卡改变
    mandatory = [c for c in checks_without if c.name.startswith("外置大脑 · ") and "(可选)" not in c.name]
    assert all(c.ok for c in mandatory)


# ── seed --参考:蒸出起点指纹、source=reference,且 learn 仍只学手改 ─────────────────

def _fp(project: Path) -> Path:
    return project / "外置大脑" / "写作指纹.md"


def test_seed_from_reference_writes_fingerprint_and_marks_source(project: Path):
    from loom.fingerprint import seed_from_reference
    from loom.state import load_state

    good_fp = "# 写作指纹\n\n## 句式偏好\n- 爱用短句\n\n## anchor 例句\n> 他没回头。\n"
    be = FakeBackend(const(good_fp))
    seed_from_reference(project, "别人写的一段范文，短句、克制。", be)
    assert "爱用短句" in _fp(project).read_text(encoding="utf-8")
    assert load_state(project).get("fingerprint_source") == "reference"


def test_seed_from_reference_prompt_wording(project: Path):
    from loom.fingerprint import seed_from_reference

    be = FakeBackend(const(
        "# 写作指纹\n\n## 句式偏好\n- 爱用短句、单句成段、少关联词\n\n"
        "## anchor 例句\n> 他没回头，雨一直下。\n"))
    seed_from_reference(project, "范文内容", be)
    _, user = be.calls[-1]
    assert "我欣赏的作者的原文范文" in user and "起点" in user


def test_seed_from_reference_rejects_empty(project: Path):
    from loom.backends import LoomBackendError
    from loom.fingerprint import seed_from_reference

    be = FakeBackend(const("whatever"))
    try:
        seed_from_reference(project, "   ", be)
        assert False, "空范文应报错"
    except LoomBackendError:
        pass


def test_learn_unaffected_by_reference_fingerprint_source(project: Path):
    """fingerprint_source='reference' 时,learn 仍只从 .原稿 vs 手改学(阀①不变)。"""
    from loom.fingerprint import learn
    from loom.state import set_fingerprint_source

    set_fingerprint_source(project, "reference")   # 模拟种子来自别人范文
    body = project / "正文"
    (body / ".原稿").mkdir(parents=True, exist_ok=True)
    snap = "他站在雨里，很久。" * 20
    edited = "他杵在雨里，站了很久。" * 20          # 手改过
    (body / "第1章.md").write_text(edited, encoding="utf-8")
    (body / ".原稿" / "第1章.md").write_text(snap, encoding="utf-8")

    captured: dict = {}

    def responder(system, user):
        captured["user"] = user
        return "# 写作指纹\n\n## 句式偏好\n- 学到了新东西\n\n## anchor 例句\n> 他杵在雨里。\n"

    learn(project, 1, FakeBackend(responder))
    # learn 的信号里带的是【你的手改】对齐,而不是范文来源
    assert "杵在雨里" in captured["user"]           # 手改进了 diff 信号
    assert "reference" not in captured["user"]       # 来源标记没混进学习信号
