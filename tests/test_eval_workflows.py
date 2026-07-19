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
    text = (WF / "release.yml").read_text(encoding="utf-8")
    assert "needs: test" in text and "needs: [build-mac, build-windows]" in text
