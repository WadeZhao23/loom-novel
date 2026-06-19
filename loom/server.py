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
from .backends import LoomBackendError, get_backend
from .config import Config, key_is_set, load_config, save_config, set_env_key
from .doctor import AGENT_FILES, BRAIN_FILES, report, run_checks
from .fingerprint import learn as fp_learn
from .fingerprint import seed_from_inherit, seed_from_samples
from .scaffold import init as scaffold_init
from .state import load_state

WEBUI_DIR = Path(__file__).parent / "webui"

app = FastAPI(title="Loom")

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
        edited = snap.exists() and out.read_text(encoding="utf-8").strip() != snap.read_text(encoding="utf-8").strip()
        chs.append({"n": n, "written": True, "edited": edited, "learned": n in set(st.get("learned", []))})
    return {
        "root": str(root),
        "title": cfg.title,
        "backend": {"provider": cfg.provider, "model": cfg.model, "chapter_chars": cfg.chapter_chars,
                    "key_set": key_is_set(root)},
        "fingerprint_source": st.get("fingerprint_source", "default"),
        "brain": [{"rel": f"外置大脑/{n}.md", "name": n} for n in BRAIN_FILES],
        "skills": [{"rel": f"skills/{n}", "name": n[:-3]} for n in _SKILLS],
        "agents": [{"rel": f"agents/{n}.md", "name": n} for n in AGENT_FILES],
        "chapters": chs,
        "next_chapter": (chapters[-1] + 1) if chapters else 1,
    }


# ----------------------------- 项目 -----------------------------
class CreateBody(BaseModel):
    name: str
    parent: str


class RootBody(BaseModel):
    root: str


@app.post("/api/project/create")
def create_project(b: CreateBody):
    try:
        root = scaffold_init(b.name, Path(b.parent).expanduser())
    except (FileExistsError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _state(root)


@app.post("/api/project/open")
def open_project(b: RootBody):
    root = Path(b.root).expanduser()
    if not _is_project(root):
        return JSONResponse({"error": f"{root} 不是 loom 项目(没有 loom.toml)。"}, status_code=400)
    try:
        return _state(root)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/project/state")
def project_state(root: str):
    return _state(Path(root))


@app.get("/api/doctor")
def doctor(root: str):
    """只读启动自检:检查 key/后端命令/agent/外置大脑齐不齐。"""
    return report(run_checks(Path(root)))


# ----------------------------- 文件 -----------------------------
class FileBody(BaseModel):
    root: str
    rel: str
    content: str


@app.get("/api/file")
def read_file(root: str, rel: str):
    p = Path(root) / rel
    if not p.exists():
        return JSONResponse({"error": f"文件不存在:{rel}"}, status_code=404)
    return {"rel": rel, "content": p.read_text(encoding="utf-8")}


@app.put("/api/file")
def write_file(b: FileBody):
    p = Path(b.root) / b.rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(b.content, encoding="utf-8")
    return {"ok": True}


# ----------------------------- 后端配置 -----------------------------
class ConfigBody(BaseModel):
    root: str
    provider: str
    model: str
    chapter_chars: int
    api_key: str | None = None


@app.put("/api/config")
def update_config(b: ConfigBody):
    root = Path(b.root)
    cfg = load_config(root)
    save_config(root, Config(provider=b.provider, model=b.model, title=cfg.title, chapter_chars=b.chapter_chars))
    if b.api_key:
        set_env_key(root, b.api_key.strip())
    return _state(root)


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
    try:
        fp_learn(root, b.chapter, get_backend(load_config(root)))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True,
            "fingerprint": (root / "外置大脑" / "写作指纹.md").read_text(encoding="utf-8"),
            "卡章纲": (root / "外置大脑" / "卡章纲.md").read_text(encoding="utf-8")}


# ----------------------------- write(流式) -----------------------------
class WriteBody(BaseModel):
    root: str
    chapter: int
    force: bool = False


@app.post("/api/write")
def write(b: WriteBody):
    root = Path(b.root)
    out = root / "正文" / f"第{b.chapter}章.md"
    snap = root / "正文" / ".原稿" / f"第{b.chapter}章.md"
    if out.exists() and not b.force:
        edited = snap.exists() and out.read_text(encoding="utf-8").strip() != snap.read_text(encoding="utf-8").strip()
        msg = (f"第 {b.chapter} 章你手改过,重跑会覆盖。先 learn,或勾选覆盖。"
               if edited else f"第 {b.chapter} 章已存在。要重写请勾选覆盖。")
        return JSONResponse({"error": msg}, status_code=409)

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            cfg = load_config(root)
            backend = get_backend(cfg)
            run_pipeline(root, b.chapter, backend, cfg, q.put, slow=0.25)
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
