# Chapter Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build batch chapter planning that generates editable per-chapter outlines, streams progress, and exposes the workflow in the web UI.

**Architecture:** Add a focused `loom/chapter_plan.py` service that plans chapters sequentially and writes `正文/.细纲/第N章.md` as the source consumed by the existing writing pipeline. Add a FastAPI NDJSON streaming endpoint modeled on `/api/write`. Add a compact sidebar planning panel that streams events, reports progress, and opens generated outlines in the existing editor.

**Tech Stack:** Python 3.11, FastAPI `StreamingResponse`, pytest, existing Loom backend abstraction, vanilla HTML/CSS/JS web UI.

---

## File Structure

- Create `loom/chapter_plan.py`: planning prompts, validation, per-chapter outline paths, atomic writes, card-outline sync, progress events.
- Create `tests/test_chapter_plan.py`: unit tests for generation ranges, skip/force behavior, validation, and event stream shape.
- Modify `loom/server.py`: import `chapter_plan`, add `PlanGenerateBody`, add `POST /api/plan/generate`.
- Create `tests/test_plan_endpoint.py`: endpoint-level stream test with patched backend.
- Modify `loom/webui/index.html`: add the chapter planning panel in the sidebar.
- Modify `loom/webui/app.js`: bind controls, stream `/api/plan/generate`, update progress, open generated outline files.
- Modify `loom/webui/style.css`: style the compact planning panel and generated list.

---

### Task 1: Core Chapter Planning Service

**Files:**
- Create: `loom/chapter_plan.py`
- Create: `tests/test_chapter_plan.py`

- [ ] **Step 1: Write failing tests for planning service behavior**

Create `tests/test_chapter_plan.py` with these tests:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from loom.chapter_plan import outline_path, plan_chapters
from tests.conftest import FakeBackend


def outline_text(chapter: int) -> str:
    return f"第{chapter}章：目标、冲突、反转、章末钩子都清楚。"


def backend_for_chapters():
    def respond(system: str, user: str) -> str:
        for n in range(1, 10):
            if f"第 {n} 章" in user or f"第{n}章" in user:
                return outline_text(n)
        return "第0章：备用细纲。"
    return FakeBackend(respond)


def test_plan_chapters_writes_each_outline_and_emits_events(project: Path) -> None:
    events: list[dict] = []

    result = plan_chapters(project, total=3, backend=backend_for_chapters(), progress=events.append)

    assert result == {"planned": 3, "skipped": 0, "chapters": [1, 2, 3]}
    assert outline_path(project, 1).read_text(encoding="utf-8").strip() == outline_text(1)
    assert outline_path(project, 2).read_text(encoding="utf-8").strip() == outline_text(2)
    assert outline_path(project, 3).read_text(encoding="utf-8").strip() == outline_text(3)
    assert [e["type"] for e in events] == [
        "progress", "done", "progress", "done", "progress", "done", "complete"
    ]
    assert events[-1] == {"type": "complete", "planned": 3, "skipped": 0}


def test_plan_chapters_starts_from_requested_chapter(project: Path) -> None:
    events: list[dict] = []

    result = plan_chapters(project, total=5, start_from=3, backend=backend_for_chapters(), progress=events.append)

    assert result["chapters"] == [3, 4, 5]
    assert not outline_path(project, 2).exists()
    assert outline_path(project, 3).read_text(encoding="utf-8").strip() == outline_text(3)
    assert [e["chapter"] for e in events if e["type"] == "done"] == [3, 4, 5]


def test_existing_outline_is_skipped_without_force(project: Path) -> None:
    existing = outline_path(project, 2)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("作者手写的第2章细纲\n", encoding="utf-8")
    events: list[dict] = []

    result = plan_chapters(project, total=2, backend=backend_for_chapters(), progress=events.append)

    assert result == {"planned": 1, "skipped": 1, "chapters": [1]}
    assert existing.read_text(encoding="utf-8") == "作者手写的第2章细纲\n"
    assert any(e["type"] == "skip" and e["chapter"] == 2 for e in events)


def test_existing_outline_is_overwritten_with_force(project: Path) -> None:
    existing = outline_path(project, 1)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("旧细纲\n", encoding="utf-8")

    plan_chapters(project, total=1, backend=backend_for_chapters(), force=True)

    assert existing.read_text(encoding="utf-8").strip() == outline_text(1)


@pytest.mark.parametrize(
    ("total", "start_from"),
    [(0, 1), (1, 0), (2, 3)],
)
def test_invalid_ranges_raise_value_error(project: Path, total: int, start_from: int) -> None:
    with pytest.raises(ValueError):
        plan_chapters(project, total=total, start_from=start_from, backend=backend_for_chapters())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_chapter_plan.py -q
```

Expected: import failure for `loom.chapter_plan`.

- [ ] **Step 3: Implement `loom/chapter_plan.py`**

Create `loom/chapter_plan.py` with these public functions and behavior:

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .backends import Backend, LoomBackendError
from .config import load_config
from .fsutil import atomic_write_text
from .guard import STEP, validate_output

Progress = Callable[[dict], None]


def _noop(event: dict) -> None:
    pass


def outline_path(project_root: Path, chapter_n: int) -> Path:
    return project_root / "正文" / ".细纲" / f"第{chapter_n}章.md"


def card_outline_path(project_root: Path) -> Path:
    return project_root / "外置大脑" / "卡章纲.md"
```

Implement helpers:

```python
def _validate(project_root: Path, total: int, start_from: int) -> None:
    if not (project_root / "loom.toml").is_file():
        raise FileNotFoundError(f"{project_root} is not a loom project (missing loom.toml).")
    if total < 1:
        raise ValueError("total must be at least 1")
    if start_from < 1:
        raise ValueError("start_from must be at least 1")
    if start_from > total:
        raise ValueError("start_from cannot be greater than total")


def _read_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
```

Implement `plan_chapters` with this signature:

```python
def plan_chapters(
    project_root: Path,
    total: int,
    backend: Backend,
    *,
    start_from: int = 1,
    force: bool = False,
    progress: Progress = _noop,
) -> dict:
```

Inside `plan_chapters`:

- call `_validate`;
- load project config with `load_config(project_root)` for title/model context;
- for every chapter in `range(start_from, total + 1)`, emit `progress`;
- if outline exists and is non-empty and `force` is false, emit `skip` and continue;
- call `backend.complete(system_prompt, user_prompt, max_chars=700)`;
- reject empty/invalid output with `LoomBackendError`;
- write the outline with `atomic_write_text(outline_path(...), outline.strip() + "\n")`;
- emit `done`;
- after the loop, emit `complete`;
- return `{"planned": planned_count, "skipped": skipped_count, "chapters": planned_chapters}`.

Use a concise prompt that includes title, chapter number, total count, current card outline, world view, character card, and previous generated outline when available.

- [ ] **Step 4: Run core tests to verify they pass**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_chapter_plan.py -q
```

Expected: all tests in `tests/test_chapter_plan.py` pass.

- [ ] **Step 5: Commit core service**

Run:

```powershell
git add loom/chapter_plan.py tests/test_chapter_plan.py
git commit -m "feat: add chapter planning service"
```

---

### Task 2: Streaming Plan API

**Files:**
- Modify: `loom/server.py`
- Create: `tests/test_plan_endpoint.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `tests/test_plan_endpoint.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from loom import server


class EndpointBackend:
    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None) -> str:
        chapter = 1
        if "第 2 章" in user or "第2章" in user:
            chapter = 2
        out = f"第{chapter}章：端点生成的细纲。"
        if on_chunk:
            on_chunk(out)
        return out


def parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_plan_generate_streams_events_and_writes_outlines(project: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "get_backend", lambda cfg: EndpointBackend())
    client = TestClient(server.app, base_url="http://127.0.0.1")

    response = client.post(
        "/api/plan/generate",
        json={"root": str(project), "total_chapters": 2, "start_from": 1, "force": False},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = parse_ndjson(response.text)
    assert [e["type"] for e in events] == ["progress", "done", "progress", "done", "complete"]
    assert (project / "正文" / ".细纲" / "第1章.md").is_file()
    assert (project / "正文" / ".细纲" / "第2章.md").is_file()


def test_plan_generate_rejects_invalid_root() -> None:
    client = TestClient(server.app, base_url="http://127.0.0.1")

    response = client.post(
        "/api/plan/generate",
        json={"root": "Z:/missing/book", "total_chapters": 2},
    )

    events = parse_ndjson(response.text)
    assert response.status_code == 200
    assert events[-1]["type"] == "error"
```

- [ ] **Step 2: Run endpoint tests to verify they fail**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_plan_endpoint.py -q
```

Expected: 404 for `/api/plan/generate` or missing `PlanGenerateBody`.

- [ ] **Step 3: Add server endpoint**

Modify `loom/server.py`:

- add `from . import chapter_plan` near existing local imports;
- add a Pydantic body near `WriteBody`:

```python
class PlanGenerateBody(BaseModel):
    root: str
    total_chapters: int
    start_from: int = 1
    force: bool = False
```

- add `plan_generate` before `app.mount(...)`:

```python
@app.post("/api/plan/generate")
def plan_generate(b: PlanGenerateBody):
    root = Path(b.root).expanduser()
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            cfg = load_config(root)
            backend = get_backend(cfg)
            chapter_plan.plan_chapters(
                root,
                b.total_chapters,
                backend,
                start_from=b.start_from,
                force=b.force,
                progress=q.put,
            )
        except (LoomBackendError, ValueError, FileNotFoundError) as e:
            q.put({"type": "error", "message": str(e)})
        except Exception as e:
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
```

- [ ] **Step 4: Run endpoint tests and core tests**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_chapter_plan.py tests\test_plan_endpoint.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit API endpoint**

Run:

```powershell
git add loom/server.py tests/test_plan_endpoint.py
git commit -m "feat: expose chapter planning api"
```

---

### Task 3: Web UI Planning Panel

**Files:**
- Modify: `loom/webui/index.html`
- Modify: `loom/webui/app.js`
- Modify: `loom/webui/style.css`

- [ ] **Step 1: Add UI markup**

In `loom/webui/index.html`, inside the `正文` sidebar section after `<ul id="chapters" class="list"></ul>`, add:

```html
<div class="plan-panel">
  <div class="plan-head">
    <span><span class="ico" data-ico="outline"></span> 章节规划</span>
  </div>
  <div class="plan-grid">
    <label>总章数 <input id="plan-total" type="number" min="1" step="1" /></label>
    <label>起始章 <input id="plan-start" type="number" min="1" step="1" /></label>
  </div>
  <label class="check-row"><input id="plan-force" type="checkbox" /> 覆盖已有细纲</label>
  <button id="btn-plan-generate" class="mini"><span class="ico" data-ico="outline"></span> 批量生成细纲</button>
  <div id="plan-status" class="plan-status"></div>
  <div id="plan-results" class="plan-results"></div>
</div>
```

- [ ] **Step 2: Add JS bindings and streaming behavior**

In `loom/webui/app.js`:

- add `planning: "icon-doc"` to `IC` only if a separate alias is useful, otherwise reuse `outline`;
- in `bind()`, add:

```javascript
const planBtn = $("btn-plan-generate");
if (planBtn) planBtn.onclick = generateChapterPlan;
```

- in `render()`, after setting `btn-write-next`, initialize defaults without clobbering active user input:

```javascript
const total = $("plan-total");
const start = $("plan-start");
if (total && (!total.value || Number(total.value) < DATA.next_chapter)) total.value = Math.max(DATA.next_chapter, 1);
if (start && (!start.value || Number(start.value) < 1)) start.value = DATA.next_chapter || 1;
```

- add helper functions near `writeChapter()`:

```javascript
function appendPlanResult(chapter, outline, skipped) {
  const list = $("plan-results");
  if (!list) return;
  const row = document.createElement("button");
  row.type = "button";
  row.className = "plan-result" + (skipped ? " skipped" : "");
  row.innerHTML = `<span>第${chapter}章</span><small>${skipped ? "已跳过" : escHtml((outline || "").slice(0, 36))}</small>`;
  row.onclick = () => openFile(`正文/.细纲/第${chapter}章.md`, true, chapter);
  list.appendChild(row);
}

async function generateChapterPlan() {
  if (!DATA) return;
  const total = parseInt($("plan-total").value, 10);
  const start = parseInt($("plan-start").value, 10) || 1;
  const force = $("plan-force").checked;
  const btn = $("btn-plan-generate");
  const status = $("plan-status");
  const results = $("plan-results");
  if (!total || total < 1 || start < 1 || start > total) {
    toast("检查总章数和起始章", true);
    return;
  }
  btn.disabled = true;
  status.textContent = "规划中...";
  results.innerHTML = "";
  try {
    await persistBackend(true);
    const response = await fetch("/api/plan/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: DATA.root, total_chapters: total, start_from: start, force }),
    });
    if (!response.ok) throw new Error(`请求失败 (${response.status})`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) handlePlanEvent(JSON.parse(line));
    }
    if (buffer.trim()) handlePlanEvent(JSON.parse(buffer));
    await refresh();
  } catch (e) {
    toast(e.message, true);
    status.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

function handlePlanEvent(ev) {
  const status = $("plan-status");
  if (ev.type === "progress") status.textContent = `正在规划第${ev.chapter}章 / 共${ev.total}章`;
  else if (ev.type === "done") {
    status.textContent = `第${ev.chapter}章细纲已生成`;
    appendPlanResult(ev.chapter, ev.outline, false);
  } else if (ev.type === "skip") {
    status.textContent = `第${ev.chapter}章已有细纲，已跳过`;
    appendPlanResult(ev.chapter, "", true);
  } else if (ev.type === "complete") {
    status.textContent = `完成：生成 ${ev.planned} 章，跳过 ${ev.skipped} 章`;
    toast(status.textContent);
  } else if (ev.type === "error") {
    status.textContent = ev.message || "规划失败";
    toast(status.textContent, true);
  }
}
```

- [ ] **Step 3: Add CSS**

In `loom/webui/style.css`, near sidebar styles, add:

```css
.plan-panel {
  margin: var(--space-3) 0 var(--space-4);
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-sunken);
}
.plan-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--space-2);
  color: var(--text-soft);
  font-size: var(--fs-xs);
  font-weight: 700;
}
.plan-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}
.plan-grid label, .check-row {
  color: var(--text-soft);
  font-size: var(--fs-caption);
}
.plan-grid input {
  margin-top: 3px;
  padding: 5px 7px;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: var(--space-2) 0;
}
.check-row input {
  width: auto;
}
#btn-plan-generate {
  width: 100%;
}
.plan-status {
  min-height: 18px;
  margin-top: var(--space-2);
  color: var(--text-mute);
  font-size: var(--fs-caption);
}
.plan-results {
  display: grid;
  gap: 4px;
  margin-top: var(--space-2);
}
.plan-result {
  display: grid;
  gap: 2px;
  width: 100%;
  min-width: 0;
  padding: 6px 8px;
  text-align: left;
  background: var(--surface);
}
.plan-result span, .plan-result small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.plan-result small {
  color: var(--text-mute);
  font-size: var(--fs-caption);
}
.plan-result.skipped {
  opacity: .72;
}
```

- [ ] **Step 4: Verify frontend syntax**

Run:

```powershell
node --check loom\webui\app.js
```

Expected: exit 0.

- [ ] **Step 5: Commit web UI**

Run:

```powershell
git add loom/webui/index.html loom/webui/app.js loom/webui/style.css
git commit -m "feat: add chapter planning panel"
```

---

### Task 4: Final Verification and Review

**Files:**
- Review all changed files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_chapter_plan.py tests\test_plan_endpoint.py -q
```

Expected: selected tests pass.

- [ ] **Step 2: Run full tests**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q
```

Expected: full suite passes.

- [ ] **Step 3: Run compile and syntax checks**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m compileall loom tests
node --check loom\webui\app.js
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Request final code review**

Dispatch a reviewer with:

- Description: “Batch chapter planning service, streaming endpoint, and web UI panel.”
- Requirements: this plan plus `docs/superpowers/specs/2026-06-27-chapter-planning-design.md`.
- Base SHA: commit before Task 1 implementation.
- Head SHA: current branch head.

- [ ] **Step 5: Fix review findings and commit fixes**

If review finds Critical or Important issues, fix them with tests first and commit:

```powershell
git add <changed-files>
git commit -m "fix: address chapter planning review"
```

- [ ] **Step 6: Finish branch**

After all verification passes and review has no blocking findings, use the finishing workflow to present merge/PR/keep options.
