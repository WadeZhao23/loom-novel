from loom import partner_tools as pt
import pytest


def test_read_allows_brain(project):
    ev = pt.run_tool(project, "读文件", {"路径": "外置大脑/世界观/金手指.md"}, ts="t")
    assert ev["t"] == "result" and "金手指" in ev["text"]


def test_read_rejects_dotfiles_and_traversal(project):
    for bad in (".env", "../secret", "外置大脑/.拆书/x.md", ".伙伴对话/当前.jsonl"):
        ev = pt.run_tool(project, "读文件", {"路径": bad}, ts="t")
        assert ev.get("error"), f"{bad} 应被拒"


def test_kandiji_returns_slots(project):
    ev = pt.run_tool(project, "看地基", {}, ts="t")
    assert ev["t"] == "result"
    assert "立项" in ev["text"] and "未填" in ev["text"]


def test_tishe_produces_proposal(project):
    ev = pt.run_tool(project, "提设定", {"落点": "外置大脑/立项卡.md#题材", "内容": "重生流"}, ts="t")
    assert ev["t"] == "proposal" and ev["id"] and ev["slot"].endswith("题材")


def test_render_contract_lists_tools():
    c = pt.render_contract()
    assert "读文件" in c and "看地基" in c and "提设定" in c
