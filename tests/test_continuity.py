"""连续性除虫:确定性双检测(零 LLM)+ LLM 扫描(Task 4 补)。守只报告不改稿。"""
from loom import statebook
from loom.continuity import BugItem, detect_consumed_reuse, detect_rule_drift, merge_items


def _book():
    return {2: [("物品", "远古药胚:已吞服消耗(冲刷绝脉) | 证据:「吞入腹中」"),
                ("物品", "铁剑:获得 | 证据:「拾起」"),
                ("规则", "因果锁定:满100%触发,100%反馈修行成果 | 证据:「锁定」")]}


def test_consumed_reuse_hit():
    body = "江澈取出远古药胚,以其伴生精血炼成破禁丹。"
    items = detect_consumed_reuse(_book(), 4, body)
    assert len(items) == 1 and items[0].kind == "物品" and items[0].stars == 5
    assert "远古药胚" in items[0].desc and "第2章" in items[0].prior
    assert items[0].evidence and "远古药胚" in items[0].evidence   # 证据=正文所在句


def test_consumed_reuse_ignores_unconsumed_and_absent():
    assert detect_consumed_reuse(_book(), 4, "他握紧铁剑。") == []        # 获得类不报
    assert detect_consumed_reuse(_book(), 4, "他两手空空。") == []        # 没出现不报
    assert detect_consumed_reuse(_book(), 2, "远古药胚仍在。") == []      # 只查前章账本(m<n)


def test_rule_drift_hit():
    body = "系统提示:因果锁定触发,未来每突破一个大境界,自动反馈10%修为。"
    items = detect_rule_drift(_book(), 4, body)
    assert len(items) == 1 and items[0].kind == "规则" and "10%" in items[0].evidence
    assert "100%" in items[0].prior


def test_rule_drift_same_number_silent():
    assert detect_rule_drift(_book(), 4, "因果锁定:100%反馈,一如既往。") == []


def test_merge_dedup_prefers_deterministic():
    a = BugItem(5, "物品", "det 版", evidence="远古药胚句")
    b = BugItem(3, "物品", "llm 版", evidence="远古药胚句")
    c = BugItem(2, "时间", "独有", evidence="昨日")
    out = merge_items([a], [b, c])
    assert out[0].desc == "det 版" and len(out) == 2


def test_parse_scan_two_segments():
    from loom.continuity import parse_scan
    raw = ("===除虫报告===\n"
           "- ⭐⭐⭐⭐⭐ | 物品 | 药胚复活 | 本章证据:「取出药胚」 | 前情证据:第2章「吞入腹中」 | 落点:正文 | 修改示例:改为本源精血\n"
           "===状态入账===\n"
           "- [物品] 破禁丹:炼成并交予苏清瑶 | 证据:「递出破禁丹」\n"
           "- 无效行不解析\n")
    items, lines = parse_scan(raw)
    assert len(items) == 1 and items[0].stars == 5 and items[0].kind == "物品"
    assert items[0].fix == "改为本源精血" and items[0].target == "正文"
    assert lines == ["- [物品] 破禁丹:炼成并交予苏清瑶 | 证据:「递出破禁丹」"]


def test_parse_scan_pass_verdict():
    from loom.continuity import parse_scan
    items, lines = parse_scan("===除虫报告===\n通过\n===状态入账===\n- 无\n")
    assert items == [] and lines == []


def test_scan_chapter_end_to_end(project):
    from conftest import FakeBackend, const
    from loom.continuity import scan_chapter
    from loom.paths import STATEBOOK_REL
    statebook.append_section(project, 2, ["- [物品] 远古药胚:已吞服消耗 | 证据:「吞入腹中」"])
    body = "江澈取出远古药胚,炼成破禁丹。\n\n他望向窗外。"
    be = FakeBackend(const("===除虫报告===\n通过\n===状态入账===\n- [物品] 破禁丹:炼成 | 证据:「炼成破禁丹」"))
    rep = scan_chapter(project, 4, body, be, hardfacts="【硬设定】测试块")
    # LLM 说通过,但确定性检测抓到药胚复活 → 合流后仍有 1 条
    assert len(rep["issues"]) == 1 and rep["issues"][0]["类别"] == "物品"
    # 入账 write-once 落盘
    assert "破禁丹" in (project / STATEBOOK_REL).read_text(encoding="utf-8")
    # 留痕落盘
    note = (project / ".审稿留痕/第4章.md").read_text(encoding="utf-8")
    assert "除虫报告" in note and "远古药胚" in note
    # prompt 组装:账本快照/硬设定/本章正文都在
    _, user = be.calls[0]
    assert "远古药胚" in user and "【硬设定】测试块" in user and "破禁丹" in user


def test_scan_chapter_llm_failure_still_reports_deterministic(project):
    from loom.continuity import scan_chapter
    statebook.append_section(project, 2, ["- [物品] 远古药胚:已吞服消耗 | 证据:「吞」"])

    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("网络炸了")

    rep = scan_chapter(project, 4, "取出远古药胚。", Boom())
    assert len(rep["issues"]) == 1     # LLM 挂了,确定性结果照出,绝不整体失败


def test_note_report_idempotent_rescan(project):
    from conftest import FakeBackend, const
    from loom.continuity import scan_chapter
    # 预置一个别的留痕小节:重扫绝不能动它
    note = project / ".审稿留痕/第4章.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("## 篇幅提醒(非阻断,供你定夺)\n- 本章超长\n", encoding="utf-8")
    statebook.append_section(project, 2, ["- [物品] 药胚:已吞服消耗 | 证据:「吞」"])
    be = FakeBackend(const("===除虫报告===\n通过\n===状态入账===\n- 无"))
    scan_chapter(project, 4, "取出药胚。", be)
    scan_chapter(project, 4, "取出药胚。", be)          # 重扫
    text = note.read_text(encoding="utf-8")
    assert text.count("## 除虫报告") == 1               # 替换不堆积
    assert "## 篇幅提醒" in text and "本章超长" in text  # 别的小节原样
