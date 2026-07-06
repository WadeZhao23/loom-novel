"""brain_ready:世界观/人物/卡章纲任一有实质内容才算铺过底(旅程卡完成判定 + 织章拦截共用)。"""
from fastapi.testclient import TestClient

from loom.draft import brain_ready
from loom.fsutil import atomic_write_text
from loom.server import app
from loom.usecases import project_state


def test_fresh_project_not_ready(project):
    assert brain_ready(project) is False


def test_filled_card_row_makes_ready(project):
    card = project / "外置大脑/卡章纲.md"
    atomic_write_text(card, card.read_text(encoding="utf-8").replace("- 第1章:", "- 第1章:睁眼杀魏忠贤。"))
    assert brain_ready(project) is True


def test_world_dir_file_makes_ready(project):
    d = project / "外置大脑/世界观"
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_text(d / "时代格局.md", "# 时代格局\n\n天启七年,阉党当政。")
    assert brain_ready(project) is True


def test_growth_file_alone_does_not_count(project):
    # 成长档案是 learn 的 AI 自留地,不算作者铺过底
    d = project / "外置大脑/人物"
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_text(d / "成长档案.md", "## 王承恩 [AI补充·第1章]\n- 提刀护驾。")
    assert brain_ready(project) is False


def test_state_and_create_endpoint(tmp_path):
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.post("/api/project/create", json={"name": "崇祯书", "parent": str(tmp_path),
                                            "idea": "重生成崇祯", "platform": "番茄"})
    assert r.status_code == 200
    d = r.json()
    assert d["brain_ready"] is False
    assert "平台:番茄" in (tmp_path / "崇祯书" / "外置大脑/立项卡.md").read_text(encoding="utf-8")
    assert project_state(tmp_path / "崇祯书")["brain_ready"] is False
