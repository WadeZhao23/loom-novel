"""连续性除虫:确定性双检测(零 LLM)+ LLM 扫描(Task 4 补)。守只报告不改稿。"""
from loom import statebook
from loom.continuity import BugItem, detect_consumed_reuse, detect_rule_drift, merge_items,     detect_time_mismatch, detect_char_continuity


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


def test_consumed_reuse_ignores_keyword_in_evidence_quote():
    # 变更描述段是「获得」(未消耗),证据引文里的「耗尽」不该误判为消耗类
    book = {2: [("物品", "铁剑:获得 | 证据:「他耗尽力气拾起铁剑」")]}
    assert detect_consumed_reuse(book, 4, "他挥舞铁剑。") == []


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




# ── G1: 时间连续性检测 ────────

def _time_book():
    return {1: [('时钟', '当夜深夜:深夜突破至炼气三层 | 证据:xxx')],
            2: [('时钟', '翌日清晨:离开宗门前往遗迹 | 证据:xxx')],
            3: [('物品', '玉佩:已破碎 | 证据:坠落')]}


def test_time_mismatch_no_clock_skip():
    """第一章无前情时钟,应跳过不报。"""
    items = detect_time_mismatch(_time_book(), 1, '当日,他起得很早。')
    assert items == []


def test_time_mismatch_time_flow_forward():
    """前章翌日清晨,本章当夜 → 合理(同一天不同时段)"""
    items = detect_time_mismatch(_time_book(), 3, '当夜,月色如洗。')
    assert items == []


def test_time_mismatch_time_reverse():
    """前章翌日清晨,本章昨日 → 矛盾(倒流)"""
    items = detect_time_mismatch(_time_book(), 3, '昨夜之事他已不再计较。')
    assert len(items) == 1 and '倒流' in items[0].desc


def test_time_mismatch_no_timeword():
    """本章开头没时间词 → 跳过"""
    items = detect_time_mismatch(_time_book(), 3, '他推开窗户,外面正在下雨。')
    assert items == []


def test_time_mismatch_three_days_after_then_next_day():
    """前章三日后,本章次日 → 倒流矛盾"""
    book = {1: [('时钟', '三日后:抵达遗迹 | 证据:跋涉')]}
    items = detect_time_mismatch(book, 2, '次日,他们开始挖掘。')
    assert len(items) == 1 and items[0].stars == 4


# ── G1: 人物出场关联检测 ────────

def _char_book():
    return {1: [('状态', '江澈:炼气巅峰 | 证据:入定'),
                ('状态', '苏清瑶:闭关冲击金丹 | 证据:闭生死关')],
            2: [('状态', '江澈:炼气巅峰(无重伤) | 证据:完好')]}


def test_char_continuity_no_special_state():
    """角色无特殊状态,正常出场不报"""
    items = detect_char_continuity(_char_book(), 3, '江澈推开院门。', {'江澈', '苏清瑶', '陈墨'})
    assert items == []


def test_char_continuity_special_state_unresolved():
    """角色前情特殊状态(闭关),本章出现但未交代变化"""
    items = detect_char_continuity(_char_book(), 3, '苏清瑶从丹房走出,面色如常。', {'江澈', '苏清瑶'})
    assert len(items) == 1 and '闭关' in items[0].desc


def test_char_continuity_alias():
    """角色以简称出现,前情有特殊状态"""
    items = detect_char_continuity(_char_book(), 3, '清瑶的丹炉已冷却多日。', {'江澈', '苏清瑶'})
    assert len(items) == 1 and 'alias' in items[0].desc or '简称' in items[0].desc
    

def test_char_continuity_other_char_not_in_book():
    """角色不在账本里 → 跳过"""
    items = detect_char_continuity(_char_book(), 3, '陈墨扛着剑走来。', {'江澈', '苏清瑶'})
    assert items == []

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
    assert rep["ledger_written"] is True
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


def test_scan_chapter_rescan_ledger_not_overwritten(project):
    """重扫已入账的章:write-once 不覆盖,ledger_written 明示 False(供 webui 提示用户手动合并)。"""
    from conftest import FakeBackend, const
    from loom.continuity import scan_chapter
    be = FakeBackend(const("===除虫报告===\n通过\n===状态入账===\n- [物品] 铁剑:获得 | 证据:「拾起铁剑」"))
    rep1 = scan_chapter(project, 4, "他拾起铁剑。", be)
    assert rep1["ledger_written"] is True
    rep2 = scan_chapter(project, 4, "他拾起铁剑。", be)          # 重扫同一章
    assert rep2["state_lines"] and rep2["ledger_written"] is False


class ScriptBackend:
    """测试用后端:固定脚本响应,记录调用。"""
    def __init__(self, script): self.script = list(script); self.calls = []
    def complete(self, system, user, *, max_chars=None, on_chunk=None):
        assert self.script, "脚本耗尽"
        out = self.script.pop(0); self.calls.append((system, user))
        if on_chunk and out: on_chunk(out)
        return out


def test_pipeline_auto_scan_and_state_block(project):
    """终稿后自动除虫(事件+留痕+入账);第二章的写手 prompt 收到「当前状态」块;开关可关。"""
    from loom.agents import run_pipeline
    from loom.config import load_config, save_config

    _PROSE = ("寅时三刻,铜锣未响。崇祯睁开眼,乾清宫的帐顶陈旧而熟悉。"
              "他记得煤山那棵歪脖子树,也记得魏忠贤的笑。这一次他要先出手。")
    full = ["锚点:崇祯睁眼,阉党当政。", "分镜一:验身。分镜二:召对。",
            _PROSE, _PROSE + "补一句。", _PROSE + "收束。", "煤山",
            # 第 7 个响应给除虫扫描(终稿后附赠调用)
            "===除虫报告===\n通过\n===状态入账===\n- [物品] 尚方剑:获得 | 证据:「取剑」"]

    cfg = load_config(project)
    cfg.gate_rounds = 0
    cfg.chapter_chars = 100
    save_config(project, cfg)
    cfg = load_config(project)
    assert cfg.continuity_scan is True        # 默认开

    seen: list[dict] = []
    run_pipeline(project, 1, ScriptBackend(list(full)), cfg, progress=seen.append)
    assert any(e["type"] == "debug_report" for e in seen)
    assert "尚方剑" in (project / "外置大脑/状态账本.md").read_text(encoding="utf-8")
    assert "除虫报告" in (project / ".审稿留痕/第1章.md").read_text(encoding="utf-8")

    # 第二章:写手 prompt 带「当前状态」块(账本已有第1章)
    be2 = ScriptBackend(list(full))
    run_pipeline(project, 2, be2, cfg)
    writer_user = be2.calls[2][1]             # 设定师/大纲师/写手 → 第3次
    assert "当前状态" in writer_user and "尚方剑" in writer_user
    assert "当前状态" not in be2.calls[0][1]  # 设定师不吃状态块(wants_hardfacts 同批才吃)

    # 关掉开关:不再有除虫调用(脚本 6 个恰好耗尽)+ 无 debug_report
    cfg.continuity_scan = False
    save_config(project, cfg)
    assert "除虫" in (project / "loom.toml").read_text(encoding="utf-8")
    cfg = load_config(project)
    assert cfg.continuity_scan is False
    seen3: list[dict] = []
    run_pipeline(project, 3, ScriptBackend(list(full[:6])), cfg, progress=seen3.append)
    assert not any(e["type"] == "debug_report" for e in seen3)


def test_regen_outline_gets_state_block(project):
    """重生成细纲:大纲师(wants_hardfacts)也要吃「当前状态」块——防细纲让已消耗物品复活。"""
    from loom.agents import regen_outline
    from loom.config import load_config, save_config
    from loom import statebook
    statebook.append_section(project, 1, ["- [物品] 远古药胚:已吞服消耗 | 证据:「吞入腹中」"])
    cfg = load_config(project)
    cfg.gate_rounds = 0
    save_config(project, cfg)
    be = ScriptBackend(["锚点:接第1章,阉党反扑。", "分镜一:朝会。分镜二:遇刺。章末钩(危机迫近)。"])
    regen_outline(project, 2, be, load_config(project))
    assert len(be.calls) == 2
    setter_user, outliner_user = be.calls[0][1], be.calls[1][1]
    assert "当前状态" not in setter_user            # 设定师不吃(非 wants_hardfacts)
    assert "当前状态" in outliner_user and "远古药胚" in outliner_user   # 大纲师吃到


def test_debug_endpoint_and_studio_tab(project, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import FakeBackend, const
    from loom import server as srv, usecases
    from loom.fsutil import atomic_write_text

    atomic_write_text(project / "正文/第1章.md", "# 第1章\n\n江澈取出尚方剑。")
    be = FakeBackend(const("===除虫报告===\n通过\n===状态入账===\n- [物品] 尚方剑:获得 | 证据:「取出尚方剑」"))
    monkeypatch.setattr(usecases, "get_backend", lambda cfg: be)
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: None)
    c = TestClient(srv.app, base_url="http://127.0.0.1")
    r = c.post("/api/chapter/debug", json={"root": str(project), "chapter": 1})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["issues"] == [] and r.json()["state_lines"]

    st = c.get(f"/api/studio?root={project}").json()
    assert st["statebook"] and st["statebook"][0]["n"] == 1
    assert st["statebook"][0]["lines"][0]["kind"] == "物品"

    # 章不存在 → 400
    r2 = c.post("/api/chapter/debug", json={"root": str(project), "chapter": 99})
    assert r2.status_code == 400


def test_gate_critic_receives_statebook_content(project):
    """质检 gate 的复审 knowledge 里必须含账本内容(paths.STATEBOOK_REL 在 _GATES["编辑"] reads 清单里)。
    防这份清单被误删而不红:写一条真实账本行,gate_rounds=1 跑一遍,断言 critic 收到的 user 含该行。"""
    from loom import gates
    from loom.agents import run_pipeline
    from loom.config import load_config, save_config

    statebook.append_section(project, 1, ["- [物品] 苍云剑:获得 | 证据:「拾起苍云剑」"])

    _PROSE = ("寅时三刻,铜锣未响。崇祯睁开眼,乾清宫的帐顶陈旧而熟悉。"
              "他记得煤山那棵歪脖子树,也记得魏忠贤的笑。这一次他要先出手。")

    def responder(system, user):
        if system == gates.CRITIC_质检 or system == gates.CRITIC_去AI味:
            return "通过"   # 无硬伤,gate 一轮即过,不触发回炉
        return _PROSE

    from conftest import FakeBackend
    be = FakeBackend(responder)
    cfg = load_config(project)
    cfg.gate_rounds = 1
    cfg.chapter_chars = 100
    save_config(project, cfg)
    cfg = load_config(project)

    run_pipeline(project, 2, be, cfg)

    critic_calls = [u for s, u in be.calls if s == gates.CRITIC_质检]
    assert critic_calls, "质检 critic 未被调用——gate_rounds=1 应触发一轮复审"
    assert any("苍云剑" in u for u in critic_calls)


def test_statebook_listed_in_state(project):
    # scaffold 自带账本模板 → OPTIONAL_BRAIN 命中即列(与 立项卡/文风参考 同款语义)
    from loom.usecases import project_state
    state = project_state(project)
    rels = []
    for b in state["brain"]:
        if "rel" in b:
            rels.append(b["rel"])
        elif "children" in b:
            rels.extend(c["rel"] for c in b["children"])
    assert "外置大脑/状态账本.md" in rels
