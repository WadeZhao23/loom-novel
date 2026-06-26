# Global DeepSeek Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement global DeepSeek API Key support through `%USERPROFILE%\.loom\.env`, with project `.env` override and no raw key exposure in state/API responses.

**Architecture:** Keep provider/model/chapter settings project-local in `loom.toml`, but resolve `DEEPSEEK_API_KEY` through a focused config layer in `loom/config.py`. Server state exposes only key presence/source metadata, and the existing WebUI top bar gains separate global-key and project-override save controls.

**Tech Stack:** Python 3.11, stdlib `unittest`, `python-dotenv`, FastAPI, plain JavaScript WebUI.

---

## File Structure

- Create: `E:/小说/xiaoshuozengjiagongneng/tests/test_global_deepseek_key.py`
  - Standard-library tests for key resolution, global key writing, stale environment cleanup, and status privacy.
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/config.py`
  - Add global `.loom/.env` helpers, explicit key resolution, project/global write helpers, and compatibility wrappers.
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/server.py`
  - Expose key status in `_state()`, add global key save endpoint, preserve project key save behavior.
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/doctor.py`
  - Update DeepSeek credential check and fix message to reflect global or project key.
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/webui/index.html`
  - Add a status span and a global-key save button beside the existing API Key input.
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/webui/app.js`
  - Render key source, save global key separately, keep current project override behavior.
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/webui/style.css`
  - Add compact styling for the key source badge.

## Task 1: Config Tests

**Files:**
- Create: `E:/小说/xiaoshuozengjiagongneng/tests/test_global_deepseek_key.py`
- Read: `E:/小说/xiaoshuozengjiagongneng/docs/superpowers/specs/2026-06-26-global-deepseek-key-design.md`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_global_deepseek_key.py`:

```python
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loom import config


def write_project(root: Path, env_text: str = "") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "loom.toml").write_text(
        "\n".join(
            [
                "[backend]",
                'provider = "deepseek"',
                'model = "deepseek-chat"',
                "",
                "[novel]",
                'title = "测试书"',
                '"章节字数" = 800',
                "",
                "[gate]",
                '"轮数" = 1',
                "",
            ]
        ),
        encoding="utf-8",
    )
    if env_text:
        (root / ".env").write_text(env_text, encoding="utf-8")


class GlobalDeepSeekKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_env = os.environ.get("DEEPSEEK_API_KEY")
        os.environ.pop("DEEPSEEK_API_KEY", None)
        if hasattr(config, "_APPLIED_DEEPSEEK_KEY"):
            config._APPLIED_DEEPSEEK_KEY = None

    def tearDown(self) -> None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        if self.old_env is not None:
            os.environ["DEEPSEEK_API_KEY"] = self.old_env
        if hasattr(config, "_APPLIED_DEEPSEEK_KEY"):
            config._APPLIED_DEEPSEEK_KEY = None

    def test_global_key_is_used_when_project_has_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project)
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")

                key, source = config.resolve_deepseek_key(project)

            self.assertEqual(key, "sk-global")
            self.assertEqual(source, "global")

    def test_project_key_overrides_global_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")

                key, source = config.resolve_deepseek_key(project)

            self.assertEqual(key, "sk-project")
            self.assertEqual(source, "project")

    def test_process_key_overrides_project_and_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            os.environ["DEEPSEEK_API_KEY"] = "sk-process"
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")

                key, source = config.resolve_deepseek_key(project)

            self.assertEqual(key, "sk-process")
            self.assertEqual(source, "process")

    def test_load_config_replaces_loom_applied_key_when_switching_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            first = base / "first"
            second = base / "second"
            write_project(first, "DEEPSEEK_API_KEY=sk-first\n")
            write_project(second, "DEEPSEEK_API_KEY=sk-second\n")
            with mock.patch.object(config.Path, "home", return_value=home):
                config.load_config(first)
                self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-first")

                config.load_config(second)

            self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-second")

    def test_load_config_removes_stale_loom_applied_key_when_next_project_has_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            first = base / "first"
            second = base / "second"
            write_project(first, "DEEPSEEK_API_KEY=sk-first\n")
            write_project(second)
            with mock.patch.object(config.Path, "home", return_value=home):
                config.load_config(first)
                self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-first")

                config.load_config(second)

            self.assertIsNone(os.environ.get("DEEPSEEK_API_KEY"))

    def test_set_global_env_key_creates_global_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")
                env_path = home / ".loom" / ".env"

            self.assertEqual(env_path.read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-global\n")

    def test_key_status_does_not_return_raw_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")

            status = config.key_status(project)

            self.assertEqual(status["source"], "project")
            self.assertTrue(status["effective"])
            self.assertTrue(status["project"])
            self.assertFalse(status["global"])
            self.assertNotIn("key", status)
            self.assertNotIn("api_key", status)
            self.assertNotIn("sk-project", repr(status))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_global_deepseek_key -v
```

Expected: FAIL or ERROR because `loom.config` does not yet define `set_global_env_key`, `resolve_deepseek_key`, and `key_status` still only checks the project `.env`.

- [ ] **Step 3: Commit the failing tests**

```powershell
git add tests/test_global_deepseek_key.py
git commit -m "test: define global deepseek key behavior"
```

## Task 2: Config Implementation

**Files:**
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/config.py`
- Test: `E:/小说/xiaoshuozengjiagongneng/tests/test_global_deepseek_key.py`

- [ ] **Step 1: Update imports and module state**

In `loom/config.py`, replace:

```python
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
```

with:

```python
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
```

Then add after imports:

```python
_APPLIED_DEEPSEEK_KEY: str | None = None
```

- [ ] **Step 2: Add dotenv helpers**

Add these functions after `find_project_root()`:

```python
def global_config_dir() -> Path:
    """Return the per-user Loom config directory."""
    return Path.home() / ".loom"


def global_env_path() -> Path:
    """Return the per-user Loom dotenv path."""
    return global_config_dir() / ".env"


def _read_env_key(path: Path) -> str | None:
    if not path.exists():
        return None
    value = dotenv_values(path).get("DEEPSEEK_API_KEY")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _replace_env_key(path: Path, key: str) -> None:
    lines: list[str] = []
    if path.exists():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("DEEPSEEK_API_KEY")
        ]
    lines.append(f"DEEPSEEK_API_KEY={key}")
    atomic_write_text(path, "\n".join(lines) + "\n")
```

- [ ] **Step 3: Add explicit DeepSeek key resolution**

Add these functions after `_replace_env_key()`:

```python
def resolve_deepseek_key(project_root: Path) -> tuple[str | None, str]:
    """Resolve the effective DeepSeek key without exposing it in API state."""
    process_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if process_key and process_key != _APPLIED_DEEPSEEK_KEY:
        return process_key, "process"

    project_key = _read_env_key(project_root / ".env")
    if project_key:
        return project_key, "project"

    global_key = _read_env_key(global_env_path())
    if global_key:
        return global_key, "global"

    return None, "none"


def apply_deepseek_key(project_root: Path) -> str:
    """Apply the resolved DeepSeek key to os.environ for existing backends."""
    global _APPLIED_DEEPSEEK_KEY
    key, source = resolve_deepseek_key(project_root)
    if key:
        os.environ["DEEPSEEK_API_KEY"] = key
        _APPLIED_DEEPSEEK_KEY = key if source != "process" else None
    else:
        if _APPLIED_DEEPSEEK_KEY is not None and os.environ.get("DEEPSEEK_API_KEY") == _APPLIED_DEEPSEEK_KEY:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        _APPLIED_DEEPSEEK_KEY = None
    return source
```

- [ ] **Step 4: Call `apply_deepseek_key()` from `load_config()`**

In `load_config(project_root)`, replace:

```python
    # .env 从项目根读(里面放 DEEPSEEK_API_KEY);override=True 保证切换项目时当前项目的 key 生效
    load_dotenv(project_root / ".env", override=True)
```

with:

```python
    # Resolve DeepSeek credentials explicitly so project switching cannot leave a stale key behind.
    apply_deepseek_key(project_root)
```

- [ ] **Step 5: Replace project/global key writers and status**

Replace the existing `set_env_key()` and `key_is_set()` functions with:

```python
def set_project_env_key(project_root: Path, key: str) -> None:
    """Write DEEPSEEK_API_KEY into the project .env file."""
    _replace_env_key(project_root / ".env", key)


def set_global_env_key(key: str) -> None:
    """Write DEEPSEEK_API_KEY into the per-user Loom .env file."""
    global_config_dir().mkdir(parents=True, exist_ok=True)
    _replace_env_key(global_env_path(), key)


def set_env_key(project_root: Path, key: str) -> None:
    """Compatibility wrapper: existing callers write a project override."""
    set_project_env_key(project_root, key)


def key_status(project_root: Path) -> dict:
    """Return key presence and effective source without returning the secret."""
    _, source = resolve_deepseek_key(project_root)
    return {
        "effective": source != "none",
        "source": source,
        "process": source == "process",
        "project": _read_env_key(project_root / ".env") is not None,
        "global": _read_env_key(global_env_path()) is not None,
    }


def key_is_set(project_root: Path) -> bool:
    return bool(key_status(project_root)["effective"])
```

- [ ] **Step 6: Run config tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_global_deepseek_key -v
```

Expected: PASS for all tests in `GlobalDeepSeekKeyTests`.

- [ ] **Step 7: Run compile check**

Run:

```powershell
python -m compileall loom tests
```

Expected: no syntax errors.

- [ ] **Step 8: Commit config implementation**

```powershell
git add loom/config.py tests/test_global_deepseek_key.py
git commit -m "feat: resolve deepseek key from global config"
```

## Task 3: Server State and Doctor

**Files:**
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/server.py`
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/doctor.py`
- Test: `E:/小说/xiaoshuozengjiagongneng/tests/test_global_deepseek_key.py`

- [ ] **Step 1: Add direct tests for server state privacy and global endpoint behavior**

Append these tests to `GlobalDeepSeekKeyTests` in `tests/test_global_deepseek_key.py`:

```python
    def test_server_state_includes_key_status_without_raw_key(self) -> None:
        from loom import server

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            (project / "正文").mkdir()

            state = server._state(project)

            self.assertTrue(state["backend"]["key_set"])
            self.assertEqual(state["backend"]["key_status"]["source"], "project")
            self.assertNotIn("sk-project", repr(state))

    def test_global_key_endpoint_saves_key_and_returns_state(self) -> None:
        from loom import server

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project)
            with mock.patch.object(config.Path, "home", return_value=home):
                body = server.GlobalKeyBody(root=str(project), api_key="sk-global")

                state = server.update_global_key(body)

            self.assertTrue((home / ".loom" / ".env").is_file())
            self.assertTrue(state["backend"]["key_set"])
            self.assertEqual(state["backend"]["key_status"]["source"], "global")
            self.assertNotIn("sk-global", repr(state))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_global_deepseek_key -v
```

Expected: FAIL or ERROR because `server._state()` does not expose `backend.key_status` and `server.GlobalKeyBody` / `server.update_global_key()` do not exist.

- [ ] **Step 3: Update server imports**

In `loom/server.py`, replace:

```python
from .config import Config, key_is_set, load_config, save_config, set_env_key
```

with:

```python
from .config import Config, key_is_set, key_status, load_config, save_config, set_env_key, set_global_env_key
```

- [ ] **Step 4: Expose key status in `_state()`**

In `loom/server.py::_state()`, replace the `backend` dict:

```python
        "backend": {"provider": cfg.provider, "model": cfg.model, "chapter_chars": cfg.chapter_chars,
                    "key_set": key_is_set(root)},
```

with:

```python
        "backend": {
            "provider": cfg.provider,
            "model": cfg.model,
            "chapter_chars": cfg.chapter_chars,
            "key_set": key_is_set(root),
            "key_status": key_status(root),
        },
```

- [ ] **Step 5: Add global key request body and endpoint**

In `loom/server.py`, after `ConfigBody`, add:

```python
class GlobalKeyBody(BaseModel):
    root: str
    api_key: str
```

After `update_config()`, add:

```python
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
```

- [ ] **Step 6: Update doctor DeepSeek check text**

In `loom/doctor.py`, replace the DeepSeek key check:

```python
        checks.append(_c("DEEPSEEK_API_KEY 已配", key_is_set(root),
                         ".env 里没读到 DEEPSEEK_API_KEY",
                         ".env 加一行 DEEPSEEK_API_KEY=sk-你的key(platform.deepseek.com 申请)"))
```

with:

```python
        checks.append(_c("DEEPSEEK_API_KEY 已配", key_is_set(root),
                         "全局 ~/.loom/.env 和项目 .env 都没读到 DEEPSEEK_API_KEY",
                         "在顶栏保存全局 DeepSeek Key,或在本项目 .env 加 DEEPSEEK_API_KEY=sk-你的key"))
```

- [ ] **Step 7: Run server/config tests**

Run:

```powershell
python -m unittest tests.test_global_deepseek_key -v
```

Expected: PASS for all tests in `GlobalDeepSeekKeyTests`.

- [ ] **Step 8: Run compile check**

Run:

```powershell
python -m compileall loom tests
```

Expected: no syntax errors.

- [ ] **Step 9: Commit server and doctor changes**

```powershell
git add loom/server.py loom/doctor.py tests/test_global_deepseek_key.py
git commit -m "feat: expose deepseek key status"
```

## Task 4: WebUI Key Source and Global Save

**Files:**
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/webui/index.html`
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/webui/app.js`
- Modify: `E:/小说/xiaoshuozengjiagongneng/loom/webui/style.css`

- [ ] **Step 1: Add UI elements in the backend toolbar**

In `loom/webui/index.html`, replace:

```html
        <input id="api-key" type="password" class="model" title="只对 DeepSeek 必填(写进项目 .env);Claude / Codex 复用各自客户端的登录,不用填 key" />
        <button id="btn-probe" class="ghost hidden" title="检测 Claude / Codex 客户端是否就绪"><span class="ico" data-ico="focus"></span> 检测连接</button>
        <span id="backend-status" class="backend-status"></span>
```

with:

```html
        <input id="api-key" type="password" class="model" title="只对 DeepSeek 必填;可保存为全局默认 key,也可随保存后端写进本项目 .env 作为覆盖" />
        <button id="btn-save-global-key" class="ghost" title="保存为所有项目共用的 DeepSeek Key"><span class="ico" data-ico="key"></span> 存全局 Key</button>
        <button id="btn-probe" class="ghost hidden" title="检测 Claude / Codex 客户端是否就绪"><span class="ico" data-ico="focus"></span> 检测连接</button>
        <span id="key-source" class="key-source"></span>
        <span id="backend-status" class="backend-status"></span>
```

- [ ] **Step 2: Bind the new button**

In `loom/webui/app.js::bind()`, after:

```javascript
  $("btn-save-backend").onclick = saveBackend;
```

add:

```javascript
  $("btn-save-global-key").onclick = saveGlobalKey;
```

- [ ] **Step 3: Render key source and placeholder**

Add this helper before `render()`:

```javascript
function keySourceLabel() {
  const st = DATA && DATA.backend && DATA.backend.key_status;
  if (!st || !st.effective) return "未配置 Key";
  const labels = {
    process: "系统环境 Key",
    project: "本项目 Key",
    global: "全局 Key",
    none: "未配置 Key",
  };
  return labels[st.source] || "已配置 Key";
}
```

In `render()`, replace:

```javascript
  $("api-key").placeholder = DATA.backend.key_set ? "API Key 已设置" : "填 DeepSeek API Key";
```

with:

```javascript
  $("api-key").placeholder = DATA.backend.key_set ? keySourceLabel() + " 已生效" : "填 DeepSeek API Key";
  $("key-source").textContent = DATA.backend.provider === "deepseek" ? keySourceLabel() : "";
```

- [ ] **Step 4: Add global save behavior**

After `async function saveBackend() { await persistBackend(false); }`, add:

```javascript
async function saveGlobalKey() {
  const key = $("api-key").value.trim();
  if (!key) {
    toast("先填 DeepSeek API Key", true);
    $("api-key").focus();
    return;
  }
  try {
    DATA = await jreq("POST", "/api/settings/global-key", { root: DATA.root, api_key: key });
    toast("全局 DeepSeek Key 已保存");
    render();
    if (CUR) updateWordCount();
  } catch (e) {
    toast(e.message, true);
  }
}
```

- [ ] **Step 5: Toggle global key controls with provider**

In `applyProviderUI(provider)`, replace:

```javascript
  $("api-key").classList.toggle("hidden", !isKey);
  $("btn-probe").classList.toggle("hidden", isKey);
```

with:

```javascript
  $("api-key").classList.toggle("hidden", !isKey);
  $("btn-save-global-key").classList.toggle("hidden", !isKey);
  $("key-source").classList.toggle("hidden", !isKey);
  $("btn-probe").classList.toggle("hidden", isKey);
```

- [ ] **Step 6: Keep project override behavior explicit**

In `persistBackend(silent)`, replace:

```javascript
  if (!silent) toast(key ? "后端 + API Key 已保存" : "后端已保存");
```

with:

```javascript
  if (!silent) toast(key ? "后端 + 本项目 Key 覆盖已保存" : "后端已保存");
```

- [ ] **Step 7: Add compact key source CSS**

In `loom/webui/style.css`, after the `.backend-status` block, add:

```css
.key-source {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--muted);
  font-size: var(--fs-xs);
  white-space: nowrap;
}
.key-source:empty { display: none; }
```

- [ ] **Step 8: Manually verify UI behavior**

Run the local server:

```powershell
python -c "from loom.desktop import serve; serve()"
```

Expected: server starts and prints a local URL, usually `http://127.0.0.1:8000`.

Open the URL and verify:

- With provider `DeepSeek`, the API Key field, `存全局 Key` button, and key source badge are visible.
- With provider `Claude Code` or `Codex CLI`, the API Key field, `存全局 Key` button, and key source badge are hidden, while `检测连接` is visible.
- Saving a global key updates the badge to `全局 Key` and does not show the raw key.
- Saving backend with a filled key updates the badge to `本项目 Key` and does not show the raw key.

- [ ] **Step 9: Run compile check**

Run:

```powershell
python -m compileall loom tests
```

Expected: no syntax errors.

- [ ] **Step 10: Commit WebUI changes**

```powershell
git add loom/webui/index.html loom/webui/app.js loom/webui/style.css
git commit -m "feat: add global deepseek key controls"
```

## Task 5: Final Verification

**Files:**
- Read: `E:/小说/xiaoshuozengjiagongneng/docs/superpowers/specs/2026-06-26-global-deepseek-key-design.md`
- Verify: all files changed in Tasks 1-4

- [ ] **Step 1: Run full automated verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall loom tests
```

Expected: all tests pass and compileall reports no syntax errors.

- [ ] **Step 2: Inspect state response for privacy**

Run a manual state request against a project with a configured key:

```powershell
@'
from pathlib import Path
from loom import server
root = Path.cwd()
state = server._state(root)
print(state["backend"])
print("contains_secret", "sk-" in repr(state))
'@ | python -
```

Expected: `backend.key_set` is `True` when a key exists, `backend.key_status.source` is one of `process`, `project`, `global`, or `none`, and `contains_secret False`.

- [ ] **Step 3: Check git diff**

Run:

```powershell
git diff --stat HEAD
git status --short
```

Expected: only intentional files are modified or untracked. `docs/features/` may remain untracked because it is the user's requirement folder and should not be staged unless requested.

- [ ] **Step 4: Summarize the result**

Report:

- Tests run and pass/fail status.
- Whether manual UI verification was completed.
- Effective key priority: process env > project `.env` > global `.loom/.env`.
- Any remaining untracked files, especially `docs/features/`.

## Self-Review

Spec coverage:

- Global `.loom/.env` support is covered by Task 2.
- Project override is covered by Task 2 tests and implementation.
- Process environment priority is covered by Task 1 tests and Task 2 implementation.
- No raw key exposure is covered by Task 1 and Task 3 tests.
- Server state and save endpoint are covered by Task 3.
- WebUI controls and status display are covered by Task 4.
- Doctor message compatibility is covered by Task 3.

Placeholder scan:

- No placeholder markers are present.
- Every task includes exact files, commands, and expected outcomes.

Type consistency:

- Python helpers use `global_config_dir`, `global_env_path`, `resolve_deepseek_key`, `apply_deepseek_key`, `set_global_env_key`, `set_project_env_key`, `set_env_key`, `key_status`, and `key_is_set` consistently.
- Server endpoint uses `GlobalKeyBody` and `update_global_key` consistently with the direct test.
- Frontend uses `btn-save-global-key`, `key-source`, `keySourceLabel`, and `saveGlobalKey` consistently with the HTML IDs.
