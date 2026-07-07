"""设定改写/续写:设定师口径、只生成不落盘、rel 守卫(书房 AI 协作二期,spec §4)。"""
import pytest

from conftest import FakeBackend, const
from loom.brainedit import continue_section, rewrite_section


def test_rewrite_prompt_carries_title_fulltext_span_instruction(project):
    be = FakeBackend(const("天启七年,魏阉当政,辽饷岁增,九边糜烂。"))
    out = rewrite_section(project, "外置大脑/世界观/时代格局.md",
                          "# 时代格局\n\n天启七年。", "天启七年。", "更具体,补辽东局势", be)
    assert out.startswith("天启七年,魏阉当政")
    system, user = be.calls[0]
    assert "设定师" in system and "只输出改写后的那一段" in system
    assert "《测试书》" in user and "# 时代格局" in user and "天启七年。" in user and "补辽东局势" in user


def test_rewrite_empty_span_raises(project):
    with pytest.raises(ValueError):
        rewrite_section(project, "外置大脑/世界观/时代格局.md", "x", "   ", "", FakeBackend(const("y")))


def test_rel_guard_blocks_fingerprint_and_chapters(project):
    be = FakeBackend(const("y"))
    for bad in ("外置大脑/写作指纹.md", "正文/第1章.md", "外置大脑/卡章纲.md",
                "外置大脑/世界观/成长档案.md", "skills/去AI味.md", "外置大脑/世界观/../../正文/第1章.md"):
        with pytest.raises(ValueError):
            rewrite_section(project, bad, "x", "x", "", be)
        with pytest.raises(ValueError):
            continue_section(project, bad, "x", "", be)


def test_rel_guard_allows_both_brain_forms(project):
    be = FakeBackend(const("新增:锦衣卫指挥使骆思恭,立场骑墙。"))
    for ok in ("外置大脑/世界观.md", "外置大脑/人物卡.md",
               "外置大脑/世界观/力量体系.md", "外置大脑/人物/反派·魏忠贤.md"):
        assert continue_section(project, ok, "# 既有设定", "补个反派", be)


def test_continue_prompt_says_append_not_repeat(project):
    be = FakeBackend(const("## 势力 · 东林党\n- 立场:清流。"))
    continue_section(project, "外置大脑/世界观/地理与势力.md", "# 地理与势力\n\n- 京师。", "补个党争势力", be)
    system, user = be.calls[0]
    assert "续写" in system and "不重复已有条目" in system
    assert "《测试书》" in user and "- 京师。" in user and "补个党争势力" in user


def test_empty_model_output_raises_backend_error(project):
    from loom.backends import LoomBackendError
    with pytest.raises(LoomBackendError):
        rewrite_section(project, "外置大脑/世界观.md", "x", "一段设定文字", "", FakeBackend(const("   ")))


def test_brain_rewrite_endpoint(project, monkeypatch):
    from fastapi.testclient import TestClient
    from loom import server as srv
    monkeypatch.setattr(srv, "get_backend", lambda cfg: FakeBackend(const("改写后的设定段落文字")))
    c = TestClient(srv.app, base_url="http://127.0.0.1")
    r = c.post("/api/brain/rewrite", json={"root": str(project), "rel": "外置大脑/世界观/时代格局.md",
                                           "full_text": "# 时代格局\n\n天启七年。", "span": "天启七年。",
                                           "instruction": "更具体"})
    assert r.status_code == 200 and r.json()["rewritten"] == "改写后的设定段落文字"


def test_brain_continue_endpoint_and_guard(project, monkeypatch):
    from fastapi.testclient import TestClient
    from loom import server as srv
    monkeypatch.setattr(srv, "get_backend", lambda cfg: FakeBackend(const("## 新势力\n- 立场:骑墙。")))
    c = TestClient(srv.app, base_url="http://127.0.0.1")
    r = c.post("/api/brain/continue", json={"root": str(project), "rel": "外置大脑/人物/反派·魏忠贤.md",
                                            "full_text": "# 反派", "instruction": "补动机"})
    assert r.status_code == 200 and r.json()["continued"].startswith("## 新势力")
    # rel 守卫走到端点层:写作指纹被拒 → 400 + error 文案
    r2 = c.post("/api/brain/rewrite", json={"root": str(project), "rel": "外置大脑/写作指纹.md",
                                            "full_text": "x", "span": "x", "instruction": ""})
    assert r2.status_code == 400 and "专门通道" in r2.json()["error"]
