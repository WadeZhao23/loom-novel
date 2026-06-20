"""质量关卡(gate):一道「独立复审 → 回炉重写」的循环,挂在某一棒产出之后。

设计守 CONTEXT「不打分不阻断」/ ADR-0002「过检测不当 KPI」:
- gate **只挑具体硬伤**(带原文证据),不产任何分数、不碰检测器指标;
- 判据是「硬伤清单空不空」,不是「分数达不达标」;
- 跑满 rounds 仍有残留 → **不硬阻断**:保留当前最好稿,把残留交回(写进审稿留痕),照常往下走。

引擎无关:进度只通过 progress(event) 回调发出,CLI / WebUI 各自渲染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .backends import Backend

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


@dataclass
class Issue:
    """一条硬伤:类别 + 一句话问题 + 原文证据短引。"""
    kind: str
    desc: str
    evidence: str = ""

    def as_dict(self) -> dict:
        return {"类别": self.kind, "问题": self.desc, "证据": self.evidence}


@dataclass
class GateResult:
    text: str                 # 最终稿(可能回炉过)
    rounds: int               # 实际跑了几轮诊断
    resolved: bool            # 末轮是否已无硬伤
    remaining: list[Issue] = field(default_factory=list)  # 跑满仍残留(交回留痕)


def _parse_verdict(raw: str) -> list[Issue]:
    """解析复审员输出 → 硬伤清单。无硬伤(含'通过')返回空列表。

    宽容解析:每条形如 `- 类别 | 问题 | 证据:"…"`;只认以 - 开头的行。
    """
    issues: list[Issue] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith(("-", "·", "•")):
            continue
        body = s.lstrip("-·• ").strip()
        if not body or body == "无硬伤":
            continue
        parts = [p.strip() for p in body.split("|")]
        kind = parts[0] if parts else "硬伤"
        desc = parts[1] if len(parts) > 1 else (parts[0] if parts else body)
        ev = ""
        if len(parts) > 2:
            ev = parts[2].split("证据:", 1)[-1].split("证据：", 1)[-1].strip().strip('"“”')
        issues.append(Issue(kind=kind, desc=desc, evidence=ev))
    return issues


def run_gate(
    backend: Backend,
    *,
    label: str,            # 给人看的名字,如 "质检" / "去AI味"
    owner_role: str,       # 这道 gate 挂在哪一棒之后(渲染时归到它名下)
    critic_system: str,    # 复审员系统提示词(只诊断、出清单)
    revise_system: str,    # 回炉者系统提示词(按清单就地修)
    draft: str,
    knowledge: str,        # 复审/回炉都要遵循的设定+方法论(已拼好)
    produces: str,         # 回炉产物名(给流式事件用)
    rounds: int,
    max_chars: int,
    progress: Progress = _noop,
) -> GateResult:
    """评审→回炉,最多 rounds 轮。rounds<=0 视为关闭,原样返回。"""
    if rounds <= 0:
        return GateResult(draft, 0, True, [])

    text = draft
    last: list[Issue] = []
    for r in range(1, rounds + 1):
        progress({"type": "gate_start", "label": label, "role": owner_role, "round": r})
        critic_user = (
            f"## 设定与标准\n{knowledge}\n\n## 待复审的本章稿\n{text}\n\n"
            "## 你的任务\n按上面的标准,只挑硬伤、给证据,严格按格式输出;无硬伤只回一行「通过」。"
        )
        verdict = backend.complete(critic_system, critic_user, max_chars=600)
        issues = _parse_verdict(verdict)

        if not issues:
            progress({"type": "gate_pass", "label": label, "role": owner_role, "round": r})
            return GateResult(text, r, True, [])

        last = issues
        progress({
            "type": "gate_issues", "label": label, "role": owner_role, "round": r,
            "issues": [i.as_dict() for i in issues],
        })

        if r == rounds:
            break  # 最后一轮只诊断、不再回炉

        progress({"type": "gate_revise", "label": label, "role": owner_role, "round": r})
        issue_lines = "\n".join(
            f"- {i.kind}:{i.desc}" + (f"(证据:「{i.evidence}」)" if i.evidence else "")
            for i in issues
        )
        revise_user = (
            f"## 设定与方法论\n{knowledge}\n\n## 本章稿\n{text}\n\n"
            f"## 复审挑出的硬伤(只修这些,别动没问题的地方)\n{issue_lines}\n\n"
            "## 你的任务\n针对性修好上面的硬伤,只输出修订后的整章正文,不要解释、不要列清单。"
        )
        chunk_cb = lambda d, role=owner_role: progress(
            {"type": "agent_chunk", "role": role, "delta": d})
        text = backend.complete(revise_system, revise_user, max_chars=max_chars, on_chunk=chunk_cb)

    progress({
        "type": "gate_exhausted", "label": label, "role": owner_role, "rounds": rounds,
        "issues": [i.as_dict() for i in last],
    })
    return GateResult(text, rounds, False, last)


# ── 两道内置 gate 的复审/回炉提示词(rubric 仍以 skills/*.md 为准,这里只是「诊断模式」外壳) ──

CRITIC_质检 = (
    "你是**独立质检员**,只诊断、不改写。依据给你的《评估自检》标准 + 这本书的设定"
    "(人物卡/世界观/卡章纲/上一章),只挑这几类**硬伤**:\n"
    "① 人物 OOC(违背性格/立场/已知信息) ② 设定漂移(违反世界观/金手指/已埋伏笔)"
    " ③ 断钩子(没接住上一章章末的钩子) ④ 整章没有任何爽点/收获。\n"
    "**不挑**:错别字、标点、文风、AI 腔(都不归你)。**宁缺毋滥**,没把握的不算硬伤。\n\n"
    "输出(严格):无硬伤只回一行「通过」;有则每条一行 `- 类别 | 一句话问题 | 证据:\"原文短引\"`,最多 5 条。"
    "不要输出正文、不要解释。"
)

REVISE_质检 = (
    "你是**写手**。拿到本章稿 + 一份硬伤清单,只针对这些硬伤就地修好,产出修订后的整章正文。"
    "别大改没问题的地方,别改文风,只输出整章正文本身,不要解释、不要小标题。"
)

CRITIC_去AI味 = (
    "你是**独立审读**,只诊断、不改写。依据给你的《去AI味》黑名单,挑出本章终稿里**具体命中**的"
    "AI 腔词句:套话头尾、空洞万能词、过度连接词、直接点名情绪、黑名单词、句式过整齐。\n"
    "**护栏**:若某处不规整/口头禅是【写作指纹】带来的作者个人特征(像他本人),**不算 AI 腔**,别挑。\n\n"
    "输出(严格):无命中只回一行「通过」;有则每条一行 `- 类别 | 命中词句 | 证据:\"原文短引\"`,最多 6 条。"
    "不要输出正文、不要解释。"
)

REVISE_去AI味 = (
    "你是**润色师**。按命中清单把这些 AI 腔擦掉:删套话头尾、万能词换具体细节、拆焊死的连接词、"
    "情绪点名改画面动作。两条护栏:**保意**(不改剧情/人物/事实,只改腔调)、**保留写作指纹**"
    "(体现作者个人特征的不规整/口头禅别擦平)。只输出整章正文本身,不要解释。"
)
