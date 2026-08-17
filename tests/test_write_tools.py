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


def test_产物名写错回可回喂的错误而不是炸掉(project):
    """agent 会把产物名写错(错别字/自己造名)。这必须是一条能自纠的错误,不是崩掉整章。"""
    sess = _sess(project)
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章大纲", "内容": "灵气复苏第三年,主角觉醒逆息体质"})
    assert ev.get("error")
    assert "本章场景骨头(分镜细纲)" in ev["error"]   # 错误里要带上有效名字,否则它改不对
    assert sess.workspace == []


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
