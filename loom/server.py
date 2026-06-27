"""本地 FastAPI 服务:把 loom 引擎暴露成 JSON / 流式接口给 Web 界面。

只监听 127.0.0.1,单用户本地桌面应用,不做鉴权。
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import run_pipeline
from .backends import (LoomBackendError, get_backend, list_models, probe as probe_backend,
                       provider_catalog, validate_model)
from . import chapters as chap
from . import projects as project_registry
from .chaptertext import parse_title, strip_title
from . import ledger
from .config import (Config, key_is_set, key_status, load_config, openai_compat_key_is_set,
                     save_config, set_env_key, set_global_env_key, set_openai_compat_key)
from .doctor import AGENT_FILES, BRAIN_FILES, report, run_checks
from .fingerprint import changed_rules, neutral_default, revert_learn
from .fingerprint import learn as fp_learn
from .fingerprint import seed_from_inherit, seed_from_samples
from .fsutil import atomic_write_text, list_history, restore_history, safe_join, snapshot_chapter
from .scaffold import available_genres
from .scaffold import init as scaffold_init
from .state import load_state

WEBUI_DIR = Path(__file__).parent / "webui"

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

# ---- 编辑器允许读写的文件(外置大脑可改、skills/agents 只读展示) ----
# 外置大脑四件套 / 5 个 agent 的清单单一真相在 doctor.py(BRAIN_FILES/AGENT_FILES)。
_SKILLS = ["世界观引擎.md", "故事引擎.md", "网文大神.md", "黄金开篇.md", "评估自检.md", "去AI味.md", "金手指.md"]


def _is_project(p: Path) -> bool:
    return (p / "loom.toml").exists()


def _state(root: Path) -> dict:
    cfg = load_config(root)
    st = load_state(root)
    body = root / "正文"
    chapters = sorted(int(p.stem[1:-1]) for p in body.glob("第*章.md")) if body.exists() else []
    chs = []
    for n in chapters:
        out, snap = body / f"第{n}章.md", body / ".原稿" / f"第{n}章.md"
        out_text = out.read_text(encoding="utf-8")
        # 「改过」只看正文体(去掉标题再比):改标题不算手改、不该亮「改过」徽标(与 learn/drift 同口径)
        edited = snap.exists() and strip_title(out_text).strip() != strip_title(snap.read_text(encoding="utf-8")).strip()
        chs.append({"n": n, "title": parse_title(out_text), "written": True,
                    "edited": edited, "learned": n in set(st.get("learned", []))})
    return {
        "root": str(root),
        "title": cfg.title,
        "backend": {"provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url,
                    "chapter_chars": cfg.chapter_chars, "key_set": key_is_set(root),
                    "key_status": key_status(root),
                    "openai_compat_key_set": openai_compat_key_is_set(root),
                    "providers": provider_catalog()},
        "fingerprint_source": st.get("fingerprint_source", "default"),
        "brain": [{"rel": f"外置大脑/{n}.md", "name": n} for n in BRAIN_FILES]
                 + ([{"rel": "外置大脑/违禁词.md", "name": "违禁词"}]
                    if (root / "外置大脑" / "违禁词.md").is_file() else []),
        "skills": [{"rel": f"skills/{n}", "name": n[:-3]} for n in _SKILLS],
        "agents": [{"rel": f"agents/{n}.md", "name": n} for n in AGENT_FILES],
        "chapters": chs,
        "next_chapter": (chapters[-1] + 1) if chapters else 1,
    }


# ----------------------------- 项目 -----------------------------
class CreateBody(BaseModel):
    name: str
    parent: str
    genre: str | None = None


class RootBody(BaseModel):
    root: str


class DefaultDirBody(BaseModel):
    path: str


@app.get("/api/genres")
def genres():
    return {"genres": available_genres()}


@app.get("/api/projects")
def projects_list():
    return project_registry.list_all()


@app.post("/api/projects/register")
def register_project(b: RootBody):
    root = Path(b.root).expanduser()
    if not _is_project(root):
        return JSONResponse({"error": f"{root} is not a loom project (missing loom.toml)."}, status_code=400)
    return project_registry.register(root)


@app.delete("/api/projects/{name}")
def delete_project(name: str):
    project_registry.remove(name)
    return project_registry.list_all()


@app.put("/api/projects/default-dir")
def update_default_dir(b: DefaultDirBody):
    return project_registry.set_default_dir(Path(b.path))


@app.post("/api/project/create")
def create_project(b: CreateBody):
    try:
        root = scaffold_init(b.name, Path(b.parent).expanduser(), b.genre)
    except (FileExistsError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    project_registry.register(root, default_dir=Path(b.parent).expanduser())
    return _state(root)


class ParentBody(BaseModel):
    parent: str


@app.post("/api/sample/open")
def sample_open(b: ParentBody):
    """拷一份内置样例书到 parent 并打开,让陌生作者先看一本跑通的书。"""
    from .scaffold import open_sample
    parent = Path(b.parent).expanduser()
    root = open_sample(parent)
    project_registry.register(root, default_dir=parent)
    return _state(root)


@app.post("/api/project/open")
def open_project(b: RootBody):
    root = Path(b.root).expanduser()
    if not _is_project(root):
        return JSONResponse({"error": f"{root} 不是 loom 项目(没有 loom.toml)。"}, status_code=400)
    try:
        state = _state(root)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    project_registry.register(root)
    return state


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
        content = restore_history(b.root, b.rel, b.id)  # 回滚前会先把当前版本也存一份
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


class GlobalKeyBody(BaseModel):
    root: str
    api_key: str


@app.get("/api/backend/probe")
def backend_probe(provider: str):
    return probe_backend(provider)


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


@app.post("/api/chapter/delete")
def chapter_delete(b: ChapterOpBody):
    try:
        return {**chap.delete_chapter(b.root, b.n), **{"state": _state(Path(b.root))}}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/chapter/insert")
def chapter_insert(b: ChapterOpBody):
    try:
        return {**chap.insert_after(b.root, b.n), **{"state": _state(Path(b.root))}}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/chapter/move")
def chapter_move(b: ChapterOpBody):
    try:
        return {**chap.move_chapter(b.root, b.n, b.direction or "up"), **{"state": _state(Path(b.root))}}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


class ScanBody(BaseModel):
    root: str
    text: str


@app.post("/api/sensitive/scan")
def sensitive_scan(b: ScanBody):
    from .sensitive import scan
    return {"hits": scan(b.text, b.root)}


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
        # key 按供应商分别落到对的 env var:DeepSeek→DEEPSEEK_API_KEY,自定义→LOOM_OPENAI_COMPAT_KEY(各占一行)
        if b.provider == "openai_compat":
            set_openai_compat_key(root, b.api_key.strip())
        else:
            set_env_key(root, b.api_key.strip())
    st = _state(root)
    warn = validate_model(b.provider, b.model)   # 软提示(如把 v4-flash 填进 deepseek)——只提示,不阻断保存
    if warn:
        st["model_warning"] = warn
    return st


@app.post("/api/settings/global-key")
def update_global_key(b: GlobalKeyBody):
    key = (b.api_key or "").strip()
    if not key:
        return JSONResponse({"error": "API Key 不能为空"}, status_code=400)
    try:
        set_global_env_key(key)
    except OSError as e:
        return JSONResponse({"error": f"写入全局 API Key 失败:{e}"}, status_code=500)
    return _state(Path(b.root))


# ----------------------------- seed / learn -----------------------------
class SeedBody(BaseModel):
    root: str
    text: str | None = None
    inherit: str | None = None


@app.post("/api/seed")
def seed(b: SeedBody):
    root = Path(b.root)
    try:
        if b.inherit:
            seed_from_inherit(root, Path(b.inherit).expanduser())
        else:
            seed_from_samples(root, b.text or "", get_backend(load_config(root)))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _state(root)


class ChapterBody(BaseModel):
    root: str
    chapter: int


@app.post("/api/learn")
def learn(b: ChapterBody):
    root = Path(b.root)
    fp_file = root / "外置大脑" / "写作指纹.md"
    # 缺文件时用 neutral_default 兜底,与 learn() 内部的旧指纹基线同源(否则 changes 会全量误报)
    old_fp = fp_file.read_text(encoding="utf-8") if fp_file.exists() else neutral_default()
    events: list[dict] = []
    try:
        fp_learn(root, b.chapter, get_backend(load_config(root)), events.append)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    new_fp = fp_file.read_text(encoding="utf-8")
    from .enrich import extract_supplement
    world_p = root / "外置大脑" / "世界观.md"
    chars_p = root / "外置大脑" / "人物卡.md"
    world_supp = extract_supplement(world_p.read_text(encoding="utf-8"), b.chapter) if world_p.exists() else ""
    chars_supp = extract_supplement(chars_p.read_text(encoding="utf-8"), b.chapter) if chars_p.exists() else ""
    done = next((e for e in events if e.get("type") == "learn_done"), {})
    return {"ok": True,
            "fingerprint": new_fp,
            "卡章纲": (root / "外置大脑" / "卡章纲.md").read_text(encoding="utf-8"),
            "changes": changed_rules(old_fp, new_fp),
            "世界观补充": world_supp,
            "人物卡补充": chars_supp,
            "warn": done.get("shrink_warning") or ""}   # 软提示:疑似把嗓音磨短/丢 anchor,可一键撤销


class DraftBody(BaseModel):
    root: str
    idea: str = ""


@app.post("/api/brain/draft")
def brain_draft(b: DraftBody):
    """从书名+题材+一句话设定,AI 起草 世界观/人物卡/卡章纲 初稿(只覆盖空白/模板,不动你写的)。"""
    from .draft import draft_brain
    root = Path(b.root)
    try:
        res = draft_brain(root, b.idea, get_backend(load_config(root)))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "written": list(res["written"].keys()),
            "skipped": res["skipped"], "state": _state(root)}


@app.post("/api/outline/regen")
def outline_regen(b: ChapterBody):
    """重新生成第 N 章细纲(设定师→大纲师),覆盖 正文/.细纲/第N章.md 并返回。不碰正文。"""
    from .agents import regen_outline
    root = Path(b.root)
    cfg = load_config(root)
    try:
        text = regen_outline(root, b.chapter, get_backend(cfg), cfg)
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "outline": text}


@app.post("/api/learn/revert")
def learn_revert(b: ChapterBody):
    p = revert_learn(Path(b.root), b.chapter)
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
        return JSONResponse({"error": str(e)}, status_code=400)
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
    from .rewrite import apply_rewrite
    apply_rewrite(Path(b.root), b.chapter, b.content, b.old_span, b.new_span)
    return {"ok": True}


# ----------------------------- write(流式) -----------------------------
class WriteBody(BaseModel):
    root: str
    chapter: int
    force: bool = False


@app.post("/api/write")
def write(b: WriteBody):
    root = Path(b.root)
    out = root / "正文" / f"第{b.chapter}章.md"
    if out.exists() and not b.force:
        if ledger.chapter_drifted(root, b.chapter):
            return JSONResponse(
                {"error": f"第 {b.chapter} 章正文与上次记录不符(手改过?)。先 learn,或勾选覆盖以你的正文为准重写。",
                 "code": "chapter_drifted"}, status_code=409)
        return JSONResponse(
            {"error": f"第 {b.chapter} 章已写完。要重写请勾选覆盖。", "code": "chapter_exists"}, status_code=409)

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            cfg = load_config(root)
            backend = get_backend(cfg)
            # out 不存在=上次没跑完(断点),resume 跳过已落盘且上游未变的工序
            run_pipeline(root, b.chapter, backend, cfg, q.put, slow=0.25, resume=not b.force)
        except (LoomBackendError, ValueError, FileNotFoundError) as e:
            q.put({"type": "error", "message": str(e)})
        except Exception as e:  # 兜底,别让流挂死
            q.put({"type": "error", "message": f"意外错误:{e}"})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# 静态界面挂在最后(/api/* 已先匹配)
app.mount("/", StaticFiles(directory=str(WEBUI_DIR), html=True), name="ui")
