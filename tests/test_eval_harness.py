"""eval harness 门禁语义:契约样本/双向比对/退出码。零真实模型。"""
import json
from pathlib import Path

from evals import harness
from evals.graders import GraderResult
from evals.harness import CaseResult, compare_to_baseline


def _cr(cid, passed, score, case_type="quality", contract_ok=True, graders=None):
    return CaseResult(cid, cid, score, passed, graders or [], case_type=case_type, contract_ok=contract_ok)


def test_detector_contract_pass_when_flaw_caught(tmp_path):
    # 契约样本:声明「关键要素」必须命中缺陷;检测器正常命中 → contract_ok=True、case passed=True(契约成立=绿)
    d = tmp_path / "c"; d.mkdir()
    (d / "case.json").write_text(json.dumps({
        "id": "det", "chapter_chars": 600, "fixture": "chapter.md",
        "case_type": "detector_contract", "expect_fail_graders": ["关键要素"],
        "expect": {"must_include": ["师姐"], "must_not_include": ["二中"]},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "chapter.md").write_text("这一章缺了师姐,还写了二中。" * 30, encoding="utf-8")  # 有「二中」禁止项→关键要素必fail(注:文本字面含「师姐」二字,故不靠缺失触发)
    r = harness.run_case(d)
    assert r.case_type == "detector_contract"
    assert r.contract_ok is True          # 缺陷被抓到,契约成立
    assert r.passed is True               # 契约样本:契约成立=这个case是绿的


def test_detector_contract_fails_when_detector_broke(tmp_path):
    # 检测器坏了(章节其实干净、grader 没东西可抓)→ 声明该fail的grader反而pass → 契约违约 → case passed=False
    d = tmp_path / "c"; d.mkdir()
    (d / "case.json").write_text(json.dumps({
        "id": "det", "chapter_chars": 600, "fixture": "chapter.md",
        "case_type": "detector_contract", "expect_fail_graders": ["关键要素"],
        "expect": {"must_include": ["师姐"], "must_not_include": ["二中"]},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "chapter.md").write_text("师姐登场,这一章很干净没有禁词。" * 30, encoding="utf-8")  # 师姐在+无二中→关键要素会pass
    r = harness.run_case(d)
    assert r.contract_ok is False         # 本该命中缺陷的grader却通过=检测器失灵
    assert r.passed is False              # 契约违约 → 该红
