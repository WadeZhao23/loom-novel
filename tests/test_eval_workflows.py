"""workflow 结构不变量:PR CI 零 key、eval-real 只手动/定时、release 不被碰。"""
from pathlib import Path

WF = Path(".github/workflows")


def _load(name):
    import yaml    # pyyaml 在 .[dev]?不在则本测试 pytest.importorskip
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def test_ci_stays_zero_key():
    import pytest
    pytest.importorskip("yaml")
    text = (WF / "ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in text                    # PR CI 绝不碰 secret
    assert "--judge-backend configured" not in text  # 绝不在 PR CI 跑真 Judge
    ci = _load("ci.yml")
    # artifact 上传步骤存在(报告可追溯)
    assert "actions/upload-artifact" in text


def test_eval_real_triggers_are_dispatch_and_schedule_only():
    import pytest
    pytest.importorskip("yaml")
    wf = _load("eval-real.yml")
    on = wf[True] if True in wf else wf.get("on")     # yaml 把 on 解析成 True 键
    assert set(on.keys()) <= {"workflow_dispatch", "schedule"}   # 绝不 pull_request(_target)
    assert "pull_request" not in on


def test_release_yml_untouched_needs_chain():
    import pytest
    pytest.importorskip("yaml")
    import yaml
    data = yaml.safe_load((WF / "release.yml").read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert jobs["build-mac"]["needs"] == "test"
    assert jobs["build-windows"]["needs"] == "test"
    assert jobs["release"]["needs"] == ["build-mac", "build-windows"]


def test_ci_report_step_is_bash_and_nonblocking():
    import pytest
    pytest.importorskip("yaml")
    import yaml
    data = yaml.safe_load((WF / "ci.yml").read_text(encoding="utf-8"))
    steps = data["jobs"]["test"]["steps"]
    rep = [s for s in steps if s.get("name", "").startswith("生成 fixture")]
    assert rep, "没找到报告生成步骤"
    assert rep[0].get("shell") == "bash"                 # 跨平台,防 Windows pwsh 崩
    assert rep[0].get("continue-on-error") is True       # 报告 bug 不否决已过门禁
