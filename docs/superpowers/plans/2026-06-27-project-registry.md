# Project Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-user Loom project registry and show remembered projects on the welcome screen.

**Architecture:** Add a focused `loom/projects.py` registry module backed by `~/.loom/projects.json`, expose it through small FastAPI endpoints, and integrate registration into existing create/open/sample flows. Keep the frontend welcome screen structure, adding a project list above the current controls.

**Tech Stack:** Python 3.11, FastAPI, pytest/unittest, vanilla HTML/CSS/JS, existing `atomic_write_text` helper.

---

## File Structure

- Create `loom/projects.py`: registry loading, saving, path normalization, CRUD, default directory.
- Create `tests/test_project_registry.py`: pure registry tests and server endpoint tests.
- Modify `loom/server.py`: import registry functions, add API models/endpoints, auto-register successful project opens/creates.
- Modify `loom/webui/index.html`: add project list container on welcome screen.
- Modify `loom/webui/app.js`: load/render project list, open/remove projects, keep default parent synchronized.
- Modify `loom/webui/style.css`: compact project list styling.

---

### Task 1: Registry Module

**Files:**
- Create: `loom/projects.py`
- Test: `tests/test_project_registry.py`

- [ ] **Step 1: Write failing registry tests**

Add tests that patch `Path.home()` through `unittest.mock.patch` so they never touch the real `~/.loom`.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from loom import projects


class ProjectRegistryTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.patcher = patch("loom.projects.Path.home", return_value=self.home)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def make_project(self, name="Book"):
        root = Path(self.tmp.name) / name
        root.mkdir()
        (root / "loom.toml").write_text("[backend]\nprovider = \"deepseek\"\n", encoding="utf-8")
        return root

    def test_empty_registry_has_default_shape(self):
        data = projects.load_registry()
        self.assertEqual(data, {"default_dir": "", "projects": {}})

    def test_register_adds_project_and_marks_existing(self):
        root = self.make_project("Alpha")
        data = projects.register(root)
        entry = data["projects"]["Alpha"]
        self.assertEqual(Path(entry["path"]), root.resolve())
        self.assertTrue(entry["created"])
        self.assertTrue(entry["last_open"])

        listed = projects.list_all()
        self.assertTrue(listed["projects"]["Alpha"]["exists"])

    def test_register_same_path_updates_last_open_without_duplicate(self):
        root = self.make_project("Alpha")
        first = projects.register(root)
        second = projects.register(root)
        self.assertEqual(list(second["projects"]), ["Alpha"])
        self.assertEqual(second["projects"]["Alpha"]["created"], first["projects"]["Alpha"]["created"])

    def test_register_same_name_different_path_gets_suffix(self):
        root1 = self.make_project("Alpha")
        root2_parent = Path(self.tmp.name) / "other"
        root2 = root2_parent / "Alpha"
        root2.mkdir(parents=True)
        (root2 / "loom.toml").write_text("[backend]\nprovider = \"deepseek\"\n", encoding="utf-8")
        data = projects.register(root1)
        data = projects.register(root2)
        self.assertEqual(set(data["projects"]), {"Alpha", "Alpha (2)"})

    def test_invalid_json_falls_back_to_empty_registry(self):
        path = projects.registry_path()
        path.parent.mkdir(parents=True)
        path.write_text("{bad json", encoding="utf-8")
        self.assertEqual(projects.load_registry(), {"default_dir": "", "projects": {}})

    def test_remove_is_idempotent(self):
        root = self.make_project("Alpha")
        projects.register(root)
        self.assertTrue(projects.remove("Alpha"))
        self.assertFalse(projects.remove("Alpha"))
        self.assertEqual(projects.list_all()["projects"], {})

    def test_set_default_dir_expands_and_saves_path(self):
        default = Path(self.tmp.name) / "books"
        data = projects.set_default_dir(default)
        self.assertEqual(Path(data["default_dir"]), default.resolve())
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_project_registry.py -q
```

Expected: FAIL because `loom.projects` does not exist.

- [ ] **Step 3: Implement `loom/projects.py`**

Create the module with this public API:

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import global_config_dir
from .fsutil import atomic_write_text


def registry_path() -> Path:
    return global_config_dir() / "projects.json"


def _empty() -> dict:
    return {"default_dir": "", "projects": {}}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _project_name(root: Path) -> str:
    return root.resolve().name or "未命名项目"


def _normalize(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return _empty()
    default_dir = data.get("default_dir", "")
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        projects = {}
    clean = {"default_dir": str(default_dir or ""), "projects": {}}
    for name, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        if not path:
            continue
        clean["projects"][str(name)] = {
            "path": path,
            "created": str(entry.get("created") or ""),
            "last_open": str(entry.get("last_open") or ""),
        }
    return clean


def load_registry() -> dict:
    path = registry_path()
    if not path.exists():
        return _empty()
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return _empty()


def save_registry(data: dict) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(_normalize(data), ensure_ascii=False, indent=2) + "\n")


def _with_exists(data: dict) -> dict:
    out = _normalize(data)
    for entry in out["projects"].values():
        entry["exists"] = Path(entry["path"]).exists()
    return out


def list_all() -> dict:
    return _with_exists(load_registry())


def _entry_name(data: dict, root: Path) -> str:
    root_resolved = root.resolve()
    base = _project_name(root)
    for name, entry in data["projects"].items():
        try:
            if Path(entry["path"]).resolve() == root_resolved:
                return name
        except OSError:
            continue
    if base not in data["projects"]:
        return base
    index = 2
    while f"{base} ({index})" in data["projects"]:
        index += 1
    return f"{base} ({index})"


def register(path: Path, *, default_dir: Path | None = None) -> dict:
    root = path.expanduser().resolve()
    data = load_registry()
    name = _entry_name(data, root)
    now = _now()
    previous = data["projects"].get(name, {})
    data["projects"][name] = {
        "path": str(root),
        "created": previous.get("created") or now,
        "last_open": now,
    }
    if default_dir is not None:
        data["default_dir"] = str(default_dir.expanduser().resolve())
    save_registry(data)
    return list_all()


def remove(name: str) -> bool:
    data = load_registry()
    existed = name in data["projects"]
    data["projects"].pop(name, None)
    save_registry(data)
    return existed


def set_default_dir(path: Path) -> dict:
    data = load_registry()
    data["default_dir"] = str(path.expanduser().resolve())
    save_registry(data)
    return list_all()


def get_default_dir() -> str:
    return load_registry()["default_dir"]
```

- [ ] **Step 4: Verify registry tests pass**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_project_registry.py -q
```

Expected: registry tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add loom/projects.py tests/test_project_registry.py
git commit -m "feat: add project registry storage"
```

---

### Task 2: Server API and Auto-Registration

**Files:**
- Modify: `loom/server.py`
- Test: `tests/test_project_registry.py`

- [ ] **Step 1: Add failing server tests**

Append tests:

```python
from fastapi.testclient import TestClient

from loom.server import app


class ProjectRegistryServerTests(ProjectRegistryTests):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)

    def test_project_open_registers_project(self):
        root = self.make_project("OpenMe")
        response = self.client.post("/api/project/open", json={"root": str(root)})
        self.assertEqual(response.status_code, 200)
        data = self.client.get("/api/projects").json()
        self.assertIn("OpenMe", data["projects"])

    def test_register_endpoint_rejects_non_project(self):
        folder = Path(self.tmp.name) / "not-project"
        folder.mkdir()
        response = self.client.post("/api/projects/register", json={"root": str(folder)})
        self.assertEqual(response.status_code, 400)

    def test_delete_project_endpoint_is_idempotent(self):
        root = self.make_project("DeleteMe")
        projects.register(root)
        response = self.client.delete("/api/projects/DeleteMe")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("DeleteMe", response.json()["projects"])
        response = self.client.delete("/api/projects/DeleteMe")
        self.assertEqual(response.status_code, 200)

    def test_default_dir_endpoint_updates_registry(self):
        folder = Path(self.tmp.name) / "books"
        response = self.client.put("/api/projects/default-dir", json={"path": str(folder)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Path(response.json()["default_dir"]), folder.resolve())
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_project_registry.py -q
```

Expected: FAIL because endpoints are missing and `/api/project/open` does not register.

- [ ] **Step 3: Implement server endpoints**

In `loom/server.py`, import registry module:

```python
from . import projects as project_registry
```

Add Pydantic model:

```python
class DefaultDirBody(BaseModel):
    path: str
```

Add endpoints near existing project endpoints:

```python
@app.get("/api/projects")
def projects_list():
    return project_registry.list_all()


@app.post("/api/projects/register")
def projects_register(b: RootBody):
    root = Path(b.root).expanduser()
    if not _is_project(root):
        return JSONResponse({"error": f"{root} 不是 loom 项目(没有 loom.toml)。"}, status_code=400)
    return project_registry.register(root)


@app.delete("/api/projects/{name}")
def projects_remove(name: str):
    project_registry.remove(name)
    return project_registry.list_all()


@app.put("/api/projects/default-dir")
def projects_default_dir(b: DefaultDirBody):
    return project_registry.set_default_dir(Path(b.path))
```

Update successful project flows:

```python
root = scaffold_init(...)
project_registry.register(root, default_dir=Path(b.parent).expanduser())
return _state(root)
```

```python
root = open_sample(Path(b.parent).expanduser())
project_registry.register(root, default_dir=Path(b.parent).expanduser())
return _state(root)
```

```python
state = _state(root)
project_registry.register(root)
return state
```

- [ ] **Step 4: Verify server tests pass**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests/test_project_registry.py -q
```

Expected: all project registry tests PASS.

- [ ] **Step 5: Run broader tests**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add loom/server.py tests/test_project_registry.py
git commit -m "feat: expose project registry api"
```

---

### Task 3: Welcome Screen Project List

**Files:**
- Modify: `loom/webui/index.html`
- Modify: `loom/webui/app.js`
- Modify: `loom/webui/style.css`

- [ ] **Step 1: Add welcome markup**

In `loom/webui/index.html`, inside the welcome panel before the new project controls, add:

```html
      <section id="project-library" class="project-library hidden">
        <div class="welcome-row">
          <h2>项目库</h2>
          <button id="btn-refresh-projects" class="ghost" title="刷新项目列表"><span class="ico" data-ico="redo"></span> 刷新</button>
        </div>
        <div id="project-list" class="project-list"></div>
      </section>
```

- [ ] **Step 2: Add frontend logic**

In `loom/webui/app.js`, add `let PROJECTS = null;` near `DATA`.

Bind controls:

```javascript
$("btn-refresh-projects").onclick = loadProjects;
```

Load projects on startup before saved project restore:

```javascript
loadProjects();
const saved = localStorage.getItem("loom_root");
if (saved) openProject(saved, true);
```

Add functions:

```javascript
async function loadProjects() {
  try {
    PROJECTS = await jreq("GET", "/api/projects");
    renderProjects();
    if (PROJECTS.default_dir && !$("new-parent").value.trim()) $("new-parent").value = PROJECTS.default_dir;
  } catch (e) {
    PROJECTS = null;
  }
}

function renderProjects() {
  const wrap = $("project-library");
  const list = $("project-list");
  if (!wrap || !list) return;
  const items = PROJECTS && PROJECTS.projects ? Object.entries(PROJECTS.projects) : [];
  wrap.classList.toggle("hidden", items.length === 0);
  list.innerHTML = "";
  items.sort((a, b) => String(b[1].last_open || "").localeCompare(String(a[1].last_open || "")));
  for (const [name, p] of items) {
    const row = document.createElement("div");
    row.className = "project-item" + (p.exists ? "" : " missing");
    const main = document.createElement("button");
    main.className = "project-open";
    main.disabled = !p.exists;
    main.title = p.path;
    main.innerHTML = `<span class="project-name">${escHtml(name)}</span><span class="project-path">${escHtml(p.path)}</span>`;
    main.onclick = () => openProject(p.path, false);
    const remove = document.createElement("button");
    remove.className = "project-remove";
    remove.title = "从项目库移除";
    remove.innerHTML = icon("trash");
    remove.onclick = () => removeProject(name);
    row.appendChild(main);
    row.appendChild(remove);
    list.appendChild(row);
  }
}

async function removeProject(name) {
  try {
    PROJECTS = await jreq("DELETE", `/api/projects/${encodeURIComponent(name)}`);
    renderProjects();
  } catch (e) {
    toast(e.message, true);
  }
}
```

After `enterProject(d)`, call `loadProjects();` so create/open/sample refresh the list.

- [ ] **Step 3: Add styling**

In `loom/webui/style.css`, add compact welcome styles:

```css
.project-library {
  width: min(720px, 100%);
  margin: 0 auto var(--space-4);
}
.welcome-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.project-list {
  display: grid;
  gap: var(--space-2);
}
.project-item {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: stretch;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  overflow: hidden;
}
.project-open {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.project-open:hover:not(:disabled) {
  background: var(--line-soft);
}
.project-open:disabled {
  cursor: default;
  color: var(--text-soft);
}
.project-name,
.project-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-name {
  font-weight: 650;
}
.project-path {
  color: var(--text-soft);
  font-size: var(--fs-xs);
}
.project-remove {
  width: 40px;
  border: 0;
  border-left: 1px solid var(--line);
  background: transparent;
  color: var(--text-soft);
  cursor: pointer;
}
.project-remove:hover {
  color: var(--danger);
  background: var(--line-soft);
}
.project-item.missing .project-name::after {
  content: " · 路径不存在";
  color: var(--danger);
  font-weight: 400;
}
```

- [ ] **Step 4: Verify frontend syntax**

Run:

```powershell
node --check loom/webui/app.js
```

Expected: exit 0.

- [ ] **Step 5: Verify full suite**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q
python -m compileall loom tests
node --check loom/webui/app.js
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add loom/webui/index.html loom/webui/app.js loom/webui/style.css
git commit -m "feat: show registered projects on welcome screen"
```

---

## Self-Review

- Spec coverage: registry file, backend endpoints, auto-registration, welcome list, missing-path handling, and default directory are covered.
- Placeholder scan: no TBD/TODO/fill-later steps.
- Type consistency: API names and payload fields are consistent across tasks.
