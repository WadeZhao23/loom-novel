"""doctor 的领航员近况检查:读留痕报降级次数;没有留痕(没降级过)不出这条,零噪音。"""
from loom.doctor import run_checks
from loom.paths import NAV_TRACE_REL


def test_no_trace_no_nav_check(project):
    assert all(c.name != "领航员出题" for c in run_checks(project))


def test_trace_entries_surface_in_doctor(project):
    p = project / NAV_TRACE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 领航员留痕\n\n## 2026-07-15 12:00:00 · 立项\n- 结果: unparsed\n"
                 "\n## 2026-07-15 12:01:00 · 立项\n- 结果: backend_error\n", encoding="utf-8")
    c = next(c for c in run_checks(project) if c.name == "领航员出题")
    assert c.ok is False
    assert "2 次" in c.missing
