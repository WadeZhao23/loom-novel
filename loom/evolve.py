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

我给你:① 这个角色的出厂写法要求(基座,**只读**);② 现有的个人增补;③ 若干章的证据,
每章两份原文——AI 交出去的那份、和作者改成的那份。

两步走,别跳:
第一步,逐章比对两份原文,只找出【跨多章反复出现】的改法。只在一章出现过的差异是这一章特殊,
不是习惯,一律忽略。也忽略纯错别字、标点、以及与这个角色职责无关的改动。
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
    blocks = [f"### 第{e.chapter}章\n【AI 交的】\n{e.ai}\n\n【作者改成的】\n{e.author}" for e in edits]
    user = (f"## 角色\n{persona_name}\n\n## 出厂写法要求(基座,只读,不要改写它)\n{base}\n\n"
            f"## 现有的个人增补\n{extra or '(还没有)'}\n\n"
            f"## 证据({len(edits)} 章)\n" + "\n\n".join(blocks) +
            "\n\n请按两步走输出【完整的新增补】。")
    out = backend.complete(_REFINE_SYSTEM, user, max_chars=1200)
    reasons = validate_output(out, Profile("个人增补", min_chars=2))
    if reasons:
        raise LoomBackendError(render("model_output_invalid", detail="；".join(reasons)),
                               code="model_output_invalid")
    out = out.strip()
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
    return Path(root) / paths.EVOLVE_DIR / "历史" / f"{persona_name}-增补前.md"


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
