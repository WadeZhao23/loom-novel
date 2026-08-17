"""写章通道的工具注册表(与 partner_tools 成对:伙伴通道 vs 写章通道)。

spec 2026-08-16 §3.2/§4:五工序 agent 化之后,今天 `_build_user_prompt` 全量拼进 prompt 的
那几坨(设定/硬设定/状态账本/上一章/工作区)改成【按需取的只读工具】,产物落盘改成【提交工具】
——护栏就挂在提交上,agent 绕不过去。
"""
from __future__ import annotations

from loom import paths, write_tools
from loom.config import load_config


def _sess(project, chapter_n: int = 1, *, outline=True):
    if outline:   # 正文稿的提交前置条件要求细纲在先(篇幅结构闸)
        p = paths.outline_path(project, chapter_n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("一(约600字):验伤。二(约600字):遇敌。", encoding="utf-8")
    return write_tools.Session(root=project, chapter_n=chapter_n, config=load_config(project))


def test_契约段列出注册表里的每一个工具():
    """注册表单一真相(同 partner_tools.render_contract):契约段与分发从同一处派生。

    prompt 里写着的工具 ≠ 实际能跑的工具,是这类文本协议最容易腐烂的地方——
    partner_tools 用「注册表渲染契约」根治过一次,这里照搬。
    """
    c = write_tools.render_contract(chapter_target=2000)
    for name in write_tools.REGISTRY:
        assert name in c, f"契约段漏了工具 {name}"


def test_工具清单里不出现用冒号开头的展示行():
    """真机 2026-08-16:契约把每个工具渲成 `- 用:取人格 | 参数:角色 | 说明`,
    模型照抄这个**展示格式**发出 `用:取人格 | 参数:编辑` ——解析器认不出这个工具名,
    0 工具、空转到撞轮数上界,整章报废。

    展示行长得像协议行,模型就会仿写它。清单里一律不许出现「用:」开头的行,
    真正的调用格式由下面那段范例负责教。
    """
    for line in write_tools.render_contract(2000).splitlines():
        stripped = line.strip().lstrip("-*# ").strip()
        if stripped.startswith("用:") or stripped.startswith("用："):
            assert "\n" not in line   # 范例块里的独立一行可以;清单行不行
            assert "|" not in line, f"清单行长得像协议行,模型会仿写它:{line!r}"


def test_契约段给出真实的多行调用范例():
    """光说「格式是一行用:工具名,后接键:值」不够——真机证明模型会去抄它看得见的那个形状。
    给一段照抄就能跑的范例。"""
    c = write_tools.render_contract(2000)
    assert "用:取人格\n角色:" in c, "缺一个可直接照抄的两行调用范例"


def test_契约段带上产物表与细纲的场次预算():
    """§4 篇幅那一行:artifacts 的提交契约要真的流进 prompt,不能只躺在表里。"""
    c = write_tools.render_contract(chapter_target=2000)
    assert "本章终稿" in c            # 产物表进了契约
    assert "拆 3-4 场" in c           # 细纲的结构闸也进了


def test_提交合格产物进工作区(project):
    sess = _sess(project)
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章设定锚点", "内容": "灵气复苏第三年,主角觉醒逆息体质。"})
    assert ev["t"] == "committed"
    assert sess.workspace == [("本章设定锚点", "灵气复苏第三年,主角觉醒逆息体质。")]


def test_查硬设定逐字取到世界观里的力量体系(project):
    """§4:hardfacts 从「wants_hardfacts 注入」换成只读工具,但**逐字直送**的语义不变
    ——境界/专名一经复述就漂(ADR 0010:F~SSS 凭空多出「一阶0级」)。"""
    (project / "外置大脑/世界观/力量体系.md").write_text(
        "## 力量体系\n凡阶→灵阶→天阶,每阶九品。", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "查硬设定", {})
    assert "凡阶→灵阶→天阶" in ev["text"]


def test_查硬设定绝不吐冰山真相(project):
    """ADR 0010 唯一的硬红线:反转段逐字喂写手 = 提前抖包袱。deny 压过 allow。"""
    (project / "外置大脑/世界观/力量体系.md").write_text(
        "## 力量体系\n凡阶→灵阶→天阶。", encoding="utf-8")
    (project / "外置大脑/世界观/冰山真相.md").write_text(
        "## 冰山真相\n师姐才是幕后黑手。", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "查硬设定", {})
    # 先确认工具真的取到了东西——否则「不含幕后黑手」在空串上恒真,是条假绿
    assert "凡阶→灵阶→天阶" in ev["text"]
    assert "幕后黑手" not in ev["text"]


def test_读上一章去掉标题只给正文体(project):
    """跨章衔接读的是【手改后的】正文,不是 .原稿 快照(CONTEXT「AI 原稿快照」词条)。
    标题不进:它绝不参与文风(ADR 0009)。"""
    (project / "正文").mkdir(exist_ok=True)
    (project / "正文/第1章.md").write_text("# 废矿里的火光\n他没说话。\n", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project, chapter_n=2), "读上一章", {})
    assert "他没说话" in ev["text"]
    assert "废矿里的火光" not in ev["text"]


def test_看工作区列出已提交产物(project):
    sess = _sess(project)
    write_tools.run_tool(sess, "提交", {"产物": "本章设定锚点", "内容": "灵气复苏第三年,主角觉醒逆息体质"})
    ev = write_tools.run_tool(sess, "看工作区", {})
    assert "本章设定锚点" in ev["text"] and "灵气复苏第三年,主角觉醒逆息体质" in ev["text"]


def test_取人格带上该角色的系统提示词与它要读的设定(project):
    """人格 = 今天的 agents/<角色>.md(系统提示词 + reads 清单)。取人格把两者一起给出来,
    于是「写手只准读写作指纹+网文大神+文风参考」这条 voice 侧边界原样成立。"""
    from loom.agents import load_agent
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "写手"})
    assert load_agent(project, "写手").system_prompt[:30] in ev["text"]
    assert "写作指纹" in ev["text"]


def test_取人格绝不吐冰山真相(project):
    """终审②critical:ADR 0010 红线的主语是写手——流水线时代靠「每棒各发一次调用」的结构
    隔离(写手 reads 本就不含世界观)。agent 化后 `_handle_persona` 的返回值进 writeloop 的
    trail、每一轮都重新拼进 prompt——「取人格:设定师」取到的冰山真相原文会绕过写手自己的
    reads 边界,躺进它落字那次调用的上下文里。deny 必须把这条路也堵上。"""
    (project / "外置大脑/世界观/力量体系.md").write_text(
        "## 力量体系\n凡阶→灵阶→天阶,每阶九品。", encoding="utf-8")
    (project / "外置大脑/世界观/冰山真相.md").write_text(
        "## 冰山真相\n师姐才是幕后黑手。", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "设定师"})
    # 先确认工具真的取到了东西——否则「不含幕后黑手」在空串上恒真,是条假绿
    assert "凡阶→灵阶→天阶" in ev["text"]
    assert "幕后黑手" not in ev["text"]


def test_取人格单文件形态也不吐冰山真相(project):
    """终审①critical:`_deny_spoiler_items` 只做了两件事——文件名(stem)命中整份剔除
    (目录形态,如 冰山真相.md)+ `_drop_spoiler_subsections` 剔 ### 及更深的反转子块。
    但单文件形态的冰山真相是 H2(## 冰山真相,见 loom/sample/agents/设定师.md 的 reads
    形状、draft.py 一键起稿模板的输出、journey.py 的 slot_order)——stem 不命中(文件名是
    「世界观」)、H2 又不被 ### 那道剔除逻辑认,原文原样喂进写手落字那次调用,破 ADR 0010。
    这里照 sample 那份把 reads 换成单文件形态复现。"""
    (project / "agents/设定师.md").write_text(
        "---\nname: 设定师\nreads:\n  - 外置大脑/世界观.md\nreads_first_chapter:\n"
        "produces: 本章设定锚点\n---\n你是设定师。", encoding="utf-8")
    (project / "外置大脑/世界观.md").write_text(
        "# 世界观\n\n## 力量体系\n凡阶→灵阶→天阶,每阶九品。\n\n"
        "## 冰山真相\n师姐才是幕后黑手。\n", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "设定师"})
    # 先确认工具真的取到了正常设定——否则「不含幕后黑手」在空串上恒真,是条假绿
    assert "凡阶→灵阶→天阶" in ev["text"]
    assert "幕后黑手" not in ev["text"]


def test_取人格冰山真相后紧跟一级标题不该被连坐吞掉(project):
    """终审②minor:`_drop_spoiler_h2_sections` 的 skip 此前是 bool,只有下一个「##」能
    复位、「#」(H1)复位不了——世界观里「## 冰山真相」后紧跟「# 第二部分」,第二部分整块
    被连坐吞掉。同文件里 `_drop_spoiler_subsections` 早就是按层级复位的正确写法,这里补齐
    同一口径:任何 <= 命中层级的标题(含更浅的 H1)都该结束 skip。"""
    (project / "agents/设定师.md").write_text(
        "---\nname: 设定师\nreads:\n  - 外置大脑/世界观.md\nreads_first_chapter:\n"
        "produces: 本章设定锚点\n---\n你是设定师。", encoding="utf-8")
    (project / "外置大脑/世界观.md").write_text(
        "## 力量体系\n凡阶→灵阶→天阶,每阶九品。\n\n"
        "## 冰山真相\n师姐才是幕后黑手。\n\n"
        "# 第二部分\n主线继续,这段不该被连坐吞掉。\n", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "设定师"})
    assert "凡阶→灵阶→天阶" in ev["text"]
    assert "幕后黑手" not in ev["text"]
    assert "主线继续,这段不该被连坐吞掉" in ev["text"]


def test_取人格卡章纲标题带真相不该被株连消失(project):
    """终审①important:`_drop_spoiler_h2_sections` 此前无条件套在每一个 read 条目上——
    卡章纲(paths.CARD_REL)不在世界观目录内,作者/导入器写出「## 第12章 · 真相揭露」这种
    非规范但合法的章节标题(导入器支持这种形态入库),整节因标题撞上反转关键词被静默剔除,
    大纲师写第12章时看不到这章要干什么。同一批修复里 stem-deny 收窄的判词正是「不该套到
    世界观以外的条目上」——H2 deny 在上一层又犯了一次,这里把它也收进世界观条目
    (`in_world_dir or rel == paths.WORLD_REL`)。"""
    (project / "外置大脑/卡章纲.md").write_text(
        "## 第12章 · 真相揭露\n主角识破师姐伪装,当场反杀夺回令牌。\n", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "大纲师"})
    assert "当场反杀夺回令牌" in ev["text"]


def test_取人格老书人物卡标题带秘密不该被株连消失(project):
    """同上:老书单文件人物卡(paths.CHARS_REL)也不在世界观目录内,标题「## 配角 · 秘密
    情人」撞上反转关键词却不该被 H2 deny 整节剔除——人物卡不是反转段。"""
    (project / "agents/设定师.md").write_text(
        "---\nname: 设定师\nreads:\n  - 外置大脑/人物卡.md\nreads_first_chapter:\n"
        "produces: 本章设定锚点\n---\n你是设定师。", encoding="utf-8")
    (project / "外置大脑/人物卡.md").write_text(
        "## 配角 · 秘密情人\n- 底线:绝不公开身份\n", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "设定师"})
    assert "绝不公开身份" in ev["text"]


def test_取人格人物卡文件名含秘密不该被株连消失(project):
    """终审②important:此前 stem-deny 对该人格的**每一个** read 条目都做 stem 匹配,
    包括 外置大脑/人物/、skills/题材 ——作者建一个「配角·秘密情人.md」,文件名撞上
    「秘密」这个反转关键词,会被整份静默剔除,人物卡凭空消失。对比 `_hardfacts_for`:
    它的 stem-deny 只作用在 外置大脑/世界观/ 目录内。这里把 stem-deny 收窄到同一范围。"""
    (project / "外置大脑/人物/配角·秘密情人.md").write_text(
        "# 配角 · 秘密情人\n- 底线:绝不公开身份\n", encoding="utf-8")
    ev = write_tools.run_tool(_sess(project), "取人格", {"角色": "设定师"})
    assert "秘密情人" in ev["text"]


def test_产物名写错回可回喂的错误而不是炸掉(project):
    """agent 会把产物名写错(错别字/自己造名)。这必须是一条能自纠的错误,不是崩掉整章。"""
    sess = _sess(project)
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章大纲", "内容": "灵气复苏第三年,主角觉醒逆息体质"})
    assert ev.get("error")
    assert "本章场景骨头(分镜细纲)" in ev["error"]   # 错误里要带上有效名字,否则它改不对
    assert sess.workspace == []


def test_细纲编码损坏时提交前置产物给可读错误而不是抛穿(project):
    """终审③:`_have` 判「有没有细纲」直接 `p.read_text(encoding="utf-8")`,没有 try 保护。
    `UnicodeDecodeError` 继承自 `ValueError` 不是 `OSError`——细纲编码损坏时,虽然会被
    `run_tool` 的 `except (..., ValueError, ...)` 兜住不至于崩整章,但回喂给 agent 的会是
    一条读不懂的 codec 报错,不是「先提交细纲」这种它能自纠的话。"""
    sess = _sess(project, outline=False)
    p = paths.outline_path(project, 1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xfe")   # 非法 UTF-8,读它必抛 UnicodeDecodeError
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章初稿", "内容": "灵气复苏第三年，主角觉醒逆息体质。"})
    assert ev.get("error")
    assert "先提交细纲" in ev["error"]   # 细纲当「没有」处理,给可自纠的话,不是裸 codec 报错


def test_留痕提交成功但不进工作区(project):
    """§4:留痕与稿子链的隔离闸,运行时这一侧。into_workspace=False 意味着下游人格
    看不到它 → 它进不了终稿、进不了 .原稿 快照、也进不了 learn 的 diff 源。"""
    sess = _sess(project)
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章改动留痕", "内容": "把「殊不知」删了,改成动作收尾。"})
    assert ev["t"] == "committed"
    assert sess.workspace == []


def test_看工作区不下传被改稿取代的旧全文稿(project):
    """复用 budget.drop_superseded 的老口径:全文稿只留最新一份,锚点/细纲逐字全保留。

    agent 化后工作区可能累积更多轮稿(它能回头重来),这条比流水线时代更要紧——
    不然 prompt 里会同时躺着三份同一章正文。
    """
    import dataclasses
    cfg = dataclasses.replace(load_config(project), chapter_chars=100)   # 压低门槛,免得测试要写 240 字
    _sess(project)   # 铺细纲:正文稿的提交前置条件
    sess = write_tools.Session(root=project, chapter_n=1, config=cfg)
    write_tools.run_tool(sess, "提交", {"产物": "本章设定锚点", "内容": "锚点:主角觉醒逆息体质,濒死才能爆发。"})
    write_tools.run_tool(sess, "提交", {"产物": "本章初稿", "内容": "初稿甲" * 20})
    write_tools.run_tool(sess, "提交", {"产物": "本章改稿", "内容": "改稿乙" * 20})
    text = write_tools.run_tool(sess, "看工作区", {})["text"]
    assert "改稿乙" in text
    assert "初稿甲" not in text      # 被改稿取代 → 不下传
    assert "逆息体质" in text        # 锚点逐字保留


def test_提交空产物被拒且不进工作区_错误可回喂(project):
    """§4 第一行:非空闸从「raise 中断整章」改成「不落 + 回喂重交」。

    run_tool 返回 error 事件而不是抛——这条错误要能拼进下一轮 prompt 让 agent 自己改好。
    """
    sess = _sess(project)
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章初稿", "内容": ""})
    assert ev.get("error")
    assert sess.workspace == []


def test_伏笔悬空提醒不被终稿提交的截断纪律抹掉(project):
    """终审③critical:`_note_path` 是「本次跑动首写即清」的截断纪律入口,但伏笔悬空走
    `agents._flag_stale_foreshadow → _save_gate_remaining`,那条路直接 append、不经过它。

    gate_rounds=0 时提交改稿不跑质检关卡(`_note_touched` 仍是 False),伏笔提醒 append 完
    之后,提交终稿时 `_note_path` 首次写入会把整个留痕文件截断——提醒被抹掉,作者永远看不到。
    `_handle_commit` 现在在扫伏笔之前先摸一下 `_note_path(sess)`,把「首写即清」提前触发,
    伏笔提醒活过之后的终稿提交。
    """
    import dataclasses

    from loom.config import load_config

    # 卡章纲:第1章埋了一条伏笔,推进距离(=3)超过 foreshadow_distance(=1)才判悬空
    卡章纲 = project / "外置大脑/卡章纲.md"
    卡章纲.parent.mkdir(parents=True, exist_ok=True)
    卡章纲.write_text(
        "- 第1章:占位。\n"
        "    - [埋设] 一块来历不明的青玉牌。\n",
        encoding="utf-8")

    cfg = dataclasses.replace(load_config(project), gate_rounds=0, foreshadow_distance=1)
    sess = _sess(project, chapter_n=3, outline=False)
    sess.config = cfg
    p = paths.outline_path(project, 3)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("一(约600字):验伤。二(约600字):遇敌。", encoding="utf-8")

    write_tools.run_tool(sess, "提交", {"产物": "本章改稿", "内容": "改稿正文，写满对白与动作。" * 15})
    note_path = paths.review_note_path(project, 3)
    assert "伏笔悬空" in note_path.read_text(encoding="utf-8"), "改稿提交后伏笔悬空提醒应该已经落盘"

    write_tools.run_tool(sess, "提交", {"产物": "本章终稿", "内容": "终稿正文，写满对白与动作。" * 15})
    assert "伏笔悬空" in note_path.read_text(encoding="utf-8"), "终稿提交不该截断掉之前的伏笔悬空提醒"
