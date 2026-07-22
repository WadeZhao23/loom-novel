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

from . import events
from .backends import Backend
from .parse import _PASS_PHRASES  # noqa: F401  判词解析共置 parse.py(S7),薄别名保引用面
from .parse import parse_verdict as _parse_verdict

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


def _merge_issues(primary: list[Issue], secondary: list[Issue]) -> list[Issue]:
    """合并两路硬伤(确定性检测器在前、LLM 复审在后),按(类别,证据/问题)去重。"""
    seen: set[tuple[str, str]] = set()
    out: list[Issue] = []
    for i in list(primary) + list(secondary):
        key = (i.kind, i.evidence or i.desc)
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out


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
    detector: Callable[[str], list[Issue]] | None = None,  # 确定性预筛(本地、不打分、出证据)
    critic_backend: Backend | None = None,  # 复审员走的后端(通常便宜模型);回炉仍用 backend
) -> GateResult:
    """评审→回炉,最多 rounds 轮。rounds<=0 视为关闭,原样返回。

    detector(若给):每轮在当前稿上跑一遍**本地确定性检测**(如 AI腔对比句式),与 LLM 复审的硬伤
    合流——既驱动回炉(rounds≥2),又在末轮一起进残留留痕(rounds=1 默认只诊断)。回炉后下一轮在
    新稿上重扫,擦干净了自然归零。检测器只读不写、不打分,守 ADR-0006「不阻断」。

    critic_backend(若给):复审(纯诊断)走它——通常是便宜模型;回炉(写作)仍走 backend。
    """
    if rounds <= 0:
        return GateResult(draft, 0, True, [])

    text = draft
    last: list[Issue] = []
    for r in range(1, rounds + 1):
        progress(events.gate_start(label, owner_role, r))
        critic_user = (
            f"## 设定与标准\n{knowledge}\n\n## 待复审的本章稿\n{text}\n\n"
            "## 你的任务\n按上面的标准,只挑硬伤、给证据,严格按格式输出;无硬伤只回一行「通过」。"
        )
        verdict = (critic_backend or backend).complete(critic_system, critic_user, max_chars=600)
        issues = _parse_verdict(verdict)
        if detector is not None:
            issues = _merge_issues(detector(text), issues)

        if not issues:
            progress(events.gate_pass(label, owner_role, r))
            return GateResult(text, r, True, [])

        last = issues
        progress(events.gate_issues(label, owner_role, r, [i.as_dict() for i in issues]))

        if r == rounds:
            break  # 最后一轮只诊断、不再回炉

        progress(events.gate_revise(label, owner_role, r))
        issue_lines = "\n".join(
            f"- {i.kind}:{i.desc}" + (f"(证据:「{i.evidence}」)" if i.evidence else "")
            for i in issues
        )
        revise_user = (
            f"## 设定与方法论\n{knowledge}\n\n## 本章稿\n{text}\n\n"
            f"## 复审挑出的硬伤(只修这些,别动没问题的地方)\n{issue_lines}\n\n"
            "## 你的任务\n针对性修好上面的硬伤,只输出修订后的整章正文,不要解释、不要列清单。"
        )
        chunk_cb = lambda d, role=owner_role: progress(events.agent_chunk(role, d))
        text = backend.complete(revise_system, revise_user, max_chars=max_chars, on_chunk=chunk_cb)

    progress(events.gate_exhausted(label, owner_role, rounds, [i.as_dict() for i in last]))
    return GateResult(text, rounds, False, last)


# ── Rubric 文件加载(rubric 存储在 skills/*.md,运行时加载) ─────────────────


def _read_rubric(project_root: Path, filename: str) -> str:
    """从 project_root/skills/ 目录读取 rubric 文件内容,不存在返回空串。"""
    p = project_root / "skills" / filename
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def load_critic(project_root: Path, label: str) -> str:
    """加载复审员(critic)rubric。label='质检' → skills/质检rubric.md"""
    return _read_rubric(project_root, f"{label}rubric.md")


def load_revise(project_root: Path, label: str) -> str:
    """加载回炉者(revise)rubric。label='质检' → skills/质检revise.md"""
    return _read_rubric(project_root, f"{label}revise.md")


# ── 向后兼容:模块级常量 ─────────────────────────────────────────────
# 运行时(agents.py)已改为从 skills/ 文件加载 rubric;
# 以下常量留作既有测试和 evals/ 代码的向后兼容,不再被 agents.py 引用。

CRITIC_质检 = (
    "你是**独立质检员**,只诊断、不改写。依据给你的《评估自检》标准 + 这本书的设定"
    "(人物卡/世界观/卡章纲/状态账本/上一章),只挑这几类**硬伤**:\n"
    "① 人物 OOC(违背性格/立场/已知信息/人物硬约束的底线身段) ② 设定漂移(违反世界观/金手指/已埋伏笔)"
    " ③ 断钩子(没接住上一章章末的钩子) ④ 整章没有任何爽点/收获"
    " ⑤ 信息边界(双向):a) 角色表现得知道他不在场/未发生的事;"
    "b) 角色展示越境界/越阅历的认知,正文却没有一句来源交代(金手指/情报/前世记忆)——缺归因同样算硬伤"
    " ⑥ 物品/状态连续性:使用了状态账本或前文回顾里已标「消耗/失去」的物品,或人物状态与账本不符"
    " ⑦ 时间连续性:时间词与前情时刻粒度不符(如昨夜发生的事说成昨日)。\n"
    "**不挑**:错别字、标点、文风、AI 腔(都不归你)。**宁缺毋滥**,没把握的不算硬伤。\n\n"
    "输出(严格):无硬伤只回一行「通过」;有则每条一行 `- 类别 | 一句话问题 | 证据:\"原文短引\"`,最多 8 条。"
    "不要输出正文、不要解释。"
)

REVISE_质检 = (
    "你是**写手**。拿到本章稿 + 一份硬伤清单,只针对这些硬伤就地修好,产出修订后的整章正文。"
    "别大改没问题的地方,别改文风,篇幅保持原稿量级,绝不扩写。只输出整章正文本身,不要解释、不要小标题。"
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
    "(体现作者个人特征的不规整/口头禅别擦平)。篇幅保持原稿量级,绝不扩写。只输出整章正文本身,不要解释。"
)
