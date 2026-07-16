"""引擎用例宿主:cli 与 server 共用的编排单点 + 每本书的写锁。

双入口各自编排引擎调用已经漂移过一次(learn 旧指纹基线 server 用 neutral_default()、
cli 用 "",同一缺陷只修了一边)。此后「先查什么、再调什么、报告怎么拼」只在这里写一次,
入口退化成参数解析 + 渲染(HTTP JSON / Rich)。

写锁:per-root 非阻塞,拿不到抛 ProjectBusyError(server 统一映射 409 project_busy)。
覆盖全部「跑模型/落盘」用例;【红线】PUT /api/file(外置大脑保存)豁免不锁——
整章生成要几分钟,期间作者必须能存世界观。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from . import chapters as chap
from . import journey as journey_mod
from . import ledger, partner_store, paths, slots as slots_mod
from .agents import regen_outline as _regen_outline
from .agents import run_pipeline
from .backends import PROVIDERS, Backend, cheap_backend, get_backend, provider_catalog
from .chaptertext import body_changed, parse_title, strip_title
from .config import key_available, key_is_set, load_config, openai_compat_key_is_set
from .doctor import AGENT_FILES, BRAIN_FILES, OPTIONAL_BRAIN
from .draft import brain_ready, draft_brain as _draft_brain
from .enrich import extract_supplement
from .fingerprint import changed_rules
from .fingerprint import learn as fp_learn
from .fingerprint import (neutral_default, revert_learn, seed_from_inherit,
                          seed_from_reference, seed_from_samples)
from .fsutil import restore_history
from .rewrite import apply_rewrite
from .state import load_state

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


# ---------------------------------------------------------------- 写锁
BUSY_MESSAGE = "本书正在写作中,等这一次跑完再操作。"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class ProjectBusyError(RuntimeError):
    """写锁被占(同一本书正有跑模型/落盘任务)。刻意不继承 LoomBackendError/ValueError:
    入口的 400 网不该兜住它,busy 永远走 409。"""

    code = "project_busy"

    def __init__(self) -> None:
        super().__init__(BUSY_MESSAGE)


def try_lock(root: Path | str) -> threading.Lock | None:
    """非阻塞拿这本书的写锁;拿不到返回 None。单用户本地应用,故意不做跨进程锁。"""
    with _locks_guard:
        lock = _locks.setdefault(str(Path(root).resolve()), threading.Lock())
    return lock if lock.acquire(blocking=False) else None


def acquire_lock(root: Path | str) -> threading.Lock:
    """拿锁或抛 ProjectBusyError。给 write 流式场景:锁随 worker 线程持有,调用方自行 release。"""
    lock = try_lock(root)
    if lock is None:
        raise ProjectBusyError()
    return lock


@contextmanager
def write_lock(root: Path | str) -> Iterator[None]:
    lock = acquire_lock(root)
    try:
        yield
    finally:
        lock.release()


# ---------------------------------------------------------------- write
def _has_loom_chapter(root: Path) -> bool:
    """本书有没有任何 Loom 织出的章(判据:存在 .原稿 快照)。导入章无快照 → 视作未织。"""
    return any(paths.snapshot_path(root, n).exists() for n in paths.chapter_numbers(root))


def write_precheck(root: Path | str, chapter: int, force: bool = False) -> dict | None:
    """写前检查:None=放行;否则 {"error","code",...}(措辞即 server 409 响应体)。
    起书完整性硬门禁在最前:仅当本书还没有 Loom 织的章时启用,force 不越它。"""
    root = Path(root)
    if not _has_loom_chapter(root):
        ok, missing = journey_mod.writing_unlocked(root)
        if not ok:
            names = "、".join(missing)
            return {"error": f"开书资料还差:{names}。在伙伴面板答几题即可解锁"
                             f"(或手填 外置大脑/ 对应文件)。",
                    "code": "brain_incomplete", "missing": missing, "stage": missing[0]}
    if force or not paths.chapter_path(root, chapter).exists():
        return None
    if ledger.chapter_drifted(root, chapter):
        return {"error": f"第 {chapter} 章正文与上次记录不符(手改过?)。先 learn,或勾选覆盖以你的正文为准重写。",
                "code": "chapter_drifted"}
    return {"error": f"第 {chapter} 章已写完。要重写请勾选覆盖。", "code": "chapter_exists"}


def write_chapter(root: Path | str, chapter: int, progress: Progress, *,
                  force: bool = False, slow: float = 0.25) -> None:
    """跑 5 Agent 写第 N 章。不拿锁:流式场景锁随 worker 线程(调用方 acquire_lock / write_lock)。"""
    root = Path(root)
    cfg = load_config(root)
    # out 不存在=上次没跑完(断点),resume 跳过已落盘且上游未变的工序,省计费
    run_pipeline(root, chapter, get_backend(cfg), cfg, progress, slow=slow, resume=not force,
                 critic_backend=cheap_backend(cfg))


# ---------------------------------------------------------------- learn
@dataclass
class LearnReport:
    """learn 的完整回执:server 直接 JSON 化,cli 挑着渲染。"""

    fingerprint: str   # 新指纹全文
    card: str          # 卡章纲全文(前端自己抠 recap,响应兼容)
    changes: dict      # {"added": [...], "removed": [...]}
    recap: str         # 第 N 章 [AI回顾] 块(app.js extractRecap 的 Python 版)
    world_supp: str    # 世界观 [AI补充] 块
    chars_supp: str    # 人物卡 [AI补充] 块
    warn: str          # 疑似磨短指纹的软提示(可一键撤销)


def learn_chapter(root: Path | str, chapter: int, backend: Backend, *,
                  appraisal_backend: Backend | None = None,
                  progress: Progress = _noop) -> LearnReport:
    """learn 全编排:记旧基线 → 蒸馏 → 拼报告。旧基线统一 neutral_default
    (曾经 cli 用 "" 漂移:缺指纹文件时 changes 全量误报)。"""
    root = Path(root)
    fp_file = root / paths.FINGERPRINT_REL
    with write_lock(root):
        old_fp = fp_file.read_text(encoding="utf-8") if fp_file.exists() else neutral_default()
        evs: list[dict] = []

        def tee(ev: dict) -> None:   # 转发给入口渲染,同时留底捞 shrink_warning
            evs.append(ev)
            progress(ev)

        fp_learn(root, chapter, backend, tee, appraisal_backend=appraisal_backend)
        new_fp = fp_file.read_text(encoding="utf-8")
        card_p = root / paths.CARD_REL
        # 双形态:[AI补充] 老书在单文件文末,目录形态在各自的 成长档案.md
        from .enrich import _supp_target
        world_p, _, _ = _supp_target(root, paths.WORLD_REL, paths.WORLD_DIR_REL)
        chars_p, _, _ = _supp_target(root, paths.CHARS_REL, paths.CHARS_DIR_REL)
        done = next((e for e in evs if e.get("type") == "learn_done"), {})
        return LearnReport(
            fingerprint=new_fp,
            card=card_p.read_text(encoding="utf-8") if card_p.exists() else "",
            changes=changed_rules(old_fp, new_fp),
            recap=_recap_block(root, chapter),
            world_supp=extract_supplement(world_p.read_text(encoding="utf-8"), chapter)
                       if world_p is not None and world_p.exists() else "",
            chars_supp=extract_supplement(chars_p.read_text(encoding="utf-8"), chapter)
                       if chars_p is not None and chars_p.exists() else "",
            warn=done.get("shrink_warning") or "",
        )


def _recap_block(root: Path, chapter: int) -> str:
    """卡章纲里第 N 章的 [AI回顾] 块(含标记、已去缩进):解析复用 studio.timeline。"""
    from .studio import timeline
    row = next((r for r in timeline(root) if r["n"] == chapter), None)
    return f"[AI回顾] {row['recap']}" if row and row.get("recap") else ""


def learn_revert(root: Path | str, chapter: int) -> Path | None:
    """撤销第 N 章最近一次 learn(锁内:防与写章竞态)。"""
    with write_lock(root):
        return revert_learn(Path(root), chapter)


# ---------------------------------------------------------------- seed
def seed_fingerprint(root: Path | str, *, text: str = "", inherit: Path | str | None = None,
                     reference: str = "", progress: Progress = _noop) -> Path:
    """seed 三源分发(优先级同 server 现状:参考范文 > 继承 > 样本);继承不建后端,免 key 可用。"""
    root = Path(root)
    with write_lock(root):
        if reference:
            return seed_from_reference(root, reference, get_backend(load_config(root)), progress)
        if inherit:
            return seed_from_inherit(root, Path(inherit).expanduser(), progress)
        return seed_from_samples(root, text or "", get_backend(load_config(root)), progress)


# ---------------------------------------------------------------- 其余落盘用例(锁内薄封装)
def draft_brain(root: Path | str, idea: str) -> dict:
    """AI 起草外置大脑初稿(只覆盖空白/模板,不动人写的)。"""
    root = Path(root)
    with write_lock(root):
        return _draft_brain(root, idea, get_backend(load_config(root)))


def regen_outline(root: Path | str, chapter: int) -> str:
    """重新生成第 N 章细纲(设定师→大纲师),不碰正文。"""
    root = Path(root)
    with write_lock(root):
        cfg = load_config(root)
        return _regen_outline(root, chapter, get_backend(cfg), cfg)


def debug_chapter(root: Path | str, chapter: int) -> dict:
    """手动除虫第 N 章(老章节可跑,逐章补建账本)。锁内:写留痕+账本。走便宜模型(评估类)。"""
    root = Path(root)
    with write_lock(root):
        from .agents import _hardfacts_for
        from .continuity import scan_chapter
        p = paths.chapter_path(root, chapter)
        if not p.is_file():
            raise FileNotFoundError(f"第 {chapter} 章还没写,先写完再除虫。")
        cfg = load_config(root)
        backend = cheap_backend(cfg) or get_backend(cfg)
        body = strip_title(p.read_text(encoding="utf-8")).strip()
        return scan_chapter(root, chapter, body, backend, hardfacts=_hardfacts_for(root))


def rewrite_apply(root: Path | str, chapter: int, content: str, old_span: str, new_span: str) -> None:
    """应用局部重写:落盘正文 + 外科式同步 .原稿 快照(锁内:新增覆盖)。"""
    with write_lock(root):
        apply_rewrite(Path(root), chapter, content, old_span, new_span)


def chapter_delete(root: Path | str, n: int) -> dict:
    with write_lock(root):
        return chap.delete_chapter(root, n)


def chapter_insert(root: Path | str, n: int) -> dict:
    with write_lock(root):
        return chap.insert_after(root, n)


def chapter_move(root: Path | str, n: int, direction: str) -> dict:
    with write_lock(root):
        return chap.move_chapter(root, n, direction)


def history_restore(root: Path | str, rel: str, snap_id: str) -> str:
    """回滚单章历史版本(锁内:防与写章竞态;回滚前会先把当前版本也存一份)。"""
    with write_lock(root):
        return restore_history(root, rel, snap_id)


# ---------------------------------------------------------------- 项目状态
# 编辑器展示的 skills 清单(外置大脑可改、skills/agents 只读展示)
_SKILLS = ["世界观引擎.md", "故事引擎.md", "网文大神.md", "黄金开篇.md", "评估自检.md", "去AI味.md", "金手指.md"]


def _brain_entries(root: Path) -> list[dict]:
    """外置大脑侧栏清单(双形态):世界观/人物卡在目录形态时给 children 分组,其余单行。"""
    _dirs = {"世界观": paths.WORLD_DIR_REL, "人物卡": paths.CHARS_DIR_REL}
    out: list[dict] = []
    for n in BRAIN_FILES:
        if n in _dirs and paths.brain_form(root, paths.brain_rel(n), _dirs[n]) == "dir":
            kids = [{"rel": f"{_dirs[n]}/{f.name}", "name": f.stem}
                    for f in paths.brain_dir_files(root, _dirs[n])]
            out.append({"name": "人物" if n == "人物卡" else n, "children": kids})
        else:
            out.append({"rel": paths.brain_rel(n), "name": n})
    out += [{"rel": paths.brain_rel(n), "name": n} for n in OPTIONAL_BRAIN
            if (root / paths.brain_rel(n)).is_file()]
    return out


def project_state(root: Path | str) -> dict:
    """项目全景(后端配置/章节/外置大脑清单):server 各端点的统一响应体。"""
    root = Path(root)
    cfg = load_config(root)
    st = load_state(root)
    chapters = paths.chapter_numbers(root)
    chs = []
    for n in chapters:
        out, snap = paths.chapter_path(root, n), paths.snapshot_path(root, n)
        out_text = out.read_text(encoding="utf-8")
        # 「改过」只看正文体(去掉标题再比):改标题不算手改、不该亮「改过」徽标(与 learn/drift 同口径)
        edited = snap.exists() and body_changed(out_text, snap.read_text(encoding="utf-8"))
        chs.append({"n": n, "title": parse_title(out_text), "written": True,
                    "edited": edited, "learned": n in set(st.get("learned", []))})
    _wu = journey_mod.writing_unlocked(root)
    return {
        "root": str(root),
        "title": cfg.title,
        "backend": {"provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url,
                    "chapter_chars": cfg.chapter_chars, "key_set": key_is_set(root),
                    "openai_compat_key_set": openai_compat_key_is_set(root),
                    # 每个供应商的 key 是否可用(本书 .env 或继承的用户级默认 .env;cli 类免 key 恒 True)
                    "keys_set": {pid: (spec["kind"] == "cli" or
                                       key_available(root, spec.get("key_env", "")))
                                 for pid, spec in PROVIDERS.items()},
                    "providers": provider_catalog()},
        "fingerprint_source": st.get("fingerprint_source", "default"),
        "brain_ready": brain_ready(root),   # 弱判据:铺过底(保留供旧前端,门禁判据用下面两项)
        "writing_unlocked": _wu[0] or _has_loom_chapter(root),
        "missing": _wu[1],
        "brain": _brain_entries(root),   # 双形态:单文件=一行;目录=分组(children 子文件)
        "skills": [{"rel": f"skills/{n}", "name": n[:-3]} for n in _SKILLS],
        "agents": [{"rel": f"agents/{n}.md", "name": n} for n in AGENT_FILES],
        "chapters": chs,
        "has_body": bool(chapters),   # 有正文章(诊断动作出现条件之一)
        "next_chapter": (chapters[-1] + 1) if chapters else 1,
    }


# ---- 创作旅程(伙伴面板;spec docs/superpowers/specs/2026-07-10-journey-partner-design.md) ----

def journey_state(root: Path | str) -> dict:
    """纯读派生视图,无锁(同 project_state)。"""
    return journey_mod.journey_state(Path(root))


def journey_card(root: Path | str) -> dict:
    """出下一张问题卡;评估类调用走 cheap_model(空则主模型)。"""
    root = Path(root)
    with write_lock(root):
        cfg = load_config(root)
        return journey_mod.next_card(root, cheap_backend(cfg) or get_backend(cfg))


def journey_answer(root: Path | str, answer: str) -> dict:
    """收作者答案:整形(必要时一次消化调用)→ 落外置大脑 → 清待答卡。"""
    root = Path(root)
    with write_lock(root):
        cfg = load_config(root)
        return journey_mod.land_answer(root, answer, cheap_backend(cfg) or get_backend(cfg))


def journey_goto(root: Path | str, stage: str, skip: bool = False) -> dict:
    root = Path(root)
    with write_lock(root):
        return journey_mod.goto(root, stage, skip=skip)


# ---- 整书诊断(导入旧书;spec T4 scan 半——候选不落盘,commit 在别处) ----

def diagnose_scan(root: Path | str) -> dict:
    """整书诊断:读采样正文出候选(不落盘)。评估类走 cheap_model。"""
    root = Path(root)
    from . import diagnose
    cfg = load_config(root)
    return diagnose.scan(root, cheap_backend(cfg) or get_backend(cfg))


def diagnose_commit(root: Path | str, picks: dict) -> dict:
    """整书诊断 commit 半:作者确认的候选落盘(不调 LLM,候选已整形)。"""
    root = Path(root)
    with write_lock(root):
        from . import diagnose
        return diagnose.commit(root, picks)


# ---- 书房伙伴(对话拍板;docs/superpowers/plans/2026-07-16-partner-p3-wire-and-migrate.md) ----
# 红线:对话里的「提设定」只产 proposal 事件(loom/partner_tools.py),不落盘;
# 唯一落盘出口是 partner_confirm。


def partner_history(root: Path | str, *, tail: int | None = None) -> dict:
    """纯读派生视图,无锁(同 journey_state/project_state)。"""
    return {"events": partner_store.read_events(Path(root), tail=tail)}


def _slot_preview(root: Path, slot_id: str) -> str | None:
    """现扫 stage_slots 取 slot_id 当前 preview;槽已不存在(改名/删除)返回 None。"""
    for spec in journey_mod.STAGES:
        found = next((s for s in slots_mod.stage_slots(root, spec) if s.id == slot_id), None)
        if found is not None:
            return found.preview
    return None


def partner_confirm(root: Path | str, pid: str, *, ts: str) -> dict:
    """拍板落盘:找 proposal → 快照比对 → 按其 slot 定址落盘 → 记一条 confirm 事件。

    幂等(防双击/重发对 file 类落点二次追加):jsonl 里已有该 pid 的 confirm 事件,
    直接返已落盘结果,不重跑 _land_slot。proposal 过期(find_proposal 返 None)或
    落点冲突/未知(_land_slot 抛 ValueError,如 filename 撞车、槽位不存在)都不崩,
    返 {"error": ...}——两种情况都不追加 confirm 事件,原 proposal 仍可重试。

    快照守卫(收敛范围,详见 docs/superpowers/sdd/task-1-report.md):proposal 产生时
    (partner_tools._handle_tishe)记落点当时的 preview 到 "before";这里落盘前重新扫一次
    现在的 preview,不一致就当这一格在提案挂起期间被作者手改过,拒绝落盘、不追加 confirm
    事件(拍板可重试——领航员会重新看一眼再提)。preview 只取前 24 字,能可靠检测 row/line/
    h2 这类「替换型」落点的改动(现实中的破坏性场景:作者手改覆盖了旧值,双方值都短);
    对 file 型「追加型」落点(如世界观小节正文),占位模板文案常年 ≥24 字、preview 早已
    饱和,快照测不出「作者又追加了别的」——这是已知的低危缺口,故意不堵:追加型双落盘
    最坏后果只是重复内容(非数据丢失),且要触发它需要「提案挂起期间、精确在扫描后落盘前
    这个窄窗口内」手改同一格,概率极低,不值得为它换更贵的整段内容快照。
    """
    root = Path(root)
    with write_lock(root):
        existing = next((e for e in partner_store.read_events(root)
                          if e.get("t") == "confirm" and e.get("id") == pid), None)
        if existing is not None:
            return {"landed": existing.get("landed"), "state": journey_mod.journey_state(root)}
        proposal = partner_store.find_proposal(root, pid)
        if proposal is None:
            return {"error": "提案已过期,重新问一次"}
        # .get() 取字段:proposal 损坏/缺字段(旧版本残留、手改 jsonl)一律当过期处理,
        # 不许 KeyError 崩(slot/content 是 _land_slot 的必需参数,缺一都没法落盘)。
        slot_id = proposal.get("slot")
        content = proposal.get("content")
        if not slot_id or not content:
            return {"error": "提案已过期,重新问一次"}
        before = proposal.get("before")   # 无此字段(旧 proposal)→ 向后兼容,跳过快照比对
        if before is not None:
            current = _slot_preview(root, slot_id)
            # current is None:槽已不存在(改名/删除),留给下面 _land_slot 报「未知槽位」,
            # 不在这里误判成 stale——两种失败原因不同,措辞不该混在一起。
            if current is not None and current != before:
                return {"error": "这一格刚改过,我重新看看再给你提", "stale": True}
        try:
            landed = journey_mod._land_slot(root, slot_id, content)
        except ValueError as e:
            return {"error": str(e)}
        partner_store.append_event(root, {"t": "confirm", "id": pid, "ts": ts, "landed": landed})
        return {"landed": landed, "state": journey_mod.journey_state(root)}


def partner_new(root: Path | str, *, stamp: str) -> dict:
    """归档当前伙伴对话,另起一段(不动书内容,只挪 jsonl 文件)。"""
    root = Path(root)
    with write_lock(root):
        partner_store.archive_current(root, stamp)
        return {"ok": True}
