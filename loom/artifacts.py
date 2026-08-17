"""产物规格表:agent 化之后,护栏的挂点。

今天护栏挂在「棒」上(`agents.STEPS`):非空闸在每棒后、gate 挂编辑/润色师后、篇幅指令按
role 分支。写作 agent 化之后没有「棒」了——它自己决定先干什么、要不要回头重来——于是护栏
统一改挂在【产物提交】上。产物提交是 Loom 侧的一个工具,agent 绕不过去。

设计(docs/superpowers/specs/2026-08-16-loom-continual-harness-design.md §4):
- **本表是产物侧行为的单一真相**,同 `agents.STEPS` / `backends.PROVIDERS` 的老规矩:
  新增产物只改数据不改代码。
- 【红线】安全攸关字段(校验档、gate 挂接、篇幅契约)只住这张代码侧表,**绝不下放到用户可编辑的
  `agents/*.md`**——用户删一行 yaml 不该能让去AI味关卡消失。同 `agents.py:74` 那条。
- **产物名一个字不改**(与 `agents._PRODUCES` 逐一对应):它是 UI 点亮五个头像的依据、也是
  evals 棒级归因取产物的键。角色降级成「人格」是内部重构,对外仍是那五个人。
- `check_commit` **纯函数、绝不抛**:不合格的原因要能拼进下一轮 prompt 让 agent 重交(自愈),
  而不是像今天 `agents.py:773` 那样把整章跑动打断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import gates, paths
from .guard import STEP, Profile, chapter_profile, validate_output


@dataclass(frozen=True)
class GateSpec:
    """一道质量关卡的完整配置。今天散在 `agents._GATES` 的角色键元组里,现按【关卡名】立表
    ——挂点由 `ArtifactSpec.gate` 指过来,于是「哪件产物过哪道关卡」是产物表说了算。"""

    label: str
    critic_system: str
    revise_system: str
    reads: tuple[str, ...]     # 复审/回炉都要遵循的设定与方法论
    wants_prev: bool           # 复审时带上一章章末(看本章接没接住钩子)


GATES: dict[str, GateSpec] = {
    # 世界观/人物 双形态都列上:读文件时对缺失路径静默跳过,单文件老书/目录新书各取其一
    "质检": GateSpec(
        "质检", gates.CRITIC_质检, gates.REVISE_质检,
        ("skills/评估自检.md", paths.CHARS_REL, paths.CHARS_DIR_REL,
         paths.WORLD_REL, paths.WORLD_DIR_REL, paths.CARD_REL, paths.STATEBOOK_REL), True),
    "去AI味": GateSpec(
        "去AI味", gates.CRITIC_去AI味, gates.REVISE_去AI味,
        ("skills/去AI味.md", paths.FINGERPRINT_REL), False),
}


def _step_profile(_chapter_target: int) -> Profile:
    """短产物(锚点/细纲)的校验档:只挡空/拒答,各产物长短差异大、不卡长度。"""
    return STEP


# ── 篇幅预算(从 agents.py 搬来;agents 侧保薄别名,evalapi 的引用面不断) ──────────

def scene_range(chapter_target: int) -> tuple[int, int]:
    """章目标字数 →(最少场次, 最多场次)。场次预算的**单一真相**:
    scene_budget 的字符串形态由它派生,evals 的棒级体检也读它——两边永不漂。"""
    if chapter_target <= 1500:
        return (2, 3)
    if chapter_target <= 3000:
        return (3, 4)
    return (4, 6)


def outline_budget(chapter_target: int) -> int:
    """细纲自身的字数上限——按场次数派生,不再是写死的 450。

    先量后定(与 len_tolerance ±60%→±25% 同一套做法):真机 20 份细纲实测
    **20/20 全部超过旧的 450**,中位 ~1060、p90 1187、最大 1873;逐场骨头 230-370 字、
    固定开销(章首接钩/章末钩类型/爽点自检)约 200 字。450 从来没被满足过,
    它不是约束、只是一句被模型整体折扣掉的空话——同段还要求每场 5 要素 + 爆发点 +
    接钩 + 钩类型 + 爽点,算术上就写不下(spec §10.4)。

    取 200 + 350×最多场次:(2,3)档→1250、(3,4)档→1600、(4,6)档→2300,覆盖实测 p90。
    """
    return 200 + 350 * scene_range(chapter_target)[1]


def scene_budget(chapter_target: int) -> str:
    """章目标字数 → 细纲场次预算(喂 prompt 的字符串形态)。超长的真根因:大纲师不知道
    章目标,按惯例拆 3-6 场,写手照多场细纲每场写透 → 2000 字目标干出 6000+。"""
    lo, hi = scene_range(chapter_target)
    return f"拆 {lo}-{hi} 场"


def _outline_contract(chapter_target: int, _actual_chars: int = 0) -> str:
    """细纲的提交契约:篇幅的**结构闸**。

    「三管齐下」的第一管(agents.py:583):大纲师按章目标定场次并给每场标字数。
    今天这段话住在 `_length_hint` 的 role 分支里、混在自由 prompt 中;挂到提交工具的
    契约上之后,agent 想交细纲就必须照这个形状交——软话变成结构约束。
    """
    return (f"细纲本身 ≤{outline_budget(chapter_target)} 字。本章正文目标约 {chapter_target} 字——"
            f"按目标定场次:{scene_budget(chapter_target)},并给每场标注「约X字」的篇幅预算、"
            f"总和≈{chapter_target}。场次宁少勿多,别用多场细纲把写手的篇幅撑爆。")


# 正文标点要求。**写成硬契约,而不是指望模型跟着 prompt 的风格走**——真机实测过一次:
# agent 路每轮 prompt 小、协议脚手架的半角标点占比高,正文就渗出 70 个半角逗号
# (同一本书走流水线是 0 个)。中文网文正文里出现半角逗号是排版事故。
# 注:这条字符串会原样进 prompt,故句中的示例必须是【真的全角字形】,别跟着本文件的注释风格写半角。
_PUNCT = "中文标点一律用全角(示例:，。？——「」),正文里绝不出现半角逗号、分号、冒号。"


def _draft_contract(chapter_target: int, actual_chars: int = 0) -> str:
    """初稿的提交契约:「三管齐下」的第二管(agents._length_hint 的写手分支)。

    真机实测 2026-08-16:只有细纲那一管时,1200 字目标写出 3731 字初稿(3 倍)——
    单靠 assemble 里那句「本章正文目标约 N 字」压不住,得挂成提交条件。
    加上这条之后 A/B 实测三次:1154/1262/1171 字(均值 −0.4%),写手这一管是够的。
    """
    return (f"正文约 {chapter_target} 字(±25%),这是发布的硬性篇幅要求:细纲各场标了字数就照它写,"
            "写满即收、宁短勿长;不为凑字加铺垫,也不因写顺了就超篇。结尾留钩。" + _PUNCT)


def _revise_contract(chapter_target: int, actual_chars: int = 0) -> str:
    """改稿/终稿的提交契约:第三管(编辑/润色师的压缩授权)。

    **压缩授权是有条件的**——这是流水线 `_length_hint` 的「螺丝①」,我第一版搬过来时漏了它,
    真机付了代价:写手交的 1196 字(达标)被下游两道无条件「压回来」连压两次,终稿 −25%。

    规则:上游稿超标 1.2 倍才给授权,**并且把实测字数摆上桌**(LLM 自己数不准,不给数字
    那句话就没牙);达标则一个「压」字都不提——免得对合格稿瞎压。
    """
    if actual_chars and actual_chars > chapter_target * 1.2:
        over = round((actual_chars / chapter_target - 1) * 100)
        return (f"上游稿实测 {actual_chars} 字,目标 {chapter_target} 字(超 {over}%)——"
                "删冗余描写、重复信息与注水铺垫,压回目标量级,不动情节骨架;绝不扩写。" + _PUNCT)
    return (f"篇幅目标约 {chapter_target} 字(±25%),上游稿篇幅已达标——**保持原有篇幅量级**,"
            "只改该改的地方;既不要为了精简而删情节血肉,也不要扩写。" + _PUNCT)


@dataclass(frozen=True)
class ArtifactSpec:
    """一件可提交的产物 = 名字 + 谁产它 + 提交时校验哪一档。"""

    name: str
    persona: str = ""                                    # 空 = 不归任何人格的附属产物
    profile_fn: Callable[[int], Profile] = _step_profile  # 章目标字数 → 校验档
    gate: str = ""              # 提交后跑哪道质量关卡(空=不跑);标签同 agents._GATES 的人看名字
    deslop: bool = False        # 该关卡挂确定性预筛(aitell 句内翻转句 + fatigue 跨章雷同)
    foreshadow_after: bool = False   # 提交后扫伏笔悬空(纯本地、不回炉、不阻断)
    into_workspace: bool = True      # 提交后进本章工作区(下游人格读得到);False = 与稿子链隔离
    review_note: bool = False        # 提交后落 .审稿留痕/(盘外,给作者看,绝不进 learn 的 diff 源)
    is_final: bool = False           # 这件产物就是本章成稿:超长提醒查它,写章循环收到它即可收工
    outline_file: bool = False       # 提交后落 正文/.细纲/第N章.md(ADR 0008 的 WYSIWYG:作者可看可改)
    requires: tuple[str, ...] = ()   # 必须先有这些产物才准提交(不是工序顺序,是结构闸的前置条件)
    # (章目标字数, 上游稿实测字数) → 提交契约(渲进工具描述)
    contract_fn: Callable[[int, int], str] | None = None


_OUTLINE = "本章场景骨头(分镜细纲)"

# 顺序 = 建议的产出顺序(agent 可以不照办、可以回头重来;这里只是建议,不是拓扑约束)。
ARTIFACTS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec("本章设定锚点", "设定师"),
    ArtifactSpec("本章场景骨头(分镜细纲)", "大纲师", contract_fn=_outline_contract,
                 outline_file=True),
    # 三件正文稿都要求细纲在先。**细纲就是篇幅闸**——`_outline_contract` 的「拆 N 场 +
    # 每场约X字 + 总和≈目标」只有在细纲真被产出时才存在。真机 2026-08-16:agent 跳过细纲
    # 直接写,终稿 +35%。这不是把工序顺序焊回来(照样能回头重来:重提细纲 → 重提正文),
    # 是给结构闸补上它的前置条件。
    ArtifactSpec("本章初稿", "写手", chapter_profile, contract_fn=_draft_contract,
                 requires=(_OUTLINE,)),
    # 质检挂改稿:今天挂在编辑棒后,语义原样平移。伏笔悬空也在这儿——它读卡章纲,
    # 放到终稿的回炉链上只会空转(质检回炉改的是正文,清不掉卡章纲里的悬空伏笔)。
    ArtifactSpec("本章改稿", "编辑", chapter_profile, gate="质检", foreshadow_after=True,
                 contract_fn=_revise_contract, requires=(_OUTLINE,)),
    # 去AI味挂终稿,且【只有】它带确定性预筛:预筛抓的是机器腔,与质检抓的硬伤不是一回事,
    # 铺到质检上等于把两套口径混成一套。
    ArtifactSpec("本章终稿", "润色师", chapter_profile, gate="去AI味", deslop=True, is_final=True,
                 contract_fn=_revise_contract, requires=(_OUTLINE,)),
    # 审稿留痕:今天是编辑棒输出里用哨兵分隔的尾巴,靠 _edit_stream_filter 切串才不漏到屏幕上。
    # 提成独立产物后,「切漏一次就漏一次」这个风险面直接不存在。into_workspace=False 是它与
    # 稿子链的隔离闸——下游看不到它,于是它进不了终稿/快照/learn 的 diff 源。
    ArtifactSpec("本章改动留痕", into_workspace=False, review_note=True),
)

_BY_NAME = {s.name: s for s in ARTIFACTS}


def spec_for(name: str) -> ArtifactSpec:
    spec = _BY_NAME.get((name or "").strip())
    if spec is None:
        raise KeyError(f"未知产物:{name!r}(已注册:{'、'.join(_BY_NAME)})")
    return spec


def commit_contract(spec: ArtifactSpec, chapter_target: int = 0, actual_chars: int = 0) -> str:
    """该产物的提交契约(渲进提交工具的描述里)。没有契约的产物返回空串。

    `actual_chars`=当前上游稿的实测字数(有就传):压缩授权是**有条件**的,见 `_revise_contract`。
    """
    return spec.contract_fn(chapter_target, actual_chars) if spec.contract_fn else ""


def check_commit(spec: ArtifactSpec, text: str, *, chapter_target: int = 0) -> list[str]:
    """提交校验:返回不合格原因清单(空 = 放行)。**绝不抛**——原因回喂给 agent 让它重交。"""
    return validate_output(text, spec.profile_fn(chapter_target))
