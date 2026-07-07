"""连续性除虫:确定性双检测(零 LLM)+ LLM 扫描(Task 4 补)。守只报告不改稿。"""
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
