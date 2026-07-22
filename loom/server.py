"""本地 FastAPI 服务:把 loom 引擎暴露成 JSON / 流式接口给 Web 界面。

只监听 127.0.0.1,单用户本地桌面应用,不做鉴权。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import events, partner, usecases
from .backends import (PROVIDERS, LoomBackendError, cheap_backend, get_backend, list_models,
                       probe as probe_backend, provider_catalog, validate_model)
from .config import Config, load_config, save_config, set_provider_key
from .doctor import report, run_checks
from .fsutil import atomic_write_text, list_history, safe_join, snapshot_chapter
from .scaffold import available_genres
from .scaffold import init as scaffold_init
from .usecases import ProjectBusyError

WEBUI_DIR = Path(__file__).parent / "webui"

# ── Gate 结果存储(供 /api/write/gate-detail 查询) ──────────────────────────
_gate_detail_store: dict[str, list] = {}
_gate_detail_lock = threading.Lock()


def _store_gate_detail(root: str, chapter: int, detail_list: list) -> None:
    """线程安全地存储 gate 结果。"""
    key = f"{root}:{chapter}"
    with _gate_detail_lock:
        if key not in _gate_detail_store:
            _gate_detail_store[key] = []
        _gate_detail_store[key].extend(detail_list)


def _get_gate_detail(root: str, chapter: int) -> list:
    """查询已存储的 gate 结果。"""
    key = f"{root}:{chapter}"
    with _gate_detail_lock:
        return list(_gate_detail_store.get(key, []))


app = FastAPI(title="Loom")

# 本地服务的两道安全闸(本地无鉴权模型成立的前提):
# 1) 只认 Host=127.0.0.1/localhost → 挡 DNS rebinding(恶意网站把域名重绑到本机再调本地端点)
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


# 2) 跨站写请求一律拒(挡 CSRF):非 GET 且 Origin/Referer 非本机 → 403。
#    本机 webui(pywebview/浏览器从 127.0.0.1 发)Origin 即 127.0.0.1,放行;无 Origin 的本地工具(curl)放行。
@app.middleware("http")
async def _block_cross_site_writes(request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        from urllib.parse import urlparse
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and (urlparse(origin).hostname or "") not in ("127.0.0.1", "localhost"):
            return JSONResponse({"error": "跨站写请求被拒"}, status_code=403)
    return await call_next(request)

# ---- 写锁:下沉到 usecases(单一宿主),这里只把「锁被占」统一映射成 409 project_busy ----
# 【红线】PUT /api/file(外置大脑保存)豁免不锁:整章生成几分钟,期间必须能存世界观。
@app.exception_handler(ProjectBusyError)
async def _project_busy(request, exc: ProjectBusyError):
    return JSONResponse({"error": str(exc), "code": exc.code}, status_code=409)


def _is_project(p: Path) -> bool:
    return (p / "loom.toml").exists()


def _err_json(e: Exception, status: int = 400) -> JSONResponse:
    """非流式端点的错误响应单点:LoomBackendError 带 code(错误目录键)透传给前端附提示。"""
    body: dict = {"error": str(e)}
    if isinstance(e, LoomBackendError) and e.code:
        body["code"] = e.code
    return JSONResponse(body, status_code=status)


# 项目全景响应体单一真相在 usecases.project_state,server 只留薄壳
_state = usecases.project_state


# ----------------------------- 项目 -----------------------------
class CreateBody(BaseModel):
    name: str
    parent: str
    genre: str | None = None
    idea: str = ""        # 一句话设定(可空):存 loom.toml,AI 铺设定底稿的种子
    platform: str = ""    # 目标平台(可空):写立项卡平台行,定违禁词自检基线


class RootBody(BaseModel):
    root: str


@app.get("/api/version")
def version():
    from . import __version__
    return {"version": __version__}


@app.get("/api/genres")
def genres():
    return {"genres": available_genres()}


def _shelve(root: Path, state: dict) -> dict:
    """开书成功 → 记上书架(新建/导入/样例统一入架,欢迎页点选,不再输路径)。"""
    from . import userconf
    userconf.record_project(root, state.get("title", ""))
    return state


@app.post("/api/project/create")
def create_project(b: CreateBody):
    try:
        root = scaffold_init(b.name, Path(b.parent).expanduser(), b.genre,
                             idea=b.idea, platform=b.platform)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from . import userconf
    userconf.apply_default_to_new_book(root)   # 新书继承用户级默认后端(连一次全局记住,不用每本重填)
    return _shelve(root, _state(root))


@app.get("/api/projects")
def projects_list():
    """书架:注册过的书 + 是否还在磁盘上 + 章数(欢迎页点选用)。"""
    from . import paths as _paths
    from . import userconf
    out = []
    for p in userconf.list_projects():
        root = Path(p.get("root", ""))
        ok = (root / "loom.toml").is_file()
        chapters = 0
        if ok:
            try:
                chapters = len(_paths.chapter_numbers(root))
            except Exception:
                pass
        out.append({**p, "exists": ok, "chapters": chapters})
    return {"projects": out}


@app.post("/api/projects/forget")
def projects_forget(b: RootBody):
    from . import userconf
    userconf.forget_project(b.root)
    return {"ok": True}


class ParentBody(BaseModel):
    parent: str


@app.post("/api/sample/open")
def sample_open(b: ParentBody):
    """拷一份内置样例书到 parent 并打开,让陌生作者先看一本跑通的书。"""
    from .scaffold import open_sample
    root = open_sample(Path(b.parent).expanduser())
    return _shelve(root, _state(root))


class ImportScanBody(BaseModel):
    folder: str


class ImportCommitBody(BaseModel):
    folder: str
    name: str
    parent: str
    routing: dict = {}


@app.post("/api/project/import/scan")
def import_scan(b: ImportScanBody):
    """扫资料夹里的 .md 和 .txt,按文件名启发路由(不落盘),供前端出确认屏。"""
    from . import importer
    folder = Path(b.folder).expanduser()
    if not folder.is_dir():
        return JSONResponse({"error": f"{folder} 不是文件夹或不存在。"}, status_code=400)
    names = sorted(p.name for p in folder.rglob("*") if p.suffix.lower() in (".md", ".txt") and p.is_file())
    if not names:
        return JSONResponse({"error": "这个文件夹里没有 .md 或 .txt 文件。"}, status_code=400)
    routed = importer.route_files(names)
    unknown = routed.pop("unknown")
    return {"ok": True, "name_suggest": folder.name, "routed": routed, "unknown": unknown}


@app.post("/api/project/import/commit")
def import_commit(b: ImportCommitBody):
    """按确认后的 routing 机械落盘成新书,入书架,返回全景 + 降级小结。"""
    from . import importer
    folder = Path(b.folder).expanduser()
    if not folder.is_dir():
        return JSONResponse({"error": f"{folder} 不是文件夹或不存在。"}, status_code=400)
    if not (b.name or "").strip():
        return JSONResponse({"error": "先给这本书起个名字。"}, status_code=400)
    routing = {bk: list(b.routing.get(bk, [])) for bk in importer.BUCKETS}
    try:
        root = importer.import_folder(folder, b.name.strip(), routing, Path(b.parent).expanduser())
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        return _err_json(e)
    from . import userconf
    userconf.apply_default_to_new_book(root)   # 同 create:新书继承用户级默认后端
    summary = importer.import_summary(root, routing)
    state = _shelve(root, _state(root))        # 同 create_project:顶层就是 project_state
    return {**state, "summary": summary}       # webui: enterProject(d) 吃 state 字段、d.summary 取小结


@app.post("/api/project/open")
def open_project(b: RootBody):
    root = Path(b.root).expanduser()
    if not _is_project(root):
        return JSONResponse({"error": f"{root} 不是 loom 项目(没有 loom.toml)。"}, status_code=400)
    try:
        return _shelve(root, _state(root))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/project/state")
def project_state(root: str):
    return _state(Path(root))


@app.get("/api/doctor")
def doctor(root: str):
    """只读启动自检:检查 key/后端命令/agent/外置大脑齐不齐。"""
    return report(run_checks(Path(root)))


@app.post("/api/export")
def export(b: RootBody):
    from .archive import export_text
    try:
        return export_text(Path(b.root).expanduser())
    except (FileNotFoundError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/backup")
def backup(b: RootBody):
    from .archive import backup_project
    try:
        return backup_project(Path(b.root).expanduser())
    except (FileNotFoundError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ----------------------------- 文件 -----------------------------
class FileBody(BaseModel):
    root: str
    rel: str
    content: str


@app.get("/api/file")
def read_file(root: str, rel: str):
    try:
        p = safe_join(root, rel)           # 挡目录穿越 / 绝对路径越界
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not p.exists():
        return JSONResponse({"error": f"文件不存在:{rel}"}, status_code=404)
    return {"rel": rel, "content": p.read_text(encoding="utf-8")}


@app.put("/api/file")
def write_file(b: FileBody):
    try:
        p = safe_join(b.root, b.rel)       # 挡目录穿越 / 绝对路径越界,绝不写到项目外
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    snapshot_chapter(b.root, b.rel)        # 覆盖正文章节前留一版历史(正则限定 正文/第N章.md,安全)
    atomic_write_text(p, b.content)        # 原子写盘:崩溃/断电不会把正文截成空或半截
    return {"ok": True}


@app.get("/api/history")
def history(root: str, rel: str):
    return {"versions": list_history(root, rel)}


class RestoreBody(BaseModel):
    root: str
    rel: str
    id: str


@app.post("/api/history/restore")
def history_restore(b: RestoreBody):
    try:
        content = usecases.history_restore(b.root, b.rel, b.id)  # 回滚前会先把当前版本也存一份
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "content": content}


# ----------------------------- 后端配置 -----------------------------
class ConfigBody(BaseModel):
    root: str
    provider: str
    model: str
    chapter_chars: int
    base_url: str | None = None
    api_key: str | None = None


@app.get("/api/backend/probe")
def backend_probe(provider: str):
    return probe_backend(provider)


# ---- 用户级默认后端(接入模型:连一次全局记住,新书自动继承)----
class DefaultBackendBody(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None


@app.get("/api/backend/default")
def get_default_backend():
    """欢迎页「接入模型」回显:当前用户级默认后端 + 各家 key 是否已设 + 供应商目录。"""
    from . import userconf
    d = userconf.load_default_backend()
    keys_set = {pid: (spec["kind"] == "cli" or userconf.default_key_is_set(pid))
                for pid, spec in PROVIDERS.items()}
    return {"provider": d.get("provider", "deepseek"), "model": d.get("model", ""),
            "base_url": d.get("base_url", ""), "has_default": userconf.has_default(),
            "keys_set": keys_set, "providers": provider_catalog()}


@app.put("/api/backend/default")
def put_default_backend(b: DefaultBackendBody):
    from . import userconf
    if b.provider == "openai_compat" and not (b.base_url or "").strip():
        return JSONResponse({"error": "选了「OpenAI 兼容(自定义)」要先填 base_url 再保存。"}, status_code=400)
    userconf.save_default_backend(b.provider, b.model, (b.base_url or "").strip(), b.api_key)
    warn = validate_model(b.provider, b.model)
    return {"ok": True, "model_warning": warn}


class ModelsBody(BaseModel):
    root: str | None = None
    provider: str
    base_url: str | None = None
    api_key: str | None = None


@app.post("/api/backend/models")
def backend_models(b: ModelsBody):
    """「拉取可用模型」:OpenAI 兼容的实时打 GET /models,CLI 类返回预设。只读、不耗 token。"""
    if b.root:
        load_config(Path(b.root))   # 让项目 .env 里的 key 进 os.environ,拉取时能用上
    return list_models(b.provider, base_url=b.base_url or "", api_key=b.api_key or "")


class ChapterOpBody(BaseModel):
    root: str
    n: int
    direction: str | None = None


class JourneyAnswerBody(BaseModel):
    root: str
    answer: str


class JourneyGotoBody(BaseModel):
    root: str
    stage: str
    skip: bool = False


@app.post("/api/chapter/delete")
def chapter_delete(b: ChapterOpBody):
    try:
        return {**usecases.chapter_delete(b.root, b.n), **{"state": _state(Path(b.root))}}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/chapter/insert")
def chapter_insert(b: ChapterOpBody):
    try:
        return {**usecases.chapter_insert(b.root, b.n), **{"state": _state(Path(b.root))}}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/chapter/move")
def chapter_move(b: ChapterOpBody):
    try:
        return {**usecases.chapter_move(b.root, b.n, b.direction or "up"), **{"state": _state(Path(b.root))}}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/journey/state")
def journey_state_ep(root: str):
    try:
        return usecases.journey_state(Path(root))
    except (ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/journey/card")
def journey_card_ep(b: RootBody):
    try:
        return usecases.journey_card(Path(b.root))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/journey/answer")
def journey_answer_ep(b: JourneyAnswerBody):
    try:
        return usecases.journey_answer(Path(b.root), b.answer)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/journey/goto")
def journey_goto_ep(b: JourneyGotoBody):
    try:
        return usecases.journey_goto(Path(b.root), b.stage, b.skip)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


class DiagnoseCommitBody(BaseModel):
    root: str
    picks: dict = {}


@app.post("/api/diagnose/scan")
def diagnose_scan_ep(b: RootBody):
    try:
        return {"ok": True, "candidates": usecases.diagnose_scan(Path(b.root))}
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/diagnose/commit")
def diagnose_commit_ep(b: DiagnoseCommitBody):
    try:
        usecases.diagnose_commit(Path(b.root), b.picks)
        return usecases.project_state(Path(b.root))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


class ScanBody(BaseModel):
    root: str
    text: str


@app.post("/api/sensitive/scan")
def sensitive_scan(b: ScanBody):
    from .sensitive import scan
    return {"hits": scan(b.text, b.root)}


@app.get("/api/studio")
def studio_view(root: str):
    """书房三视图(时间轴/伏笔账本/专名册):纯只读投影,不调模型、不写盘。"""
    from .studio import studio
    try:
        return studio(Path(root))
    except Exception as e:
        return JSONResponse({"error": f"书房读取失败:{e}"}, status_code=400)


@app.put("/api/config")
def update_config(b: ConfigBody):
    root = Path(b.root)
    cfg = load_config(root)
    base_url = (b.base_url or "").strip()
    if b.provider == "openai_compat" and not base_url:
        return JSONResponse({"error": "选了「OpenAI 兼容(自定义)」要先填这家供应商的 base_url(接口地址),再保存。"},
                            status_code=400)
    save_config(root, Config(provider=b.provider, model=b.model, base_url=base_url, title=cfg.title,
                             chapter_chars=b.chapter_chars, gate_rounds=cfg.gate_rounds))  # 别把回炉轮数静默重置回默认
    if b.api_key:
        # key 按供应商的 key_env(PROVIDERS 注册表声明)各落各行:DeepSeek/智谱/Kimi/…互不覆盖
        key_env = (PROVIDERS.get(b.provider) or {}).get("key_env")
        if key_env:
            set_provider_key(root, key_env, b.api_key.strip())
    st = _state(root)
    warn = validate_model(b.provider, b.model)   # 软提示(如把 v4-flash 填进 deepseek)——只提示,不阻断保存
    if warn:
        st["model_warning"] = warn
    return st


# ----------------------------- seed / learn -----------------------------
class SeedBody(BaseModel):
    root: str
    text: str | None = None
    inherit: str | None = None
    reference: str | None = None


@app.post("/api/seed")
def seed(b: SeedBody):
    root = Path(b.root)
    try:
        usecases.seed_fingerprint(root, text=b.text or "", inherit=b.inherit, reference=b.reference or "")
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    return _state(root)


class ChapterBody(BaseModel):
    root: str
    chapter: int


@app.post("/api/learn")
def learn(b: ChapterBody):
    root = Path(b.root)
    try:
        cfg = load_config(root)
        rep = usecases.learn_chapter(root, b.chapter, get_backend(cfg),
                                     appraisal_backend=cheap_backend(cfg))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    # LearnReport → 响应字段逐字节兼容(前端 app.js 零改动)
    return {"ok": True,
            "fingerprint": rep.fingerprint,
            "卡章纲": rep.card,
            "changes": rep.changes,
            "世界观补充": rep.world_supp,
            "人物卡补充": rep.chars_supp,
            "warn": rep.warn}   # 软提示:疑似把嗓音磨短/丢 anchor,可一键撤销


class DraftBody(BaseModel):
    root: str
    idea: str = ""


@app.post("/api/brain/draft")
def brain_draft(b: DraftBody):
    """从书名+题材+一句话设定,AI 起草 世界观/人物卡/卡章纲 初稿(只覆盖空白/模板,不动你写的)。"""
    root = Path(b.root)
    try:
        res = usecases.draft_brain(root, b.idea)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    return {"ok": True, "written": list(res["written"].keys()),
            "skipped": res["skipped"], "state": _state(root)}


class BrainRWBody(BaseModel):
    root: str
    rel: str
    full_text: str
    span: str = ""
    instruction: str = ""


@app.post("/api/brain/rewrite")
def brain_rewrite_section(b: BrainRWBody):
    """设定文件 AI 改写:只生成候选、不落盘(作者在编辑器确认后走既有保存链路)。"""
    from .brainedit import check_rel, rewrite_section
    root = Path(b.root)
    try:
        check_rel(b.rel)   # 守卫先行:rel 不合法就别碰 config/backend,报错才是守卫文案而非 key 缺失
        out = rewrite_section(root, b.rel, b.full_text, b.span, b.instruction, get_backend(load_config(root)))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    return {"ok": True, "rewritten": out}


@app.post("/api/brain/continue")
def brain_continue_section(b: BrainRWBody):
    """设定文件 AI 续写:同上,只生成不落盘。"""
    from .brainedit import check_rel, continue_section
    root = Path(b.root)
    try:
        check_rel(b.rel)
        out = continue_section(root, b.rel, b.full_text, b.instruction, get_backend(load_config(root)))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    return {"ok": True, "continued": out}


@app.post("/api/outline/regen")
def outline_regen(b: ChapterBody):
    """重新生成第 N 章细纲(设定师→大纲师),覆盖 正文/.细纲/第N章.md 并返回。不碰正文。"""
    root = Path(b.root)
    try:
        text = usecases.regen_outline(root, b.chapter)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    return {"ok": True, "outline": text}


@app.post("/api/chapter/debug")
def chapter_debug(b: ChapterBody):
    """手动除虫第 N 章:跨章连续性报告(非阻断)+ 本章状态入账。"""
    try:
        rep = usecases.debug_chapter(Path(b.root), b.chapter)
    except (LoomBackendError, ValueError, FileNotFoundError, OSError) as e:
        return _err_json(e)
    return {"ok": True, **rep}


@app.post("/api/learn/revert")
def learn_revert(b: ChapterBody):
    p = usecases.learn_revert(Path(b.root), b.chapter)
    if p is None:
        return JSONResponse({"error": "没有可撤销的 learn 备份(可能已撤过)。"}, status_code=400)
    return {"ok": True, "fingerprint": p.read_text(encoding="utf-8")}


# ----------------------------- 局部重写 -----------------------------
class RewriteBody(BaseModel):
    root: str
    chapter: int
    full_text: str
    span: str
    instruction: str = ""


@app.post("/api/rewrite")
def rewrite(b: RewriteBody):
    """只重写选中段(整章作上下文,按写作指纹的嗓音);不落盘,返回候选。"""
    from .rewrite import rewrite_span
    root = Path(b.root)
    try:
        out = rewrite_span(root, b.chapter, b.full_text, b.span, b.instruction, get_backend(load_config(root)))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
    return {"rewritten": out}


class RewriteApplyBody(BaseModel):
    root: str
    chapter: int
    content: str
    old_span: str
    new_span: str


@app.post("/api/rewrite/apply")
def rewrite_apply(b: RewriteApplyBody):
    """应用重写:落盘正文 + 外科式同步 .原稿 快照(守 learn 不被 AI 重写污染)。"""
    usecases.rewrite_apply(Path(b.root), b.chapter, b.content, b.old_span, b.new_span)
    return {"ok": True}


# ----------------------------- write(流式) -----------------------------
class WriteBody(BaseModel):
    root: str
    chapter: int
    force: bool = False


@app.post("/api/write")
def write(b: WriteBody):
    root = Path(b.root)
    rej = usecases.write_precheck(root, b.chapter, b.force)   # 已存在 / drifted / force 三态
    if rej:
        return JSONResponse(rej, status_code=409)

    lock = usecases.acquire_lock(root)   # 拿不到 → ProjectBusyError → 409(流式场景锁随 worker)

    q: queue.Queue = queue.Queue()
    root_str = str(root)

    def _gate_aware_put(ev: dict) -> None:
        """写章进度回调:拦截 gate_issues 事件,积累 issues_detail。"""
        if ev.get("type") == "gate_issues" and "issues_detail" in ev:
            _store_gate_detail(root_str, b.chapter, ev["issues_detail"])
        q.put(ev)

    def worker():
        try:
            usecases.write_chapter(root, b.chapter, _gate_aware_put, force=b.force, slow=0.25)
        except LoomBackendError as e:
            q.put(events.error(str(e), code=e.code))   # code 透传,前端据此附可操作提示
        except (ValueError, FileNotFoundError) as e:
            q.put(events.error(str(e)))
        except Exception as e:  # 兜底,别让流挂死
            q.put(events.error(f"意外错误:{e}"))
        finally:
            lock.release()   # 锁跟着 worker 走(响应流着,写还没完),在哨兵 None 之前放
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class GateDetailBody(BaseModel):
    root: str
    chapter: int


@app.post("/api/write/gate-detail")
def gate_detail_ep(b: GateDetailBody):
    """返回结构化 Gate 审稿结果:包含每条 Issue 的 category/severity/paragraph_index/original_text/suggestion。"""
    detail = _get_gate_detail(b.root, b.chapter)
    return {"ok": True, "gate_detail": detail}


# ----------------------------- 书房伙伴(对话) -----------------------------
class PartnerSayBody(BaseModel):
    root: str
    text: str


class PartnerConfirmBody(BaseModel):
    root: str
    id: str


@app.post("/api/partner/say")
def partner_say(b: PartnerSayBody):
    """对话一轮,ndjson 流(user/assistant/assistant_delta/tool/result/proposal/error)。
    锁裁量红线(spec §10):独立 partner 轮锁,完全不碰书写锁——织章持写锁跑几分钟期间,
    say 照样能聊,只挡两次并发 say 交错写同一 .伙伴对话/当前.jsonl。backend 用主模型
    (get_backend),不走 cheap_backend:对话是主体验。"""
    root = Path(b.root)
    lock = usecases.acquire_partner_lock(root)   # 拿不到 → ProjectBusyError(partner_busy) → 409

    q: queue.Queue = queue.Queue()
    cancel = threading.Event()

    def worker():
        ts = time.strftime("%Y%m%d-%H%M%S")
        try:
            cfg = load_config(root)
            partner.run_turn(root, b.text, get_backend(cfg), emit=q.put, ts=ts,
                             should_cancel=cancel.is_set)
        except LoomBackendError as e:
            # partner 流信封是 {"t":...,"ts":...}(非 /api/write 的 type-keyed),error 事件跟随;
            # code 透传,前端据此附可操作提示;e.code 为 None 时不出 code 键
            err_ev = {"t": "error", "text": str(e), "ts": ts}
            if e.code:
                err_ev["code"] = e.code
            q.put(err_ev)
        except (ValueError, FileNotFoundError) as e:
            q.put({"t": "error", "text": str(e), "ts": ts})
        except Exception as e:  # 兜底,别让流挂死
            q.put({"t": "error", "text": f"意外错误:{e}", "ts": ts})
        finally:
            lock.release()   # 锁跟着 worker 走(响应流着,轮还没完),在哨兵 None 之前放
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        try:
            while True:
                ev = q.get()
                if ev is None:
                    break
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        finally:
            # 客户端断连(前端 abort)→ 生成器被关闭 → 置取消旗,worker 下一轮边界停并放锁。
            # 正常收尾(哨兵 None break)时 worker 已 return,置旗是无副作用的 no-op(spec §10.3)。
            cancel.set()

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/partner/confirm")
def partner_confirm_ep(b: PartnerConfirmBody):
    """拍板落盘(非流式,走真书写锁):找 proposal → 落进对应槽位 → 记 confirm 事件。"""
    try:
        return usecases.partner_confirm(Path(b.root), b.id, ts=time.strftime("%Y%m%d-%H%M%S"))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/partner/new")
def partner_new_ep(b: RootBody):
    """归档当前伙伴对话、另起一段(走真书写锁;不动书内容,只挪 jsonl 文件)。"""
    try:
        return usecases.partner_new(Path(b.root), stamp=time.strftime("%Y%m%d-%H%M%S"))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.get("/api/partner/history")
def partner_history_ep(root: str):
    """纯读派生视图,无锁(同 journey_state)。"""
    return usecases.partner_history(Path(root))


# 静态界面挂在最后(/api/* 已先匹配)
app.mount("/", StaticFiles(directory=str(WEBUI_DIR), html=True), name="ui")
