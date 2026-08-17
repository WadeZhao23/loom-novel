"""护栏换挂点:质量关卡 / 留痕 / 伏笔,从「挂在棒上」改成「挂在产物提交上」。

spec 2026-08-16 §4。语义一条不改,只是挂点从 `agents.STEPS` 换到 `artifacts.ARTIFACTS`
——因为 agent 化之后没有「棒」了,但「提交」这道门 agent 绕不过去。
"""
from __future__ import annotations

import dataclasses

from loom import paths, write_tools
from loom.config import load_config

_稿 = "他没说话。火把的光爬上矿壁,血顺着指缝往下滴。" * 6   # 过 chapter_profile 的实字门槛


def _sess(project, backend=None, *, outline=True, **cfg_over):
    if outline:
        _seed_outline(project)
    cfg = dataclasses.replace(load_config(project), **cfg_over)
    return write_tools.Session(root=project, chapter_n=1, config=cfg, backend=backend)


class _RecordingBackend:
    """记下每次调用的 system,好断言「哪道关卡真的跑了」。"""

    def __init__(self, reply: str = "通过") -> None:
        self.reply = reply
        self.systems: list[str] = []

    def complete(self, system, user, *, max_chars=None, on_chunk=None):
        self.systems.append(system)
        return self.reply


def test_提交改稿跑质检关卡(project):
    """§4:质检今天挂「编辑棒后」→ 换挂「提交改稿」。默认轮数=1 只诊断不回炉,
    但复审员必须真的被调到,否则等于关卡静默消失。"""
    be = _RecordingBackend()
    sess = _sess(project, be)
    write_tools.run_tool(sess, "提交", {"产物": "本章改稿", "内容": _稿})
    assert any("独立质检员" in s for s in be.systems)


def test_提交终稿跑去AI味关卡(project):
    be = _RecordingBackend()
    sess = _sess(project, be)
    write_tools.run_tool(sess, "提交", {"产物": "本章终稿", "内容": _稿})
    assert any("独立审读" in s for s in be.systems)


def test_提交初稿不跑任何关卡(project):
    """关卡只挂改稿/终稿两处。初稿挂上去会平白多烧两次调用,且语义上也不对
    ——今天就是编辑棒后才质检。"""
    be = _RecordingBackend()
    sess = _sess(project, be)
    write_tools.run_tool(sess, "提交", {"产物": "本章初稿", "内容": _稿})
    assert be.systems == []


def test_轮数为0时关卡整个关掉(project):
    """ADR-0006:`[gate]轮数=0` = 关。作者关了就一次复审都不该发。"""
    be = _RecordingBackend()
    sess = _sess(project, be, gate_rounds=0)
    write_tools.run_tool(sess, "提交", {"产物": "本章终稿", "内容": _稿})
    assert be.systems == []


def test_关卡回炉后进工作区的是回炉稿(project):
    """轮数≥2 才自动回炉。回炉产出的新稿必须取代原稿进工作区,
    否则关卡白跑——下游拿到的还是没修的那份。"""
    be = _RecordingBackend()
    # 复审挑出一条硬伤 → 触发回炉;回炉这一次 complete 返回的就是新稿
    be.reply = "- 人物OOC | 主角性格不符 | 证据:\"他笑了\""
    sess = _sess(project, be, gate_rounds=2)
    write_tools.run_tool(sess, "提交", {"产物": "本章改稿", "内容": _稿})
    assert sess.workspace, "改稿该进工作区"
    assert sess.workspace[-1][1] != _稿, "进工作区的应是回炉后的稿,不是原稿"


def test_关卡跑满仍残留的硬伤追加进审稿留痕(project):
    """ADR-0006「不阻断」:跑满轮数仍有残留 → 保留最好稿 + 残留写进留痕交作者定夺,
    绝不拦着不让出稿。"""
    be = _RecordingBackend("- 人物OOC | 主角性格不符 | 证据:\"他笑了\"")
    sess = _sess(project, be)
    write_tools.run_tool(sess, "提交", {"产物": "本章改稿", "内容": _稿})
    note = paths.review_note_path(project, 1)
    assert note.is_file() and "人物OOC" in note.read_text(encoding="utf-8")


def test_提交细纲没标每场字数会发提醒(project):
    """字数五螺丝④:细纲缺「约X字」标注 → warn(写手篇幅要失控了)。纯提醒,不阻断。"""
    evs: list = []
    sess = _sess(project)
    sess.progress = evs.append
    write_tools.run_tool(sess, "提交", {"产物": "本章场景骨头(分镜细纲)",
                                       "内容": "分镜一:验伤。分镜二:遇敌。分镜三:绝境爆发。"})
    assert any("约X字" in str(e) for e in evs)
    assert sess.workspace, "只是提醒,细纲照样进工作区——绝不阻断"


def test_提交终稿超长进留痕提醒(project):
    """字数五螺丝③:终稿超目标 1.25 倍 → 留痕提醒可能注水。ADR-0006:纯提示、绝不拦稿。"""
    sess = _sess(project, gate_rounds=0)
    write_tools.run_tool(sess, "提交", {"产物": "本章终稿", "内容": "他没说话。" * 400})
    assert "篇幅提醒" in paths.review_note_path(project, 1).read_text(encoding="utf-8")
    assert sess.workspace, "超长只留痕,稿照样进工作区"


def test_没有细纲就不许提交正文稿(project):
    """真机 2026-08-16:agent 整个跳过细纲直接写,终稿 1619 字 / 目标 1200 → +35%。

    细纲**就是篇幅闸**——`_outline_contract` 的「拆 N 场 + 每场约X字 + 总和≈目标」
    只有在细纲真被产出时才存在。没有它,篇幅没有任何结构性约束。

    §3.2 说顺序是建议不是拓扑,这条不违背它:这不是「工序顺序」,是**结构闸的前置条件**,
    而且照样可以回头重来(重提细纲 → 重提正文)。
    """
    sess = _sess(project, outline=False)
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章初稿", "内容": _稿})
    assert ev.get("error") and "细纲" in ev["error"]
    assert sess.workspace == []


def test_有细纲之后正文稿放行(project):
    sess = _sess(project, outline=False)
    write_tools.run_tool(sess, "提交", {"产物": "本章场景骨头(分镜细纲)",
                                       "内容": "一(约600字):验伤。二(约600字):遇敌。"})
    ev = write_tools.run_tool(sess, "提交", {"产物": "本章初稿", "内容": _稿})
    assert ev.get("t") == "committed"


def test_作者手写的细纲文件也算数(project):
    """WYSIWYG:作者自己在 `正文/.细纲/` 写好了细纲、没让 agent 产——那也是细纲,不该拦着他。"""
    paths.outline_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.outline_path(project, 1).write_text("一(约1200字):作者手写。", encoding="utf-8")
    sess = _sess(project, outline=False)
    assert write_tools.run_tool(sess, "提交", {"产物": "本章终稿", "内容": _稿}).get("t") == "committed"


def test_提交细纲落盘成可看可改的文件(project):
    """ADR 0008 的 WYSIWYG:细纲落 `正文/.细纲/第N章.md`,作者能看能改。

    真机实测 2026-08-16:agent 路跑完一章,`正文/.细纲/` 目录压根不存在——同一本书走流水线
    是有的。护栏搬家时漏了这一条,等于在 agent 模式下把这个功能删了。
    """
    sess = _sess(project, outline=False)
    write_tools.run_tool(sess, "提交", {"产物": "本章场景骨头(分镜细纲)",
                                       "内容": "一(约400字):验伤。二(约400字):遇敌。三(约400字):爆发。"})
    p = paths.outline_path(project, 1)
    assert p.is_file() and "验伤" in p.read_text(encoding="utf-8")


def test_作者改过的细纲会顶到agent面前(project):
    """WYSIWYG 的另一半:细纲文件已存在(多半是作者手改过)→ 这一轮必须让 agent 看见它、按它来,
    而不是自顾自重新拆一版。「你改了它,重写本章就按你的来」是 ADR 0008 的承诺。"""
    from loom import writeloop
    paths.outline_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.outline_path(project, 1).write_text("一(约600字):作者手改的场次。", encoding="utf-8")
    sess = _sess(project, outline=False)
    _, user = writeloop._assemble(sess, [])
    assert "作者手改的场次" in user


def test_细纲编码损坏不拖累assemble出稿(project):
    """终审④:`UnicodeDecodeError` 继承自 `ValueError` 不是 `OSError`,裸 `except OSError`
    抓不到它——作者用 GBK 存过 `.细纲/第N章.md`,`_existing_outline` 就会直接抛穿,agent 化
    每一轮 `_assemble` 都会踩到,整章跑不了。docstring 承诺「读不了就当没有」,这里钉住。"""
    from loom import writeloop
    paths.outline_path(project, 1).parent.mkdir(parents=True, exist_ok=True)
    paths.outline_path(project, 1).write_bytes(b"\xff\xfe")   # 非法 UTF-8,读它必抛 UnicodeDecodeError
    sess = _sess(project, outline=False)
    _, user = writeloop._assemble(sess, [])   # 不该抛
    assert "作者已经给了本章细纲" not in user   # 读不了就当没有,不当成「作者给了细纲」注进 prompt


def test_提交留痕落到审稿留痕文件(project):
    """§4:留痕从「编辑棒输出里用哨兵分隔的尾巴」变成独立产物,提交即落 .审稿留痕/。"""
    sess = _sess(project)
    write_tools.run_tool(sess, "提交", {"产物": "本章改动留痕", "内容": "把「殊不知」删了,改成动作收尾。"})
    note = paths.review_note_path(project, 1)
    assert note.is_file() and "殊不知" in note.read_text(encoding="utf-8")


def _seed_outline(project, n: int = 1) -> None:
    """铺一份细纲。正文稿的提交前置条件(篇幅结构闸)要求它在先——除非这条测试测的正是那个条件。"""
    from loom import paths
    p = paths.outline_path(project, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("一(约600字):验伤。二(约600字):遇敌。", encoding="utf-8")
