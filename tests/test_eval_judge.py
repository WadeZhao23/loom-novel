"""LLM-judge grader:后端失败不假通过、非法输出、正常判断。用 FakeBackend,零真实模型。"""
from conftest import FakeBackend
from evals.graders import grade_quality_llm, grade_deslop_llm


def _boom(system, user, **kw):
    raise RuntimeError("后端炸了")


def test_backend_failure_not_fake_pass():
    g = grade_quality_llm("正文", "设定", FakeBackend(_boom))
    assert g.passed is False          # 后端失败绝不假通过
    assert "[infra]" in g.detail      # 标成 infra 供上层识别


def test_deslop_backend_failure_not_fake_pass():
    g = grade_deslop_llm("正文", "指纹", FakeBackend(_boom))
    assert g.passed is False and "[infra]" in g.detail


def test_clean_verdict_passes():
    g = grade_quality_llm("正文", "设定", FakeBackend(lambda s, u, **k: "通过"))
    assert g.passed is True           # 复审回「通过」→ 无硬伤 → passed


def test_issues_found_fails():
    verdict = "- OOC：主角性格崩了\n- 断钩：章末没留悬念"
    g = grade_quality_llm("正文", "设定", FakeBackend(lambda s, u, **k: verdict))
    assert g.passed is False          # 挑出硬伤 → 不通过
