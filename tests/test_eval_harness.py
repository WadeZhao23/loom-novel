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


def test_new_case_not_in_baseline_flagged(tmp_path):
    base = {"cases": {"old": {"score": 1.0, "passed": True}}}
    results = [_cr("old", True, 1.0), _cr("new", True, 0.9)]   # new 不在 baseline
    regs = compare_to_baseline(results, base)
    assert any(x["case"] == "new" and "未固化" in x["kind"] for x in regs)


def test_deleted_baseline_case_flagged(tmp_path):
    base = {"cases": {"old": {"score": 1.0, "passed": True}, "gone": {"score": 1.0, "passed": True}}}
    results = [_cr("old", True, 1.0)]                          # gone 从数据集删了
    regs = compare_to_baseline(results, base)
    assert any(x["case"] == "gone" and "消失" in x["kind"] for x in regs)


def test_no_false_regression_when_matched(tmp_path):
    base = {"cases": {"old": {"score": 1.0, "passed": True}}}
    results = [_cr("old", True, 1.0)]
    assert compare_to_baseline(results, base) == []            # 对齐时零回归


def test_baseline_stores_per_grader_and_version(tmp_path):
    from evals.harness import save_baseline, CaseResult
    from evals.graders import GraderResult
    g = GraderResult("关键要素", 0.5, False, 1.0, True)
    r = CaseResult("c", "c", 0.5, False, [g], case_type="detector_contract", contract_ok=True)
    p = tmp_path / "b.json"
    save_baseline(p, [r])
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    c = data["cases"]["c"]
    assert c["case_type"] == "detector_contract"
    assert c["graders"]["关键要素"] == {"score": 0.5, "passed": False, "gating": True}
    assert c["score"] == 0.5 and c["passed"] is False   # 旧键仍在(向后兼容 compare)
