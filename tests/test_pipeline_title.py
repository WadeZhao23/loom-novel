"""流水线:自动标题落进首行 H1、正文/快照/账本同口径不误判 drifted、空输出不落空稿。"""
from __future__ import annotations

import pytest

from loom.agents import run_pipeline
from loom.backends import LoomBackendError
from loom.chaptertext import parse_title, strip_title
from loom.config import Config
from loom.ledger import chapter_drifted

from conftest import FakeBackend

LONG = "他屏住呼吸,后背贴着冰冷的石头。" * 30   # 够长,过终稿非空闸


def _responder(system, user):
    if "章节标题" in system:
        return "矿洞惊变"
    return LONG


def test_pipeline_writes_title_and_is_not_drifted(project):
    cfg = Config(provider="deepseek", model="x", chapter_chars=300, gate_rounds=0)
    path, final = run_pipeline(project, 1, FakeBackend(_responder), cfg)

    out = (project / "正文" / "第1章.md").read_text(encoding="utf-8")
    snap = (project / "正文" / ".原稿" / "第1章.md").read_text(encoding="utf-8")
    assert out.lstrip().startswith("# 矿洞惊变")
    assert parse_title(out) == "矿洞惊变"
    assert snap.lstrip().startswith("# 矿洞惊变")          # 快照与正文同口径(都含 H1)
    assert strip_title(out).strip() == strip_title(snap).strip()
    # 关键回归:带标题的章一写完,不该被误判「手改过」而 409 挡住重写
    assert chapter_drifted(project, 1) is False


def test_title_rename_does_not_count_as_drift(project):
    cfg = Config(provider="deepseek", model="x", chapter_chars=300, gate_rounds=0)
    run_pipeline(project, 1, FakeBackend(_responder), cfg)
    out_path = project / "正文" / "第1章.md"
    body = strip_title(out_path.read_text(encoding="utf-8"))
    out_path.write_text("# 我改了个标题\n\n" + body, encoding="utf-8")   # 只改标题
    assert chapter_drifted(project, 1) is False                         # 改标题 ≠ 手改正文


def test_empty_writer_output_does_not_write_empty_chapter(project):
    def empty_writer(system, user):
        if "章节标题" in system:
            return "不该到这"
        return ""        # 任一棒返回空
    cfg = Config(provider="deepseek", model="x", chapter_chars=300, gate_rounds=0)
    with pytest.raises(LoomBackendError) as e:
        run_pipeline(project, 1, FakeBackend(empty_writer), cfg)
    assert e.value.code == "model_output_invalid"
    assert not (project / "正文" / "第1章.md").exists()      # 没有把空正文落盘
