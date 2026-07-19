"""伙伴对话存储:jsonl 单行 append + 坏行跳过 + proposal 查找。上下文不是状态。"""
from loom import partner_store as ps
from loom.paths import PARTNER_CUR_REL


def test_append_and_read_roundtrip(project):
    ps.append_event(project, {"t": "user", "ts": "2026-07-16T00:00:00", "text": "你好"})
    ps.append_event(project, {"t": "assistant", "ts": "2026-07-16T00:00:01", "text": "我在"})
    evs = ps.read_events(project)
    assert [e["t"] for e in evs] == ["user", "assistant"]
    assert evs[0]["text"] == "你好"


def test_bad_line_skipped(project):
    ps.append_event(project, {"t": "user", "ts": "x", "text": "ok"})
    p = project / PARTNER_CUR_REL
    p.write_text(p.read_text(encoding="utf-8") + "{坏行不是json\n", encoding="utf-8")
    ps.append_event(project, {"t": "assistant", "ts": "y", "text": "still ok"})
    evs = ps.read_events(project)
    assert [e["t"] for e in evs] == ["user", "assistant"]   # 坏行跳过,前后都在


def test_tail_limits(project):
    for i in range(5):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"m{i}"})
    assert [e["text"] for e in ps.read_events(project, tail=2)] == ["m3", "m4"]


def test_find_proposal_scans_full_file(project):
    for i in range(20):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"m{i}"})
    ps.append_event(project, {"t": "proposal", "ts": "p", "id": "p1", "slot": "外置大脑/立项卡.md#题材", "content": "重生流"})
    for i in range(20):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"n{i}"})
    found = ps.find_proposal(project, "p1")
    assert found and found["content"] == "重生流"     # 全文件找,不受 tail 影响


def test_delete_dir_is_safe(project):
    # 删 .伙伴对话/ 只是失忆,read_events 返空不炸
    ps.append_event(project, {"t": "user", "ts": "x", "text": "ok"})
    import shutil
    shutil.rmtree(project / ".伙伴对话")
    assert ps.read_events(project) == []
