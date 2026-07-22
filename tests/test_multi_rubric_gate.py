"""M6 可配置多候选 Gate:同时跑多个 rubric 各审一次。"""
from __future__ import annotations

from pathlib import Path

import pytest

from loom.config import Config, load_config
from loom.gates import (
    _load_rubric_file,
    _merge_issues,
    run_multi_rubric_gate,
    Issue,
)
from loom.backends import CompletionResult

from conftest import FakeBackend, const


class TestMultiRubricConfig:
    """测试 multi_rubric 配置解析。"""

    def test_config_has_multi_rubric_field(self):
        """Config 有 multi_rubric 字段,默认空列表。"""
        cfg = Config()
        assert cfg.multi_rubric == []

    def test_toml_parses_multi_rubric(self, tmp_path: Path):
        """loom.toml [gate.multi_rubric] 正确解析为列表。"""
        toml = """
[backend]
provider = "deepseek"
model = "deepseek-v4-pro"

[novel]
title = "测试书"
"章节字数" = 800

[gate]
"轮数" = 2
multi_rubric = ["rubric1.md", "rubric2.md"]
"""
        (tmp_path / "loom.toml").write_text(toml, encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg.multi_rubric == ["rubric1.md", "rubric2.md"]
        assert cfg.gate_rounds == 2

    def test_multi_rubric_empty_default(self, tmp_path: Path):
        """未设置 multi_rubric 时为空列表。"""
        toml = """
[backend]
provider = "deepseek"
model = "deepseek-v4-pro"

[novel]
title = "测试书"
"章节字数" = 800

[gate]
"轮数" = 1
"""
        (tmp_path / "loom.toml").write_text(toml, encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg.multi_rubric == []

    def test_multi_rubric_single_entry(self, tmp_path: Path):
        """multi_rubric 可以只有一条。"""
        toml = """
[backend]
provider = "deepseek"
model = "deepseek-v4-pro"

[novel]
title = "测试书"
"章节字数" = 800

[gate]
"轮数" = 1
multi_rubric = ["额外质检视角.md"]
"""
        (tmp_path / "loom.toml").write_text(toml, encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg.multi_rubric == ["额外质检视角.md"]


class TestLoadRubricFile:
    """测试 rubric 文件加载。"""

    def test_load_from_project_root(self, project: Path):
        """从项目根加载存在文件。"""
        rubric = project / "my_rubric.md"
        rubric.write_text("这是自定义 rubric\n", encoding="utf-8")
        content = _load_rubric_file(project, "my_rubric.md")
        assert "自定义 rubric" in content

    def test_load_from_skills_dir(self, project: Path):
        """从 skills/ 目录加载。"""
        skills_dir = project / "skills"
        skills_dir.mkdir(exist_ok=True)
        rubric = skills_dir / "质检视角2.md"
        rubric.write_text("第二个质检视角\n", encoding="utf-8")
        content = _load_rubric_file(project, "质检视角2.md")
        assert "第二个质检视角" in content

    def test_load_nonexistent_returns_empty(self, project: Path):
        """不存在的文件返回空串。"""
        content = _load_rubric_file(project, "不存在的文件.md")
        assert content == ""


class TestMergeIssues:
    """测试 Issue 合并去重。"""

    def test_merge_different_issues(self):
        """不同 issue 应该合并。"""
        a = [Issue(kind="人物OOC", desc="主角表现不符", evidence="行1")]
        b = [Issue(kind="设定漂移", desc="境界名错误", evidence="行2")]
        merged = _merge_issues(a, b)
        assert len(merged) == 2

    def test_merge_duplicate_issues(self):
        """相同 issue 应该去重(按 kind+evidence 判)。"""
        a = [Issue(kind="人物OOC", desc="第一版", evidence="行1")]
        b = [Issue(kind="人物OOC", desc="第二版", evidence="行1")]  # 相同 evidence
        merged = _merge_issues(a, b)
        assert len(merged) == 1

    def test_merge_deduplicates_by_kind_and_evidence(self):
        """去重键为 (kind, evidence)。"""
        a = [Issue(kind="A", desc="甲", evidence="行1")]
        b = [Issue(kind="A", desc="乙", evidence="行1")]  # 同 kind 同 evidence → 去重,保留第一个的 desc
        merged = _merge_issues(a, b)
        assert len(merged) == 1
        assert merged[0].desc == "甲"  # 保留 first-seen 的 desc

    def test_merge_same_kind_different_evidence(self):
        """同 kind 不同 evidence 不的去重。"""
        a = [Issue(kind="人物OOC", desc="问题A", evidence="行1")]
        b = [Issue(kind="人物OOC", desc="问题B", evidence="行2")]
        merged = _merge_issues(a, b)
        assert len(merged) == 2


class TestRunMultiRubricGate:
    """测试 run_multi_rubric_gate 核心逻辑。"""

    def test_rounds_0_returns_draft(self):
        """rounds <= 0 时原样返回。"""
        result = run_multi_rubric_gate(
            None, label="质检", owner_role="写手",
            default_critic="质检", default_revise="修正",
            multi_rubric=[], project_root=Path("/tmp"),
            draft="原稿内容", knowledge="", produces="终稿",
            rounds=0, max_chars=800,
        )
        assert result.text == "原稿内容"
        assert result.resolved is True

    def test_rounds_1_no_multi_uses_default(self):
        """rounds=1 且无 multi_rubric 时,退化为用默认 rubric 诊断一次。"""
        calls = []

        class CountingBackend:
            calls = []

            def complete(self, system, user, max_chars=None, on_chunk=None):
                self.calls.append((system[:30], user[:50]))
                return CompletionResult("通过")  # 无 hard issues

            @property
            def usage_history(self):
                return None

        backend = CountingBackend()
        result = run_multi_rubric_gate(
            backend, label="质检", owner_role="写手",
            default_critic="你是质检员", default_revise="你是修正员",
            multi_rubric=[], project_root=Path("/tmp"),
            draft="原稿内容", knowledge="设定知识", produces="终稿",
            rounds=1, max_chars=800,
        )
        # 只有一次调用:默认 rubric 诊断
        assert len(backend.calls) == 1
        assert result.resolved is True

    def test_rounds_2_with_extra_rubric_runs_both(self):
        """rounds=2 且 multi_rubric 有一条时,跑默认 + 额外各一次。"""
        # 创建临时 rubric 文件
        rubric_path = "/tmp/test_extra_rubric.md"
        Path(rubric_path).write_text("额外质检视角:检查逻辑一致性", encoding="utf-8")

        class CountingBackend:
            calls = []

            def complete(self, system, user, max_chars=None, on_chunk=None):
                self.calls.append((system[:20], user[:30]))
                return "通过"  # 无 hard issues

            @property
            def usage_history(self):
                return None

        try:
            backend = CountingBackend()
            result = run_multi_rubric_gate(
                backend, label="质检", owner_role="写手",
                default_critic="默认质检员", default_revise="修正员",
                multi_rubric=[rubric_path], project_root=Path("/tmp"),
                draft="原稿内容", knowledge="设定知识", produces="终稿",
                rounds=2, max_chars=800,
            )
            # 2 次调用:默认 rubric + 额外 rubric
            assert len(backend.calls) == 2
            assert "默认质检员" in backend.calls[0][0]
            assert result.resolved is True
        finally:
            Path(rubric_path).unlink(missing_ok=True)

    def test_extra_rubric_detects_issues(self):
        """额外 rubric 能发现默认 rubric 没发现的问题。"""
        rubric_text = "额外质检视角:检查时间线一致性"
        rubric_path = "/tmp/test_time_rubric.md"
        Path(rubric_path).write_text(rubric_text, encoding="utf-8")

        replies = [
            "通过",  # 默认 rubric:无问题
            "- 时间线 | 时间词矛盾 | 证据:\"昨夜说成昨日\"",  # 额外 rubric:发现问题
        ]

        class Scripted:
            def __init__(self, replies):
                self.replies = list(replies)

            def complete(self, system, user, max_chars=None, on_chunk=None):
                r = self.replies.pop(0) if self.replies else ""
                return CompletionResult(r)

            @property
            def usage_history(self):
                return None

        try:
            backend = Scripted(replies)
            result = run_multi_rubric_gate(
                backend, label="质检", owner_role="写手",
                default_critic="默认质检员", default_revise="修正员",
                multi_rubric=[rubric_path], project_root=Path("/tmp"),
                draft="原稿内容", knowledge="设定知识", produces="终稿",
                rounds=2, max_chars=800,
            )
            # 额外 rubric 发现问题→回炉一次→不 resolved
            assert result.resolved is False
            assert len(result.remaining) == 1
            assert result.remaining[0].kind == "时间线"
        finally:
            Path(rubric_path).unlink(missing_ok=True)

    def test_rounds_1_with_multi_rubric_only_runs_default(self):
        """rounds=1 即使有 multi_rubric,也只跑默认 rubric。"""
        class CountingBackend:
            calls = 0

            def complete(self, system, user, max_chars=None, on_chunk=None):
                self.calls += 1
                return "通过"

            @property
            def usage_history(self):
                return None

        backend = CountingBackend()
        result = run_multi_rubric_gate(
            backend, label="质检", owner_role="写手",
            default_critic="默认", default_revise="修正",
            multi_rubric=["额外.md"], project_root=Path("/tmp"),
            draft="内容", knowledge="知识", produces="终稿",
            rounds=1, max_chars=800,
        )
        assert backend.calls == 1  # 只调用了一次(默认 rubric)

    def test_backward_compat_rounds_1(self):
        """rounds=1,无 multi_rubric 时行为与原来完全一致。"""
        calls = []

        class Backend:
            def complete(self, system, user, max_chars=None, on_chunk=None):
                calls.append((system, user))
                return "通过"

            @property
            def usage_history(self):
                return None

        backend = Backend()
        result = run_multi_rubric_gate(
            backend, label="质检", owner_role="写手",
            default_critic="标准critic", default_revise="标准revise",
            multi_rubric=[], project_root=Path("/tmp"),
            draft="正文内容", knowledge="设定", produces="终稿",
            rounds=1, max_chars=800,
        )
        assert len(calls) == 1
        assert "标准critic" in calls[0][0]


class TestMultiRubricInPipeline:
    """测试 multi_rubric 在流水线中的集成。"""

    def test_agents_passes_multi_rubric_to_gate(self):
        """agents.run_pipeline 在 gate 处传递 config.multi_rubric。"""
        import inspect
        from loom.gates import run_multi_rubric_gate
        sig = inspect.signature(run_multi_rubric_gate)
        assert "multi_rubric" in sig.parameters
        assert "default_critic" in sig.parameters

    def test_config_multi_rubric_in_agents_gate_section(self):
        """agents.py 的 gate 调用部分读取 config.multi_rubric。"""
        import inspect
        from loom.agents import run_pipeline
        src = inspect.getsource(run_pipeline)
        assert "multi_rubric" in src
        assert "run_multi_rubric_gate" in src
        assert "run_gate" in src  # 正常路径也要保留
