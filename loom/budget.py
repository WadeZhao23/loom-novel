"""上下文预算(S6):长篇 30+ 章不崩的那一刀——全部确定性,零 LLM、零 tokenizer。

三类累积量的治法(评审定稿):
- 卡章纲 [AI回顾] / 世界观·人物卡 [AI补充·第N章]:只全文带**最近 WINDOW 章**,
  更早的确定性折叠为一行(人写的规划行/主体永远逐字保留——折的只是 AI 追加块)。
- 工作区:被取代的旧全文稿(初稿被改稿取代)不再下传 prompt——设定锚点/细纲逐字保留,
  「累积非纯链式」的防漂移初衷不受损;ledger 里仍存全量(续跑完整性与 prompt 预算解耦)。
- 写作指纹 learn 输出预算:随现有指纹体量增长(拆掉 1800 字隐形天花板——
  指纹只增不删,撞顶时每次 learn 都在逼模型压缩、挤掉 anchor)。

【护栏口径】保护槽永不折:写作指纹全文(anchor 所在)、硬设定逐字块、人写规划行。
签名(resume.sig_v2)吃原始文件,与本模块的折叠解耦——折叠是 (文件, 章号) 的纯函数,
文件变则签名变,续跑语义不受影响。不做 LLM 摘要压实(不可复现,砸 sha 记账)。
"""
from __future__ import annotations

import re

WINDOW = 8          # 近 N 章的 AI 追加块全文保留(与「伏笔提醒章距」默认同量级)
LEARN_FLOOR = 1800  # learn 输出预算地板(旧行为)
LEARN_CEIL = 4096   # 预算封顶:逼近它说明指纹该合并同义项了(warn 提示,不硬拦)

_CH_LINE = re.compile(r"^- 第(\d+)章[:：]")           # 卡章纲顶格章行(人写)
_RECAP = "[AI回顾]"
_SUPP_HEAD = re.compile(r"^## \[AI补充·第(\d+)章\]\s*$")  # 世界观/人物卡的追加块头


def fold_recaps(card_text: str, current_chapter: int, window: int = WINDOW) -> str:
    """卡章纲:远章(章号 < current-window)的 [AI回顾] 缩进子块折叠为一行摘要头。
    人写的顶格规划行永远逐字保留;近窗口章与无回顾章原样。"""
    cutoff = current_chapter - window
    if cutoff <= 0:
        return card_text
    out: list[str] = []
    cur_ch = 0
    folding = False
    for line in card_text.splitlines():
        m = _CH_LINE.match(line)
        if m:
            cur_ch = int(m.group(1))
            folding = False
            out.append(line)
            continue
        if line[:1] in (" ", "\t") and cur_ch and cur_ch < cutoff:
            s = line.strip()
            if _RECAP in s:
                head = s.split(_RECAP, 1)[-1].strip()
                out.append(f"    [AI回顾·已折叠] {head[:40]}…(远章,详见卡章纲原文)")
                folding = True
                continue
            if folding:
                continue   # 远章回顾块的后续缩进行(伏笔行等)一并折掉
        else:
            folding = False
        out.append(line)
    return "\n".join(out)


def fold_supplements(text: str, current_chapter: int, window: int = WINDOW) -> str:
    """世界观/人物卡:远章的 [AI补充·第N章] 整块折叠为一行占位。人写主体永远不动。"""
    cutoff = current_chapter - window
    if cutoff <= 0:
        return text
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        m = _SUPP_HEAD.match(line)
        if m:
            skipping = int(m.group(1)) < cutoff
            if skipping:
                out.append(f"## [AI补充·第{m.group(1)}章](已折叠,详见原文)")
                continue
        elif line.startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def drop_superseded(workspace: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """工作区进 prompt 前:全文稿(初稿/改稿)只留最新一份,锚点/细纲全保留。"""
    fulls = [i for i, (p, _) in enumerate(workspace) if ("初稿" in p or "改稿" in p)]
    drop = set(fulls[:-1])   # 只留最后一份全文稿
    return [item for i, item in enumerate(workspace) if i not in drop]


def learn_budget(old_fp_chars: int) -> int:
    """learn 输出预算:容得下「现有指纹 + 本次增量」,地板 1800、封顶 4096。"""
    return min(LEARN_CEIL, max(LEARN_FLOOR, int(old_fp_chars * 1.2) + 400))


def near_learn_ceiling(old_fp_chars: int) -> bool:
    return learn_budget(old_fp_chars) >= LEARN_CEIL
