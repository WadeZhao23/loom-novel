"""产物规格表:spec 2026-08-16 §4「护栏从棒换到产物提交」的代码化。

今天护栏挂在「棒」上(agents.STEPS),agent 化后没有棒了,挂到【产物提交】上——
产物提交是 Loom 侧的工具,agent 绕不过去。本文件钉住这张表的两条根本约定。
"""
from __future__ import annotations

from loom import agents, artifacts


def test_五个人格的主产物名与今天五棒逐一对应():
    """§3.2 承诺:角色从「工序」降级为「人格」,但【产物名一个字不改】。

    产物名是 UI 点亮五个头像的依据(events.agent_done(role, produces))、也是 evals
    棒级归因取产物的键。名字一变,README 的五个人、前端进度、eval 基线同时断。
    """
    assert [s.name for s in artifacts.ARTIFACTS if s.persona] == list(agents._PRODUCES.values())


def test_空产物提交被拦下并返回可回喂的原因():
    """§4 第一行:非空闸从「raise 中断整章」改成「不落盘 + 回喂让它重交」。

    check_commit 是纯函数、绝不抛——原因要能拼进下一轮 prompt 让 agent 自愈,
    而不是像今天 agents.py:773 那样把整章跑动打断。
    """
    reasons = artifacts.check_commit(artifacts.spec_for("本章设定锚点"), "", chapter_target=2000)
    assert reasons


def test_gate_从棒换到产物提交():
    """§4:质检今天挂「编辑棒后」→ 改挂「提交改稿」;去AI味挂「润色师后」→ 改挂「提交终稿」。

    确定性预筛(aitell 句内翻转句 + fatigue 跨章雷同)仍只随去AI味走,不铺到质检上
    ——两者管的不是一回事(硬伤 vs 机器腔),口径别混。
    """
    assert artifacts.spec_for("本章改稿").gate == "质检"
    assert artifacts.spec_for("本章终稿").gate == "去AI味"
    assert artifacts.spec_for("本章初稿").gate == ""
    assert artifacts.spec_for("本章终稿").deslop is True
    assert artifacts.spec_for("本章改稿").deslop is False


def test_伏笔悬空扫描挂在提交改稿后():
    """§4:今天挂编辑棒后(StepSpec.foreshadow_after),换挂「提交改稿」后。

    刻意【不】挂终稿:它读的是卡章纲,质检回炉改的是正文,放在回炉链上只会空转。
    """
    assert artifacts.spec_for("本章改稿").foreshadow_after is True
    assert [s.name for s in artifacts.ARTIFACTS if s.foreshadow_after] == ["本章改稿"]


def test_审稿留痕是独立产物_与稿子链物理隔离():
    """§4:今天编辑棒把「改稿 + 哨兵 + 留痕」拌在一个输出里,靠 _edit_stream_filter 流式切串,
    切漏一次留痕就漏到作者屏幕上。换成独立产物后 agent 分两次提交,两者物理分开。

    隔离靠 into_workspace=False:留痕不进本章工作区 → 下游人格看不到它 → 它进不了
    终稿、进不了 .原稿 快照、也就进不了 learn 的 diff 源(CONTEXT「绝不进 learn 的 diff 源」)。
    """
    note = artifacts.spec_for("本章改动留痕")
    assert note.persona == ""            # 附属产物,不点亮任何头像
    assert note.gate == ""               # 留痕不进质量关卡(它不是稿)
    assert note.into_workspace is False
    assert all(s.into_workspace for s in artifacts.ARTIFACTS if s.persona)


def test_细纲提交契约带场次预算与每场字数标注():
    """§4:篇幅从「_length_hint 按 role 分支的一句软话」换成【提交工具的契约】。

    字数五螺丝的教训(agents.py:583 那段 docstring):软话压不住篇幅,结构闸才压得住。
    契约挂在工具上,agent 想提交细纲就必须照着这个形状交。
    """
    c = artifacts.commit_contract(artifacts.spec_for("本章场景骨头(分镜细纲)"), chapter_target=2000)
    assert "拆 3-4 场" in c
    assert "约X字" in c


def test_写手与编辑的篇幅要求也进提交契约():
    """§4「篇幅三管齐下」的另两管。今天写手的「±20% 硬性篇幅」与编辑/润色师的「压缩授权」
    住在 `_length_hint` 的 role 分支里,agent 化后 role 分支没人调了——必须挂到对应产物的
    提交契约上。

    真机实测 2026-08-16:缺了这两管,1200 字目标写出 3731 字初稿(3 倍)。
    """
    draft = artifacts.commit_contract(artifacts.spec_for("本章初稿"), 1200)
    assert "1200" in draft and "25%" in draft
    for name in ("本章改稿", "本章终稿"):
        c = artifacts.commit_contract(artifacts.spec_for(name), 1200)
        assert "1200" in c, f"{name} 的契约里要有目标字数"
    # 压缩授权【有没有】要看上游稿超没超标,不是无条件的——那两条判据见下面两条测试


def test_正文类产物的契约要求全角标点():
    """真机实测 2026-08-16(样例书第 3 章,两条路对跑):

        流水线稿:全角标点 181,半角逗号 0
        agent 稿:全角标点  80,半角逗号 **70**

    根因不是模板(`写手.md` 自己就是半角为主),是**每轮 prompt 的构成**:流水线的 user prompt
    里塞着上一章正文 + 指纹 anchor(大量全角散文)把风格带住了;agent 路每轮 prompt 小得多,
    协议脚手架的半角占比高,风格就渗进正文。

    靠「风格熏陶」不可靠 → 写进契约当硬要求。中文网文正文出现半角逗号是排版事故。
    """
    for name in ("本章初稿", "本章改稿", "本章终稿"):
        c = artifacts.commit_contract(artifacts.spec_for(name), 1200)
        assert "全角" in c, f"{name} 的契约没要求全角标点"


def test_达标的上游稿不给压缩授权():
    """真机 A/B 2026-08-16:写手三次产出 1154/1262/1171 字(目标 1200,均值 −0.4%)——
    **写手没问题**;但终稿两次都是 −25%。根因是我把流水线 `_length_hint` 的「螺丝①」
    漏掉了:那边只在【上游稿超标 1.2 倍】时才给压缩授权,「达标不提,免对合格稿瞎压」。
    无条件说「压回来」,一份合格稿连压两道就成了 −25%。
    """
    for name in ("本章改稿", "本章终稿"):
        ok = artifacts.commit_contract(artifacts.spec_for(name), 1200, actual_chars=1196)
        assert "压" not in ok, f"{name}:上游已达标,不该出现压缩指令"


def test_超标的上游稿才把实测字数摆上桌():
    """超标时要给出【实测数字】——LLM 自己数不准,不摆数字那句压缩授权就没牙。"""
    over = artifacts.commit_contract(artifacts.spec_for("本章终稿"), 1200, actual_chars=3731)
    assert "3731" in over and "压" in over


def test_篇幅容差是正负25():
    """作者定的:±25% 以内都可接受(2026-08-16)。"""
    c = artifacts.commit_contract(artifacts.spec_for("本章初稿"), 1200)
    assert "25%" in c


def test_场次预算搬进artifacts后agents侧仍是同一个函数():
    """`_scene_range` 是场次预算的单一真相(agents.py:49 的老约定),evals 经 evalapi 也读它。

    搬进 artifacts 之后 agents 侧保薄别名(同 gates.py:18 `_PASS_PHRASES` 的做法)——
    引用面不断,且两边永远是同一个对象,不可能漂。
    """
    assert agents._scene_range is artifacts.scene_range
    assert agents.outline_budget is artifacts.outline_budget


def test_合格产物放行():
    ok = artifacts.check_commit(
        artifacts.spec_for("本章设定锚点"),
        "涉及设定:灵气复苏第三年,主角觉醒「逆息」体质,只能在濒死时爆发。",
        chapter_target=2000,
    )
    assert ok == []
