"""S6 上下文预算:确定性折叠/丢弃的单元 + 30+ 章 prompt 回放断言(评审要求的真护栏)。"""
from __future__ import annotations

from loom import paths
from loom.agents import run_pipeline
from loom.budget import WINDOW, drop_superseded, fold_recaps, fold_supplements, learn_budget
from loom.config import load_config
from loom.gates import CRITIC_去AI味, CRITIC_质检
from tests.conftest import FakeBackend

# ---------- 单元:折叠与丢弃 ----------

def _card(n_ch: int) -> str:
    lines = ["# 卡章纲", ""]
    body = "本章发生了很多值得记住的事,句子写得够长以便折叠预览截不到尾部。"
    for i in range(1, n_ch + 1):
        lines.append(f"- 第{i}章:第{i}章的人写规划行")
        lines.append(f"    [AI回顾] 摘要:{body}尾标TAILREC{i}。")
        lines.append(f"    - [埋设] 第{i}章的伏笔FS{i}")
    return "\n".join(lines)


def test_fold_recaps_window_and_human_lines():
    card = _card(30)
    folded = fold_recaps(card, 31)
    for i in range(31 - WINDOW, 31):          # 近窗口章:回顾全文在(含尾部)
        assert f"TAILREC{i}" in folded
    assert "TAILREC1" not in folded and "FS1" not in folded  # 远章:全文与伏笔行折掉,只留 40 字预览头
    assert "[AI回顾·已折叠]" in folded
    for i in range(1, 31):                     # 人写规划行永远逐字保留
        assert f"第{i}章的人写规划行" in folded
    assert len(folded) < len(card)
    assert fold_recaps(card, 5) == card        # 没超窗口 → 原样


def test_fold_supplements_keeps_human_body():
    text = ("# 世界观\n\n## 力量体系\n- 凡→化神\n\n"
            "## [AI补充·第1章]\n远章补充SUPP1\n\n## [AI补充·第29章]\n近章补充SUPP29\n")
    folded = fold_supplements(text, 31)
    assert "SUPP1" not in folded and "(已折叠" in folded
    assert "SUPP29" in folded and "凡→化神" in folded


def test_drop_superseded_keeps_anchors_and_latest_draft():
    ws = [("本章设定锚点", "锚"), ("本章场景骨头(分镜细纲)", "纲"),
          ("本章初稿", "DRAFT_OLD"), ("本章改稿", "DRAFT_NEW")]
    out = drop_superseded(ws)
    assert [p for p, _ in out] == ["本章设定锚点", "本章场景骨头(分镜细纲)", "本章改稿"]


def test_learn_budget_grows_with_fingerprint():
    assert learn_budget(300) == 1800            # 地板不变(旧行为)
    assert learn_budget(3000) == 4000           # 随体量长:3000*1.2+400
    assert learn_budget(99999) == 4096          # 封顶


# ---------- 回放断言:30+ 章工程下的 prompt 有界且保护槽逐字在场 ----------

def test_long_book_prompt_replay(project):
    toml = project / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"章节字数" = 800', '"章节字数" = 120'),
                    encoding="utf-8")
    (project / paths.CARD_REL).write_text(_card(30), encoding="utf-8")
    # 上一章(第30章)与指纹 anchor、硬设定逐字块
    paths.chapter_path(project, 30).parent.mkdir(parents=True, exist_ok=True)
    paths.chapter_path(project, 30).write_text("# 三十\n\n前章结尾留了倒计时钩。\n", encoding="utf-8")
    fp = project / paths.FINGERPRINT_REL
    fp.write_text(fp.read_text(encoding="utf-8") + "\n> 这是我的anchor签名句ANCHORX。\n", encoding="utf-8")
    wv = project / paths.WORLD_DIR_REL / "力量体系.md"   # 脚手架已是目录形态:硬设定按文件名直送
    wv.write_text(wv.read_text(encoding="utf-8") + "\n- 凡境→蜕凡HARDFACTX\n", encoding="utf-8")

    seq = {"i": 0}

    def responder(s, u):
        if s in (CRITIC_质检, CRITIC_去AI味):
            return "通过"
        seq["i"] += 1
        return f"第{seq['i']}棒产出STEP{seq['i']},长度足够过每棒非空闸。" * 2

    be = FakeBackend(responder)
    run_pipeline(project, 31, be, load_config(project), resume=False)
    users = {}   # 每棒最后一次 user prompt(role 探测:调用顺序固定)
    order = ["设定师", "大纲师", "写手", "编辑", "质检critic", "润色师", "去AI味critic", "标题"]
    for name, (_, u) in zip(order, be.calls):
        users[name] = u

    outliner = users["大纲师"]
    assert f"TAILREC{30}" in outliner and "TAILREC1" not in outliner, "近窗口回顾全文、远章折叠"
    assert "第1章的人写规划行" in outliner, "人写规划行永远在场"
    writer = users["写手"]
    assert "凡境→蜕凡HARDFACTX" in writer, "硬设定逐字保护槽"
    assert "这是我的anchor签名句ANCHORX" in writer, "anchor 例句逐字保护槽"
    polisher = users["润色师"]
    assert "STEP3" not in polisher, "被改稿取代的初稿(第3棒)不再下传润色师"
    assert "STEP4" in polisher, "最新全文稿(改稿)必须在场"
    assert "STEP1" in polisher and "STEP2" in polisher, "锚点/细纲仍逐字保留(累积非纯链式)"
    # 总量有界:大纲师 prompt 不应把 30 章回顾全文塞进来(粗界:折叠后 < 原卡章纲全文塞入的量)
    assert len(outliner) < len(_card(30)) + 3000