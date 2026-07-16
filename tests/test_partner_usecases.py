"""伙伴用例层:confirm 拍板落盘(找proposal→_land_slot→记confirm事件,幂等/过期/撞车不崩)、
new 归档、history 纯读。红线:对话里的「提设定」只产 proposal,唯一落盘出口是 confirm。"""
from loom import partner_store as ps
from loom import usecases


def test_partner_confirm_lands_into_slot_and_records_confirm_event(project):
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": "外置大脑/立项卡.md#平台", "content": "番茄"})
    out = usecases.partner_confirm(project, "p1", ts="t2")
    assert out["landed"].endswith("立项卡.md")
    assert "平台:番茄" in (project / "外置大脑/立项卡.md").read_text(encoding="utf-8")
    assert "error" not in out
    assert out["state"]["current"]   # journey_state 派生视图随附返回
    confirms = [e for e in ps.read_events(project) if e.get("t") == "confirm"]
    assert len(confirms) == 1
    assert confirms[0]["id"] == "p1" and confirms[0]["landed"] == out["landed"]


def test_partner_confirm_idempotent_does_not_double_land(project):
    # file 类落点是追加写:二次落盘会在文件里重复出现同一段内容,用它来钉住幂等
    target = project / "外置大脑/世界观/一句话定位.md"
    before = target.read_text(encoding="utf-8")
    needle = "深海矿城漂浮于风暴之上,能源即权柄"   # 与占位示例文案不重叠,免误判基线
    assert needle not in before
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": "外置大脑/世界观/一句话定位.md#@body", "content": needle})
    out1 = usecases.partner_confirm(project, "p1", ts="t2")
    text_after_first = target.read_text(encoding="utf-8")
    assert text_after_first.count(needle) == 1

    out2 = usecases.partner_confirm(project, "p1", ts="t3")   # 重发(双击/重试)
    text_after_second = target.read_text(encoding="utf-8")
    assert text_after_second == text_after_first   # 没有二次落盘
    assert text_after_second.count(needle) == 1
    assert out2["landed"] == out1["landed"]

    confirms = [e for e in ps.read_events(project) if e.get("t") == "confirm"]
    assert len(confirms) == 1   # confirm 事件也没有二次写


def test_partner_confirm_expired_proposal_returns_error_not_raise(project):
    out = usecases.partner_confirm(project, "no-such-id", ts="t1")
    assert out == {"error": "提案已过期,重新问一次"}
    assert [e for e in ps.read_events(project) if e.get("t") == "confirm"] == []


def test_partner_confirm_collision_returns_error_without_crashing(project):
    # 撞车:_land_slot 对 filename 类落点在目标已有实质内容时抛 ValueError(同 test_journey.py
    # test_land_slot_filename_collision_refuses 的前提)——confirm 必须捕获,不许崩、不许落盘。
    d = project / "外置大脑/人物"
    (d / "主角·林潜.md").write_text("# 主角 · 林潜\n\n- 核心欲望:复仇\n", encoding="utf-8")
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": "外置大脑/人物/主角·未命名.md#@name", "content": "林潜"})
    out = usecases.partner_confirm(project, "p1", ts="t2")
    assert "error" in out
    assert (d / "主角·未命名.md").exists()   # 原文件没被吞
    assert [e for e in ps.read_events(project) if e.get("t") == "confirm"] == []   # 没落盘就没记confirm


def test_partner_confirm_unknown_slot_returns_error_without_crashing(project):
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": "外置大脑/立项卡.md#不存在的键", "content": "x"})
    out = usecases.partner_confirm(project, "p1", ts="t2")
    assert "error" in out


def test_confirm_rejects_when_row_slot_changed_since_proposal(project):
    # row/line 型落点(平台行):proposal 之后作者手改了这一格 → confirm 必须拒绝(stale),
    # 不覆盖手改。平台的值短(几个字),不会撞上 preview 24 字的饱和上限,能被快照守卫检测到。
    slot_id = "外置大脑/立项卡.md#平台"
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": slot_id, "content": "番茄", "before": "起点"})
    p = project / "外置大脑/立项卡.md"
    p.write_text(p.read_text(encoding="utf-8").replace("平台:起点", "平台:七猫"), encoding="utf-8")
    out = usecases.partner_confirm(project, "p1", ts="t2")
    assert out == {"error": "这一格刚改过,我重新看看再给你提", "stale": True}
    assert "平台:七猫" in p.read_text(encoding="utf-8")   # 手改没被覆盖
    assert [e for e in ps.read_events(project) if e.get("t") == "confirm"] == []


def test_confirm_tolerates_malformed_proposal(project):
    # proposal 缺 content(损坏/旧版本残留)→ 返 error,不许 KeyError 崩
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": "外置大脑/立项卡.md#平台"})
    out = usecases.partner_confirm(project, "p1", ts="t2")
    assert "error" in out
    assert [e for e in ps.read_events(project) if e.get("t") == "confirm"] == []


def test_confirm_idempotent_still_first(project):
    # 快照守卫不破坏现有幂等:confirm 事件先拦,即便落盘后该格 preview 已经不等于 before
    # (落盘本身就会让 before 过期),第二次 confirm 仍走幂等分支返已落盘结果,不误判 stale。
    slot_id = "外置大脑/立项卡.md#平台"
    ps.append_event(project, {"t": "proposal", "ts": "t1", "id": "p1",
                               "slot": slot_id, "content": "番茄", "before": "起点"})
    out1 = usecases.partner_confirm(project, "p1", ts="t2")
    assert "error" not in out1
    out2 = usecases.partner_confirm(project, "p1", ts="t3")   # 重发(双击/重试)
    assert out2["landed"] == out1["landed"]
    assert "error" not in out2
    confirms = [e for e in ps.read_events(project) if e.get("t") == "confirm"]
    assert len(confirms) == 1


def test_partner_new_archives_current_conversation(project):
    ps.append_event(project, {"t": "user", "ts": "1", "text": "你好"})
    out = usecases.partner_new(project, stamp="20260716-000000")
    assert out == {"ok": True}
    assert ps.read_events(project) == []   # 当前对话清空(失忆,书文件无恙)
    archived = project / ".伙伴对话" / "归档-20260716-000000.jsonl"
    assert archived.is_file()


def test_partner_history_reads_events_read_only(project):
    ps.append_event(project, {"t": "user", "ts": "1", "text": "你好"})
    ps.append_event(project, {"t": "assistant", "ts": "2", "text": "在的"})
    out = usecases.partner_history(project)
    assert [e["t"] for e in out["events"]] == ["user", "assistant"]


def test_partner_history_tail_limits(project):
    for i in range(5):
        ps.append_event(project, {"t": "user", "ts": str(i), "text": f"m{i}"})
    out = usecases.partner_history(project, tail=2)
    assert [e["text"] for e in out["events"]] == ["m3", "m4"]
