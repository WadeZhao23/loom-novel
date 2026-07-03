"""写作指纹的两件事:seed(从样本提炼初版)、learn(从你的手改重新蒸馏)。

铁律(见 ADR 0001/0002/0005):
- 学习信号【只能是你的手改】,绝不用 AI 自己的输出回写。
- 手改先做【句级对齐】(ADR 0005):同位置改写归为「改写候选」、纯增删归为「改剧情」,
  比行级 diff 干净;模型先逐对判定改写/改情节,再只从改写里学文风,忽略剧情纠错与去AI味。
- 指纹是【累积演进的一份】:既有规则 / anchor 默认全保留,learn 只增量并入(新增 / 合并近义 /
  仅当本次证据直接矛盾时才改写那一条),绝不推倒重写、绝不整段删掉你攒下的文风——否则换个模型
  重蒸馏就把「你」磨没了(用户实报过的 bug);规则超 40 条靠合并近义收敛,不靠丢偏好(见 _LEARN_SYSTEM)。
- 保留若干条逐字 anchor 例句,模型不许改写——防止反复蒸馏磨成中庸腔;anchor 须是纯文风、不含剧情专名。

引擎不依赖前端:进度通过 progress(event: dict) 回调发出。
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Callable

from . import events
from .backends import Backend, LoomBackendError
from .chaptertext import strip_title
from .errors import render
from .fsutil import atomic_write_text
from .guard import FINGERPRINT, guard_write, validate_output, visible_len
from .paths import FINGERPRINT_REL, chapter_path, fp_history_path, snapshot_path
from .state import mark_learned, set_fingerprint_source, unmark_learned

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass

_SEED_SYSTEM = """你是一个文风分析器。从用户给的真实写作样本里,提炼出一份可复用的【写作指纹】\
——也就是"这个人写东西的辨识特征"。只看怎么写(句式/用词/节奏/口头禅/爱用和绝不用的表达),\
不要复述样本的内容主题。输出必须是中文 Markdown,沿用下面给定的小标题结构,简洁、具体、可执行。\
其中 anchor 例句必须从样本里【逐字摘抄】3-6 句最有个人味的原话,不许改写。"""

_LEARN_SYSTEM = """你在维护一个作者的【写作指纹】。我给你:① 现有指纹;② 作者手改的【已按句对齐的改写候选 + 纯增删】。

两步走,别跳:
第一步,对每条「改写候选」先判定——它是【改写】(同一件事换个说法,体现作者文风)还是【改情节】(发生的事/信息变了)?
第二步,只从判定为【改写】的条目里提取作者的【个人文风偏好】(句式长短、用词习惯、节奏、口头禅、禁用表达);\
【改情节】的条目、以及【纯增删】,一律忽略,绝不当文风学。也忽略单纯的"去AI味"通用改动(那是另一个功能)。

把新观察【增量并入】现有指纹——这是【累积】,不是推倒重写。现有指纹是作者一路 learn 攒下来的嗓音,默认全部保留:
- 既有规则【默认一条不删】。只在三种情况下动它:① 把这次新学到的文风偏好【追加】成新规则;\
② 当本次证据与某条旧规则【直接矛盾】时,改写那一条(以更近的证据为准);③ 把意思明显重复的两条合并成一条。\
除此之外,不要因为"想精简/想换个说法/这条本次没复现"就删任何既有规则。
- anchor 例句【只增不减,逐字保留】:把这次作者改完保留下来、且体现文风又不含剧情专名/信息的原句【追加】进去;\
既有 anchor 一字不改、不替换、不删除。
- 规则总数即使超过 40 条,也优先合并近义项来收敛,绝不靠丢掉作者的个人偏好来压缩。

输出【完整的新指纹】(含全部保留下来的旧规则与旧 anchor),沿用与现有指纹相同的小标题结构,不要解释你改了什么。"""

_FORMAT_HINT = """# 写作指纹

> 这是"你"的文风规则化描述;写手/润色师写前会读它,你 learn 后它会更新。目的只有一个:越写越像你。

## 句式偏好
- (例:爱用短句+单句成段;长句少;少用关联词焊接)

## 口头禅 / 高频表达
-

## 禁用词 / 绝不这么写
-

## 节奏
-

## anchor 例句(逐字保留的我的原话,模型照这个味儿写、不许改写)
>
"""


def neutral_default() -> str:
    """init 离线落的中性默认指纹——老实标注"还没学到你"。"""
    return (
        "# 写作指纹\n\n"
        "> ⚠️ 这是**中性默认指纹**,还没学到你。\n"
        "> 喂样本(seed),或先写一章、手改、再 learn,它就开始像你了。\n\n"
        "## 句式偏好\n- (待 seed/learn 填充)\n\n"
        "## 口头禅 / 高频表达\n- (待填充)\n\n"
        "## 禁用词 / 绝不这么写\n- 殊不知、仿佛、宛如的堆砌\n- 连续三个以上排比\n- 直接点名情绪(\"悲伤涌上心头\")\n\n"
        "## 节奏\n- (待填充)\n\n"
        "## anchor 例句(逐字保留的我的原话,模型照这个味儿写、不许改写)\n> (还没有——喂样本后这里会出现你的原句)\n"
    )


def seed_from_samples(project_root: Path, samples: str, backend: Backend, progress: Progress = _noop) -> Path:
    if not samples.strip():
        raise LoomBackendError("样本是空的。给我一段你真写过的文字(越像你平时越好)。")
    progress(events.info("正在从你的样本里提炼写作指纹…"))
    user = (
        f"这是我真写过的文字样本:\n\n{samples.strip()}\n\n"
        f"请按下面的结构输出我的写作指纹:\n\n{_FORMAT_HINT}"
    )
    fp = backend.complete(_SEED_SYSTEM, user, max_chars=1800)
    path = project_root / FINGERPRINT_REL
    guard_write(path, fp, FINGERPRINT)   # 空/残缺不覆盖:宁可不种,也不拿一坨空的盖掉默认指纹
    set_fingerprint_source(project_root, "sample")
    progress(events.seed_done(path, "sample"))
    return path


def seed_from_reference(project_root: Path, reference_text: str, backend: Backend, progress: Progress = _noop) -> Path:
    """从【别人的原文范文】蒸出一份可作起点的写作指纹(L1 seed-from-others)。

    与 seed_from_samples 同一条蒸馏管线,只是料是你欣赏的作者的原文——种子只定【起点】,
    此后靠你的改稿脱化成你。铁律不变:learn 的学习信号仍【唯一是你的手改】(阀①),
    fingerprint_source='reference' 永不被 learn 读取(ADR 0002 不变)。
    """
    if not reference_text.strip():
        raise LoomBackendError("范文是空的。给我一段你欣赏的作者的原文(当起点用)。")
    progress(events.info("正在从这段范文里蒸出可作起点的写作指纹…"))
    user = (
        f"这是我欣赏的作者的原文范文,请蒸出可作为起点的写作指纹:\n\n{reference_text.strip()}\n\n"
        f"请按下面的结构输出这份【起点】写作指纹:\n\n{_FORMAT_HINT}"
    )
    fp = backend.complete(_SEED_SYSTEM, user, max_chars=1800)
    path = project_root / FINGERPRINT_REL
    guard_write(path, fp, FINGERPRINT)   # 校验结构(不校验来源):空/残缺不覆盖默认指纹
    set_fingerprint_source(project_root, "reference")
    progress(events.seed_done(path, "reference"))
    return path


def seed_from_inherit(project_root: Path, other_fingerprint: Path, progress: Progress = _noop) -> Path:
    if not other_fingerprint.exists():
        raise LoomBackendError(f"找不到要继承的指纹文件:{other_fingerprint}")
    content = other_fingerprint.read_text(encoding="utf-8")
    # 轻校验:这是用户主动选的【已有文件】、不是模型输出——只确认它像一份指纹,
    # 别套「模型没产出、请清空模型框」那套话术(那是给模型空响应用的,语义对不上)。
    if validate_output(content, FINGERPRINT):
        raise LoomBackendError(render("fingerprint_inherit_invalid"), code="fingerprint_inherit_invalid")
    path = project_root / FINGERPRINT_REL
    atomic_write_text(path, content)
    set_fingerprint_source(project_root, "inherit")
    progress(events.seed_done(path, "inherit"))
    return path


# 一句 = 正文 + 句末标点串(连续的!?/……不拆开)+ 紧跟的收尾引号(并入本句),或裸换行结尾;
# 引号不并入会把『他说:"好的。"然后离开。』切成两个残句,对白密集章的 learn 信号被打碎。
_SENT_RE = re.compile(r'[^。!?!?…\n]*(?:[。!?!?…]+[」』”’"\']*|\n)|[^。!?!?…\n]+')


def _segment(text: str) -> list[str]:
    """中文按句切:句末标点(含紧跟的收尾引号)/换行后切,保留标点,丢空白片段。"""
    return [s.strip() for s in _SENT_RE.findall(text) if s.strip()]


def _aligned_signal(snapshot: str, edited: str) -> str:
    """把手改拆成【改写候选】(同位置改写=文风候选)和【纯增删】(多半改剧情)。

    比行级 unified_diff 干净:整段重写时,行级 diff 是一大坨删+一大坨加、没有配对;
    句级 SequenceMatcher 把"同一处的改写"对齐成 AI→你 的句对,纯增删另列,
    让下游模型能逐对判定"改写(文风) vs 改情节",而不是从一团 diff 里瞎猜。
    (注:同位置≠同语义——SequenceMatcher 按位置对齐,语义上是不是文风改写,
     由 _LEARN_SYSTEM 的第一步交给模型判定。Loom 不引入向量/embedding。)
    """
    ai, you = _segment(snapshot), _segment(edited)
    sm = difflib.SequenceMatcher(None, ai, you, autojunk=False)
    rewrites: list[tuple[str, str]] = []
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            a, b = ai[i1:i2], you[j1:j2]
            if len(a) == len(b):                 # 逐句改写 → 1:1 配对
                rewrites += list(zip(a, b))
            else:                                # 句数变了(拆/合句)→ 整块对照
                rewrites.append(("".join(a), "".join(b)))
        elif tag == "delete":
            removed += ai[i1:i2]
        elif tag == "insert":
            added += you[j1:j2]

    parts: list[str] = []
    if rewrites:
        parts.append("## 改写候选(同一处:AI 的说法 → 你改成的说法)")
        for k, (a, b) in enumerate(rewrites, 1):
            parts.append(f"{k}. AI:{a}\n   你:{b}")
    if removed or added:
        parts.append("\n## 纯增删(多半是改剧情/补信息,不是文风)")
        parts += [f"- 你删了:{s}" for s in removed]
        parts += [f"- 你加了:{s}" for s in added]
    return "\n".join(parts) if parts else "(没有可识别的句级改动)"


def learn(project_root: Path, chapter_n: int, backend: Backend, progress: Progress = _noop,
          *, appraisal_backend: Backend | None = None) -> Path:
    edited_path = chapter_path(project_root, chapter_n)
    snap_path = snapshot_path(project_root, chapter_n)
    if not snap_path.exists() or not edited_path.exists():
        raise LoomBackendError(f"第 {chapter_n} 章还没生成过(找不到原稿快照)。先写第 {chapter_n} 章。")
    # 去掉首行标题再比/再 diff:只改标题不算「手改」、绝不被当文风学进指纹(标题与正文体物理隔离)
    edited = strip_title(edited_path.read_text(encoding="utf-8"))
    snapshot = strip_title(snap_path.read_text(encoding="utf-8"))
    if edited.strip() == snapshot.strip():
        raise LoomBackendError(
            f"第 {chapter_n} 章你一个字都还没改 —— 没有「你的改动」可学。\n"
            f"先手改它,把不像你的地方改成像你的,再 learn。"
        )

    signal = _aligned_signal(snapshot, edited)
    fp_path = project_root / FINGERPRINT_REL
    old_fp = fp_path.read_text(encoding="utf-8") if fp_path.exists() else neutral_default()

    progress(events.info(f"正在从你对第 {chapter_n} 章的手改里学习…"))
    user = (
        f"## 现有指纹\n{old_fp}\n\n"
        f"## 作者对第 {chapter_n} 章的手改(已按句对齐)\n{signal}\n\n"
        f"请按两步走(先判定改写/改情节,再只学改写)输出更新后的【完整新指纹】。"
    )
    new_fp = backend.complete(_LEARN_SYSTEM, user, max_chars=1800)
    # 硬闸(直接修用户实报的数据丢失):空/过短/丢光小节结构 → 保留旧指纹、绝不覆盖,抛友好错误。
    reasons = validate_output(new_fp, FINGERPRINT)
    if reasons:
        raise LoomBackendError(render("model_output_invalid", detail="；".join(reasons)),
                               code="model_output_invalid")
    new_fp = new_fp.strip()
    # 软闸(守 ADR 0001「不自动给指纹打分,把决定权还给人 + 可撤销」):疑似把你攒下的嗓音
    # 磨短/丢 anchor 时,仍然写入,但显著提示「可一键撤销」——不硬拦,不替你判定 learn 合不合格。
    warn = _shrink_warning(old_fp, new_fp)
    # 备份 learn 前的指纹,供作者一键撤销(人兜"形对神错"——自动打分兜不住)
    atomic_write_text(fp_history_path(project_root, chapter_n), old_fp)
    atomic_write_text(fp_path, new_fp + "\n")
    mark_learned(project_root, chapter_n)
    if warn:
        progress(events.warn(warn))
    # 写后摘要 / 外置大脑生长都是「管 what 的附赠」,可走便宜模型;指纹蒸馏(上面)始终用主模型保「像你」
    appraise = appraisal_backend or backend
    # 写后摘要补卡章纲:附赠动作,失败绝不阻断 learn(指纹已落盘)
    try:
        from .recap import recap_chapter
        recap_chapter(project_root, chapter_n, appraise, progress)
    except LoomBackendError as e:
        progress(events.warn(f"写后摘要没补成(不影响指纹):{e}"))
    # 外置大脑随章生长:把这章新设定/新人物追加进世界观/人物卡(同为附赠,绝不阻断 learn)
    try:
        from .enrich import enrich_chapter
        enrich_chapter(project_root, chapter_n, appraise, progress)
    except Exception as e:  # 附赠功能,任何失败都不能拖累已落盘的指纹
        progress(events.warn(f"外置大脑补充没补成(不影响指纹):{e}"))
    progress(events.learn_done(fp_path, chapter_n, warn))
    return fp_path


def revert_learn(project_root: Path, chapter_n: int) -> Path | None:
    """一键撤销第 N 章【最近一次】learn:把指纹还原到那次 learn 前(只撤一层),并清掉该章 learned 标记。

    撤完即清备份(撤销是一次性的);同章学过多次时,撤的是最近那次。
    """
    backup = fp_history_path(project_root, chapter_n)
    if not backup.exists():
        return None
    fp_path = project_root / FINGERPRINT_REL
    atomic_write_text(fp_path, backup.read_text(encoding="utf-8"))
    backup.unlink()
    unmark_learned(project_root, chapter_n)  # 状态同步:撤了就别再假显「已学」
    return fp_path


def _is_rule(line: str) -> bool:
    """是不是一条真规则/anchor 例句(排除页眉说明 blockquote 与占位行,免得当噪声报给作者)。"""
    s = line.strip()
    if not s.startswith(("-", ">")):
        return False
    body = s.lstrip("->").strip()
    if not body or body.startswith("("):  # 占位:- (待填充) / > (还没有…)
        return False
    return not any(k in s for k in ("中性默认指纹", "文风规则化描述", "喂样本", "先写一章"))


_QUOTE_NORM = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _norm_rule(line: str) -> str:
    """比对用归一:中英文引号统一、去首尾空白。
    免得"只把『他没说话。』的弯引号换成直引号"这种纯标点改动被误报成「删一条又加一条」,
    在弹窗里吓到作者(以为攒下的嗓音被删了)。展示仍用原文,只比对时归一。"""
    return line.strip().translate(_QUOTE_NORM)


def _anchor_lines(fp: str) -> list[str]:
    """指纹里真正的 anchor 例句行(blockquote 且非占位/页眉)。"""
    return [l for l in fp.splitlines() if l.strip().startswith(">") and _is_rule(l)]


def _shrink_warning(old_fp: str, new_fp: str) -> str:
    """软闸:这次 learn 是否疑似把攒下的嗓音磨短/丢了 anchor。返回提示语(没问题则空串)。

    只提示、不阻断——硬阻断与 ADR 0001「不自动给指纹打分」相悖;真磨短了,人看一眼点撤销即可。
    """
    msgs: list[str] = []
    old_v, new_v = visible_len(old_fp), visible_len(new_fp)
    if old_v >= 120 and new_v < old_v * 0.6:       # 基线够长才比,避开中性默认指纹→首次 learn 的正常增长
        msgs.append(f"新指纹比原来短了不少({old_v}→{new_v} 字)")
    old_anchors = {_norm_rule(l) for l in _anchor_lines(old_fp)}
    new_anchors = {_norm_rule(l) for l in _anchor_lines(new_fp)}
    if len(old_anchors) >= 2:                       # 原本就有若干 anchor 才谈「保留率」
        kept = len(old_anchors & new_anchors)
        if kept / len(old_anchors) < 0.8:
            msgs.append(f"保留的 anchor 例句偏少(原 {len(old_anchors)} 条只留下 {kept} 条)")
    if not msgs:
        return ""
    return "这次 learn:" + ";".join(msgs) + "。已写入指纹,但若你觉得不像自己了,点「撤销这次 learn」即可一键还原。"


def changed_rules(old_fp: str, new_fp: str) -> dict:
    """新旧指纹的行级变化(只看真规则/anchor 行),给作者一眼看清这次 learn 学到/改了什么。"""
    old_lines, new_lines = old_fp.splitlines(), new_fp.splitlines()
    old_norm = [_norm_rule(l) for l in old_lines]  # 归一后比对,原文用于展示
    new_norm = [_norm_rule(l) for l in new_lines]
    sm = difflib.SequenceMatcher(None, old_norm, new_norm, autojunk=False)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed += [old_lines[i].strip() for i in range(i1, i2) if _is_rule(old_lines[i])]
        if tag in ("replace", "insert"):
            added += [new_lines[j].strip() for j in range(j1, j2) if _is_rule(new_lines[j])]
    return {"added": added, "removed": removed}
