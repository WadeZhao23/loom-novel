"""书名注入:模型必须知道这本书叫什么(立项即铺底 §1 根因一)。"""
from loom.agents import regen_outline, run_pipeline
from loom.config import load_config, save_config

_OUTLINE_RUN = ["锚点:崇祯睁眼在乾清宫。", "分镜一:验身。分镜二:召王承恩。章末钩(危机迫近)。"]


class ScriptBackend:
    """按脚本顺序吐产出,记录 (system, user);耗尽即炸。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, system, user, *, max_chars=None, on_chunk=None):
        assert self.script, "脚本耗尽:调用次数超出预期"
        out = self.script.pop(0)
        self.calls.append((system, user))
        if on_chunk and out:
            on_chunk(out)
        return out


def test_title_in_every_step_prompt(project):
    be = ScriptBackend(_OUTLINE_RUN)
    regen_outline(project, 1, be, load_config(project))
    assert len(be.calls) == 2  # 设定师 + 大纲师
    for _, user in be.calls:
        assert user.startswith("# 你要写的是《测试书》第 1 章。")


_PROSE = ("寅时三刻,铜锣未响。崇祯睁开眼,乾清宫的帐顶陈旧而熟悉。"
          "他记得煤山那棵歪脖子树,记得白绫勒进脖颈的凉,也记得城破前夜没人来救驾。"
          "这一次,他先要魏忠贤的命。")   # ≥40 实字:过 chapter_profile(100) 的终稿闸


def test_title_change_invalidates_resume(project):
    full = ["锚点:崇祯睁眼在乾清宫,阉党当政。", "分镜一:验身。分镜二:召王承恩。章末钩(危机迫近)。",
            _PROSE, _PROSE + "补一句悬念。", _PROSE + "收束更冷。", "煤山"]
    cfg = load_config(project)
    cfg.gate_rounds = 0          # 关 gate:免去质检/去AI味的额外调用,脚本可控
    cfg.chapter_chars = 100      # 终稿闸降到 max(40, 12)=40 实字,测试文本可控
    save_config(project, cfg)
    cfg = load_config(project)
    run_pipeline(project, 1, ScriptBackend(list(full)), cfg)

    # 原样续跑:五棒签名全命中、零工序调用;标题重生成是既有行为,恒有且仅有这一次
    idle = ScriptBackend(["煤山"])
    run_pipeline(project, 1, idle, cfg)
    assert len(idle.calls) == 1
    assert "# 你要写的是" not in idle.calls[0][1]   # 这唯一一次是标题生成,不是工序

    cfg.title = "换了个书名"
    save_config(project, cfg)
    cfg = load_config(project)
    redo = ScriptBackend(list(full))   # 大纲师有细纲文件走 WYSIWYG 旁路,脚本富余没关系(不要求耗尽)
    run_pipeline(project, 1, redo, cfg)
    assert len(redo.calls) >= 2, "改书名必须让续跑签名失配、从设定师重跑"
    assert "《换了个书名》" in redo.calls[0][1]
