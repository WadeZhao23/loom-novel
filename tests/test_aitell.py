"""AI 腔对比句式检测器:抓高精度 AI 翻转句,豁免作者签名句,默认不碰跨句号的作者声音。"""
from __future__ import annotations

from pathlib import Path

from loom import gates
from loom.aitell import detect, load_anchors
from loom.gates import Issue
from tests.conftest import FakeBackend, const


def _ev(issues: list[Issue]) -> list[str]:
    return [i.evidence for i in issues]


# ── 该报的高精度 AI 形态 ──────────────────────────────────────────────────

def test_flags_ershi():
    # 紧贴「而是」
    hits = detect("这不是结束,而是另一个开始。")
    assert len(hits) == 1
    assert hits[0].kind == "AI腔·对比句式"
    assert "而是" in hits[0].evidence


def test_flags_comma_shi():
    # 软分隔后的「,是」
    hits = detect("它不是巧合,是有人安排好的。")
    assert len(hits) == 1


def test_flags_compact_same_clause():
    # 同句无分隔「不是A是B」
    hits = detect("他要的不是钱是命。")
    assert len(hits) == 1


# ── 不该报的误报类 ────────────────────────────────────────────────────────

def test_skips_shi_bu_shi_question():
    assert detect("他是不是早就知道了?") == []


def test_skips_either_or():
    # 「不是A就是B / 也是B」里的「是」是连词
    assert detect("结果不是赢就是输,没有中间。") == []
    assert detect("他不是蠢也是装的吧。") == []


def test_skips_tag_particle():
    # 「…,是吗」反问尾巴
    assert detect("你不是早走了,是吗?") == []


# ── 跨句号的「。是」= 作者声音,默认不报;显式开 cross_sentence 才报 ──────────

def test_cross_sentence_off_by_default():
    # 句号切断的并列否定是作者写法(逗号并排才是 AI),默认不报
    assert detect("那不是怕。是懒得动。") == []


def test_cross_sentence_opt_in():
    hits = detect("那不是怕。是懒得动。", cross_sentence=True)
    assert len(hits) == 1


# ── 指纹 anchor 豁免:作者逐字签名句,即便形态像 AI 也不报 ────────────────────

def test_anchor_suppresses_verbatim_signature():
    anchors = ["不是忍。是不在意。不是不疼。疼也不值一个表情。"]
    # 开 cross_sentence 本会命中,但它是作者签名句 → 豁免
    assert detect("不是忍。是不在意。", anchors, cross_sentence=True) == []


def test_anchor_does_not_overreach():
    # 别的 AI 翻转句不在 anchor 里,照报不误
    anchors = ["那不是笑。"]
    hits = detect("这不是退让,而是策略。", anchors)
    assert len(hits) == 1


# ── 解析:从写作指纹.md 取 anchor 例句 ──────────────────────────────────────

def test_load_anchors_reads_signature_section(project: Path):
    # scaffold 铺的是中性默认指纹;手写一份带 anchor 段的覆盖它来测解析
    fp = project / "外置大脑" / "写作指纹.md"
    fp.write_text(
        "# 写作指纹\n\n> 顶部引言不算 anchor。\n\n"
        "## 口头禅\n- 「他」反复作主语\n\n"
        "## anchor 例句(逐字保留)\n"
        "> 他没抬头。\n>\n> 那不是笑。\n",
        encoding="utf-8",
    )
    anchors = load_anchors(project)
    assert "他没抬头。" in anchors
    assert "那不是笑。" in anchors
    assert "顶部引言不算 anchor。" not in anchors  # 只取 anchor 段,不混顶部引言


def test_load_anchors_missing_file_is_empty(tmp_path: Path):
    assert load_anchors(tmp_path) == []


# ── 体量与去重 ────────────────────────────────────────────────────────────

def test_dedupe_and_cap():
    # 同一翻转句重复多次 → 去重成一条
    hits = detect("不是A,而是B。" * 3)
    assert len(hits) == 1


# ── 与「去AI味」关卡合流:确定性命中即便 LLM 回「通过」也进残留留痕(rounds=1) ──

def test_gate_merges_detector_when_llm_passes():
    backend = FakeBackend(const("通过"))  # LLM 复审说没问题
    det = lambda text: detect("它不是偶然,而是必然。")  # 确定性检测器命中一条
    res = gates.run_gate(
        backend, label="去AI味", owner_role="润色师",
        critic_system="x", revise_system="y", draft="它不是偶然,而是必然。",
        knowledge="", produces="本章终稿", rounds=1, max_chars=2000, detector=det,
    )
    # rounds=1 只诊断:不回炉、不阻断,但确定性硬伤进 remaining(留痕)
    assert res.resolved is False
    assert any(i.kind == "AI腔·对比句式" for i in res.remaining)
    assert res.text == "它不是偶然,而是必然。"  # 原样返回,绝不硬阻断


def test_gate_detector_drives_revise_and_clears():
    # rounds=2:第一轮命中 → 回炉成干净稿 → 第二轮重扫归零 → resolved
    state = {"revised": False}

    def responder(system: str, user: str) -> str:
        if "只挑硬伤" in system or "诊断" in system or "审读" in system:
            return "通过"  # LLM 复审始终说通过,硬伤全靠确定性检测器
        return "它出于必然。"  # 回炉者产出的干净稿(无翻转句)

    backend = FakeBackend(responder)
    det = lambda text: detect(text)  # 在「当前稿」上重扫
    res = gates.run_gate(
        backend, label="去AI味", owner_role="润色师",
        critic_system="审读", revise_system="润色师", draft="它不是偶然,而是必然。",
        knowledge="", produces="本章终稿", rounds=2, max_chars=2000, detector=det,
    )
    assert res.text == "它出于必然。"
    assert res.resolved is True
    assert res.remaining == []
