"""M3 增量重写模式:支持跳过设定师/大纲师的轻量管道。"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from loom.agents import STEPS, _outline_path, _hardfacts_for, load_agent

# 足够通过正文 guard(800 字的 12% = 96 字)的测试文本
_LONG_TEXT = (
    "这是产出的第一章内容。包含一些实质性的文字内容,确保能够通过校验和检查的关卡。"
    "正文需要至少九十六字才能通过终稿非空闸,所以这段文字适当拉长篇幅以确保不会被阻拦。"
    "这里包含一些描述性的文字和各种实质性内容。大概已经有一百多字,足够通过检查了。"
    "再补充一点点内容确保阈值绰绰有余。"
)


class TestSteps:
    """STEPS 表测试。"""

    def test_steps_order(self):
        """5 步流水线角色序列正确。"""
        assert [s.role for s in STEPS] == ["设定师", "大纲师", "写手", "编辑", "润色师"]

    def test_step_indices(self):
        """start_step 与角色映射正确。"""
        assert STEPS[0].role == "设定师"
        assert STEPS[1].role == "大纲师"
        assert STEPS[2].role == "写手"

    def test_outline_path_structure(self, project: Path):
        """_outline_path 返回正确的细纲路径。"""
        p = _outline_path(project, 1)
        assert "正文/.细纲" in str(p)
        assert p.name == "第1章.md"

    def test_hardfacts_for_returns_text(self, project: Path):
        """样板项目有世界观,hardfacts 不为空。"""
        hard = _hardfacts_for(project)
        assert hard is not None and hard.strip() != ""


class TestPartialPipelineCore:
    """测试增量重写的核心逻辑(不调后端)。"""

    def test_start_step_0_default(self):
        """start_step=0 时跑完整流水线。"""
        assert len(STEPS) == 5

    def test_run_pipeline_has_start_step_param(self):
        """run_pipeline 函数签名包含 start_step 参数,默认 0。"""
        from loom.agents import run_pipeline
        sig = inspect.signature(run_pipeline)
        assert "start_step" in sig.parameters
        assert sig.parameters["start_step"].default == 0

    def test_write_chapter_has_start_step_param(self):
        """usecases.write_chapter 函数签名包含 start_step 参数,默认 0。"""
        from loom.usecases import write_chapter
        sig = inspect.signature(write_chapter)
        assert "start_step" in sig.parameters
        assert sig.parameters["start_step"].default == 0

    def test_load_agent_returns_produces(self, project: Path):
        """各角色的 produces 字段正确。"""
        produces = {spec.role: load_agent(project, spec.role).produces for spec in STEPS}
        assert produces["设定师"] == "本章设定锚点"
        assert produces["大纲师"] == "本章场景骨头(分镜细纲)"
        assert produces["写手"] == "本章初稿"
        assert produces["编辑"] == "本章改稿"
        assert produces["润色师"] == "本章终稿"

    def test_outline_file_exists(self, project: Path):
        """细纲文件创建后存在。"""
        p = _outline_path(project, 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("分镜细纲:第一场(约 500 字),第二场(约 700 字)", encoding="utf-8")
        assert p.exists()
        assert p.read_text(encoding="utf-8").strip()

    def test_cli_write_has_start_step_interface(self):
        """CLI write 函数通过 usecases 传递 start_step。"""
        import inspect
        from loom.usecases import write_chapter
        sig = inspect.signature(write_chapter)
        assert "start_step" in sig.parameters


class TestPartialPipelineWithFakeBackend:
    """FakeBackend 模拟后端,验证增量重写流水线行为。"""

    def _setup_outline(self, project: Path, chapter: int, text: str = "") -> None:
        """创建细纲文件。"""
        p = _outline_path(project, chapter)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text or "分镜细纲:第一场(约 500 字)", encoding="utf-8")

    @staticmethod
    def _make_tracked_backend(track: list[str]) -> object:
        """返回一个 TrackedBackend 实例,按角色响应并记入 track。"""
        from loom.backends import CompletionResult

        class _Backend:
            def complete(self, system, user, max_chars=None, on_chunk=None):
                for role, produces in [
                    ("设定师", "本章设定锚点"),
                    ("大纲师", "本章场景骨头"),
                    ("写手", "本章初稿"),
                    ("编辑", "本章改稿"),
                    ("润色师", "本章终稿"),
                ]:
                    if f"产出【{produces}" in user:
                        if role not in track:
                            track.append(role)
                        text = f"这是{role}产出的结果。{_LONG_TEXT}"
                        if on_chunk and text:
                            on_chunk(text)
                        return CompletionResult(text)
                text = _LONG_TEXT
                if on_chunk:
                    on_chunk(text)
                return CompletionResult(text)

            @property
            def usage_history(self):
                return None

        return _Backend()

    def test_full_pipeline_runs_all(self, project: Path):
        """start_step=0 → 5 道工序全部执行。"""
        from loom.agents import run_pipeline
        from loom.config import load_config

        calls: list[str] = []
        backend = self._make_tracked_backend(calls)
        cfg = load_config(project)
        path, text = run_pipeline(project, 1, backend, cfg, start_step=0, resume=False)

        assert len(calls) == 5
        assert calls == ["设定师", "大纲师", "写手", "编辑", "润色师"]
        assert path.exists()

    def test_from_writer_skips_two(self, project: Path):
        """start_step=2: 跳过设定师+大纲师。"""
        from loom.agents import run_pipeline
        from loom.config import load_config

        self._setup_outline(project, 1)
        calls: list[str] = []
        backend = self._make_tracked_backend(calls)
        cfg = load_config(project)
        path, text = run_pipeline(project, 1, backend, cfg, start_step=2, resume=False)

        assert "设定师" not in calls
        assert "大纲师" not in calls
        assert calls == ["写手", "编辑", "润色师"]
        assert path.exists()

    def test_skip_outliner_skips_setter_only(self, project: Path):
        """start_step=1: 跳过设定师,保留大纲师。"""
        from loom.agents import run_pipeline
        from loom.config import load_config

        calls: list[str] = []
        backend = self._make_tracked_backend(calls)
        cfg = load_config(project)
        path, text = run_pipeline(project, 1, backend, cfg, start_step=1, resume=False)

        assert "设定师" not in calls
        assert calls == ["大纲师", "写手", "编辑", "润色师"]
        assert path.exists()

    def test_from_writer_workspace_has_anchor_and_outline(self, project: Path):
        """start_step=2 时,写手 prompt 含有设定锚点和细纲。"""
        from loom.backends import CompletionResult
        from loom.agents import run_pipeline
        from loom.config import load_config

        outline_text = "分镜细纲:第一场(约 300 字),第二场(约 500 字)"
        self._setup_outline(project, 1, outline_text)

        user_prompts: list[str] = []

        class _Backend2:
            def complete(self, system, user, max_chars=None, on_chunk=None):
                user_prompts.append(user)
                text = _LONG_TEXT
                if on_chunk:
                    on_chunk(text)
                return CompletionResult(text)

            @property
            def usage_history(self):
                return None

        cfg = load_config(project)
        run_pipeline(project, 1, _Backend2(), cfg, start_step=2, resume=False)

        writer_prompt = next(
            (u for u in user_prompts if "你的任务" in u and "产出【本章初稿" in u), None
        )
        assert writer_prompt is not None, "应触发写手 prompt"
        assert "本章工作区" in writer_prompt, "工作区应出现在写手 prompt 中"
        assert "本章设定锚点" in writer_prompt, "工作区应包含设定锚点"
        assert "本章场景骨头(分镜细纲)" in writer_prompt, "工作区应包含细纲"
