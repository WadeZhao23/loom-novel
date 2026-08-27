"""自进化:从【作者实际改成了什么】学出人格的个人增补。

spec 2026-08-16 §1.3/§5(P3)。这是 Continual Harness 的一环——把已经在写作指纹上验证过
十几个版本的 learn 纪律,推广到第二个可进化对象(agent 提示词)。

**为什么不问模型「本可以更好吗」**:Prime Agent 的 `/refine` 只能让模型回看自己的轨迹自评,
因为没有人在旁边逐字改它的输出。Loom 不一样——作者每一章都在手改,那是 **ground truth**。
于是判据是「作者实际改成了什么」,不是任何形式的评价。顺带地,全程没有一个分数,
ADR 0002/0006 的「不打分」红线自动成立。

**为什么第一个对象是细纲**:四类可进化对象里,只有细纲有【干净的、逐产物的】证据——
它是 WYSIWYG 文件,AI 交的那份在轨迹里、作者改的那份在盘上,两边都是原文。
正文的手改混着 voice(已归写作指纹,ADR 0002)和剧情改动,归因只能猜——不猜。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import artifacts, paths, trail

# 盘上有【可比对文件】的产物 → 它归哪个人格。目前只有细纲一件;
# 将来若有第二件本地可编辑产物,在这里加一行即可(同 DETECTORS 注册表的路子)。
_COMPARABLE: dict[str, str] = {
    a.name: a.persona for a in artifacts.ARTIFACTS if a.outline_file and a.persona
}


def learnable_personas() -> set[str]:
    """今天「学改法」学得了的人格 —— 由 `_COMPARABLE` 派生,不手抄。

    结构性限制,不是「证据还不够」:判据只能是「作者实际改成了什么」(ADR 0002/0006 红线),
    所以那个人格必须有一件**盘上可比对**的产物。今天只有大纲师的细纲是这个形状。
    将来某件产物也变成本地可编辑,`_COMPARABLE` 加一行,这里和文案自动跟着变。
    """
    return set(_COMPARABLE.values())


@dataclass(frozen=True)
class Edit:
    """一条证据:某一章里,agent 交的那份 vs 作者改成的那份。"""

    chapter: int
    artifact: str
    persona: str
    ai: str        # agent 提交的原文
    author: str    # 作者改后的原文


def _norm(text: str) -> str:
    """比对用归一:只去首尾空白。落盘时补的换行不该被当成「作者改了它」。"""
    return (text or "").strip()


def collect(root: Path | str, *, persona: str | None = None) -> list[Edit]:
    """扫全书,收出「agent 交了 X、作者把它改成了 Y」的章。按章号升序。

    两边都得有才算证据:作者自己手写的细纲(agent 没交过)没有 AI 侧,无从比较;
    agent 交了而作者没动过,也不是证据。
    """
    root = Path(root)
    out: list[Edit] = []
    for n in trail.chapters(root):   # 证据源是轨迹,不是正文文件(正文可能还没落盘)
        # 同一件产物可能提交多次(agent 回头重来)——作者改的是最后那份,比较也拿它
        latest: dict[str, str] = {}
        for c in trail.read_commits(root, n):
            if c.get("产物") in _COMPARABLE:
                latest[c["产物"]] = c.get("text", "")
        for name, ai in latest.items():
            who = _COMPARABLE[name]
            if persona and who != persona:
                continue
            p = paths.outline_path(root, n)
            if not p.is_file():
                continue
            try:
                author = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # UnicodeDecodeError 继承自 ValueError 而非 OSError,裸 `except OSError`
                # 抓不到,编码损坏的细纲会让 collect 直接抛穿、砸崩整条自进化证据采集链
                # (同 mirror.py 已踩过的坑)——这一章当没有证据跳过即可,其余章节照常收。
                continue
            if _norm(author) and _norm(author) != _norm(ai):
                out.append(Edit(chapter=n, artifact=name, persona=who,
                                ai=_norm(ai), author=_norm(author)))
    return out


_REFINE_SYSTEM = """你在维护一位作者的【个人增补】——记录他在这本书上**反复做的改法**,
好让下次这个角色直接照他的习惯来。

我给你:① 这个角色的出厂写法要求(基座,**只读**);② 现有的个人增补;③ 若干章的证据。
证据是**已经算好的逐行 diff**——作者删掉了哪些行、加上了哪些行、把哪行改写成了什么。
你不必自己去比对原文,那一步我已经替你做完了。

两步走,别跳:
第一步,横着看这几章的 diff,找出【跨多章反复出现】的改法。判据就是重复:同一类改动在
两章及以上出现过,才算习惯。只在一章出现过的是那一章特殊,一律忽略;纯错别字、标点、
以及与这个角色职责无关的改动也忽略。
**别因为「不确定」就一条都不给**——真有跨章重复就写出来;确实每章都各改各的,才回「无」。
第二步,把这些改法写成给这个角色的**执行性规则**(一条一行,以「- 」起头,说清「做什么/不做什么」,
不要解释你的推理过程)。

把新观察【增量并入】现有增补——这是**累积**,不是推倒重写:
- 既有条目【默认一条不删】。只在三种情况下动它:① 追加新学到的改法;
  ② 本次证据与某条旧条目【直接矛盾】时,改写那一条(以更近的证据为准);③ 把意思重复的两条合并。
- 【绝不改写基座】。基座是出厂写法要求,随版本升级走;你只输出增补区的内容。
- 【不要打分、不要评价】作者改得好不好。你的依据只有一条:他实际改成了什么。

输出【完整的新增补】(含全部保留下来的旧条目),只要条目行本身,不要标题、不要前言、不要解释。
确实没有可归纳的反复改法时,只回一行:无。"""

_NO_PATTERN = ("无", "无。", "(无)", "（无）")


_MAX_DIFF_LINES = 20      # 每章每类最多列这么多行,再多就截断并明说(别把 prompt 撑爆)


def _diff_lines(ai: str, author: str) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """行级 diff:(作者删掉的, 作者加上的, 作者改写的[(前,后)])。**确定性,不经模型。**

    v0.3.7「字数五螺丝」的教训在这里原样适用:**LLM 自己数不准 = 授权无牙**,那一版把
    「数字数」从模型手里拿回代码手里。这里是同一件事换了个形状——真机 2026-08-26 实测,
    旧写法把两份各 1400 字的原文丢给模型、让它自己「逐章比对」,而真正的差异是 40 行里的
    1~3 行:三章证据里作者一共删了 5 处「情绪:」行、2 处「许的承诺」行,这么干净的重复模式,
    refine 回的是「无」。diff 是确定性的、difflib 三行就算得出来,没有理由让模型去大海捞针。
    """
    import difflib
    a = [l.rstrip() for l in (ai or "").splitlines() if l.strip()]
    b = [l.rstrip() for l in (author or "").splitlines() if l.strip()]
    dropped: list[str] = []
    added: list[str] = []
    changed: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "delete":
            dropped += a[i1:i2]
        elif tag == "insert":
            added += b[j1:j2]
        elif tag == "replace":
            # 成对的算「改写」,落单的归到删/加——别把一次改写谎报成一删一加
            for k in range(max(i2 - i1, j2 - j1)):
                before = a[i1 + k] if i1 + k < i2 else None
                after = b[j1 + k] if j1 + k < j2 else None
                if before is not None and after is not None:
                    changed.append((before, after))
                elif before is not None:
                    dropped.append(before)
                elif after is not None:
                    added.append(after)
    return dropped, added, changed


def _fmt(label: str, rows: list[str]) -> str:
    if not rows:
        return f"{label}:(无)"
    shown = rows[:_MAX_DIFF_LINES]
    more = f"\n  …另有 {len(rows) - len(shown)} 行同类,已省略" if len(rows) > len(shown) else ""
    return f"{label}({len(rows)} 行):\n" + "\n".join(f"  {r}" for r in shown) + more


def _evidence_block(e: "Edit") -> str:
    """一章的证据 = 【算好的 diff】,不是两份原文。见 `_diff_lines` 的注释。"""
    dropped, added, changed = _diff_lines(e.ai, e.author)
    parts = [f"### 第{e.chapter}章(AI 交 {len(e.ai)} 字 → 作者改成 {len(e.author)} 字)",
             _fmt("作者删掉的行", dropped), _fmt("作者加上的行", added)]
    if changed:
        shown = changed[:_MAX_DIFF_LINES]
        rows = "\n".join(f"  「{b}」→「{a}」" for b, a in shown)
        more = f"\n  …另有 {len(changed) - len(shown)} 处,已省略" if len(changed) > len(shown) else ""
        parts.append(f"作者改写的行({len(changed)} 处):\n{rows}{more}")
    else:
        parts.append("作者改写的行:(无)")
    return "\n".join(parts)


def refine(root: Path | str, persona_name: str, backend, *, min_edits: int = 3,
           progress=None) -> str | None:
    """从证据蒸出【完整的新增补】。证据不够返回 None(且**一次调用都不发**)。

    产物是「并入之后的完整增补」,不是增量片段——同 `fingerprint.learn` 输出完整新指纹,
    调用方整块替换增补区即可(`persona.write_extra`)。

    空/残废输出直接抛(同 guard 的老规矩):模型这次没产出,就别拿一坨空的去覆盖作者攒下的增补。
    """
    from .errors import render
    from .guard import Profile, validate_output
    from .backends import LoomBackendError

    edits = collect(root, persona=persona_name)
    if len(edits) < min_edits:
        return None
    base, extra = _persona_mod().split(root, persona_name)
    blocks = [_evidence_block(e) for e in edits]
    user = (f"## 角色\n{persona_name}\n\n## 出厂写法要求(基座,只读,不要改写它)\n{base}\n\n"
            f"## 现有的个人增补\n{extra or '(还没有)'}\n\n"
            f"## 证据({len(edits)} 章)\n" + "\n\n".join(blocks) +
            "\n\n请按两步走输出【完整的新增补】。")
    out = backend.complete(_REFINE_SYSTEM, user, max_chars=1200)
    reasons = validate_output(out, Profile("个人增补", min_chars=2))
    if reasons:
        raise LoomBackendError(render("model_output_invalid", detail="；".join(reasons)),
                               code="model_output_invalid")
    # 逐行去尾空白:模型爱在行尾留两个空格(markdown 换行),原样落进 agents/<角色>.md 是噪声
    out = "\n".join(l.rstrip() for l in out.strip().splitlines()).strip()
    return None if out in _NO_PATTERN else out


def propose(root: Path | str, persona_name: str, backend, *, min_edits: int = 3) -> dict | None:
    """出一张**候选卡**:refine 蒸出的新增补 + 它依据了几章证据。**一个字都不落盘。**

    红线(§7.1):绝不替作者做决定。改了提示词下一章出稿就变,而作者不知道为什么——
    可见性 + 可撤销,是这条自进化链唯一让人放心的形状。

    候选卡的形状与领航员的「提设定」【不】完全一致(终审③:这句此前写反过,误导过上一轮
    修复者)——这里多带 kind="人格增补"/角色/证据章数 三个字段:角色/内容 没有 slot 概念,
    落点固定是 agents/<角色>.md 的个人增补区(见 `partner_confirm` 按 kind 分流的落盘路径,
    不是「提设定」那套 slot 定址 + 快照守卫)。webui 复用既有卡片渲染读的是 slot/content
    两个别名,这两个别名不在这里补——由调用方 `partner_tools._handle_xuegaifa` 加上
    (slot=agents/<角色>.md,content=本函数产出的「内容」),这里出的是这件事本身的产物
    形状,不掺前端渲染细节。
    """
    text = refine(root, persona_name, backend, min_edits=min_edits)
    if not text:
        return None
    return {"t": "proposal", "kind": "人格增补", "角色": persona_name,
            "内容": text, "证据章数": len(collect(root, persona=persona_name))}


def _snapshot_path(root: Path | str, persona_name: str) -> Path:
    # 同样拼进文件名 → 同样过 persona.check_name(revert 只碰快照、不碰 agents/,单靠 _path 那道闸兜不住)
    return Path(root) / paths.EVOLVE_DIR / "历史" / f"{_persona_mod().check_name(persona_name)}-增补前.md"


def confirm(root: Path | str, persona_name: str, text: str) -> Path:
    """作者拍板:落进增补区。落之前先把当前增补快照进 `.进化/历史/`,供一键撤销。

    快照只留【最近一次】(同 `fingerprint.revert_learn` 的一次性撤销语义)——
    不做无限回退栈,那是版本控制的活,不是这里的。
    """
    from .fsutil import atomic_write_text
    p = _persona_mod()
    snap = _snapshot_path(root, persona_name)
    snap.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(snap, p.split(root, persona_name)[1])
    return p.write_extra(root, persona_name, text)


def has_snapshot(root: Path | str, persona_name: str) -> bool:
    """还撤得回去吗——`.进化/历史/` 里那份一次性快照还在不在(镜台据此决定按钮灰不灰)。"""
    try:
        return _snapshot_path(root, persona_name).is_file()
    except ValueError:      # 人格名不合法(persona.check_name)→ 当然没有快照,不抛给只读投影
        return False


def revert(root: Path | str, persona_name: str) -> Path | None:
    """一键撤销最近一次落盘。没有快照(没落过 / 作者删了 `.进化/`)则返回 None。"""
    snap = _snapshot_path(root, persona_name)
    if not snap.is_file():
        return None
    old = snap.read_text(encoding="utf-8")
    path = _persona_mod().write_extra(root, persona_name, old)
    snap.unlink(missing_ok=True)   # 撤完即清:撤销是一次性的
    return path


def _persona_mod():
    from . import persona as _p   # 函数级导入:persona 不反向依赖 evolve,保持单向
    return _p


def ripe(root: Path | str, persona: str, *, min_edits: int = 3) -> bool:
    """证据够不够开口提议。

    一章的差异可能只是这一章特殊;要跨多章反复出现,才谈得上「这是你的改法」——
    同 fingerprint 的思路,单次证据不足以改写规则。
    """
    return len(collect(root, persona=persona)) >= min_edits
