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


def test_tishe_captures_before_preview(project):
    # 提设定产 proposal 时带 before=落点当前 preview(快照守卫用它比对手改);
    # 立项卡「平台」骨架落点默认值是「起点」,line 型 preview 不饱和,能原样比对。
    ev = pt.run_tool(project, "提设定", {"落点": "外置大脑/立项卡.md#平台", "内容": "番茄"}, ts="t")
    assert ev["t"] == "proposal"
    assert ev["before"] == "起点"


def test_render_contract_lists_tools():
    c = pt.render_contract()
    assert "读文件" in c and "看地基" in c and "提设定" in c


def test_read_rejects_symlink_into_dotdir(project):
    # 白名单目录内的符号链接指向点目录→必须拒(防解析后绕过)
    import os
    secret = project / "外置大脑/.拆书"; secret.mkdir(parents=True, exist_ok=True)
    (secret / "s.md").write_text("机密", encoding="utf-8")
    os.symlink(secret / "s.md", project / "外置大脑/link.md")
    ev = pt.run_tool(project, "读文件", {"路径": "外置大脑/link.md"}, ts="t")
    assert ev.get("error"), "符号链接指向点目录必须被拒"
    assert "机密" not in ev.get("text", "")


def test_read_rejects_whitelist_boundary(project):
    # 白名单外:loom.toml、agents/ 都不在读白名单
    for bad in ("loom.toml", "agents/领航员.md"):
        ev = pt.run_tool(project, "读文件", {"路径": bad}, ts="t")
        assert ev.get("error"), f"{bad} 应被拒(不在白名单)"


def test_kandiji_shows_filled_and_preview(project):
    # 看地基是全量明细:填一格后能看到该格 filled + preview
    p = project / "外置大脑/立项卡.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "(占位示例:玄幻 · 东方玄幻。填你投稿的那个分区,让设定师知道这本书归在哪一类。)", "都市异能"), encoding="utf-8")
    ev = pt.run_tool(project, "看地基", {}, ts="t")
    assert "都市异能" in ev["text"]     # preview 出现在全量明细里


def test_read_truncation_stays_within_budget(project):
    # 截断提示语本身也要计入预算:总长(正文+提示)必须 ≤3000 字,不能拼完超红线
    p = project / "外置大脑/世界观/超长.md"
    p.write_text("正" * 5000, encoding="utf-8")
    ev = pt.run_tool(project, "读文件", {"路径": "外置大脑/世界观/超长.md"}, ts="t")
    assert ev["t"] == "result"
    assert len(ev["text"]) <= 3000, f"总长 {len(ev['text'])} 超预算"
