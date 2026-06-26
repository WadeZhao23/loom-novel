# Global DeepSeek Key Design

## Goal

Add a global DeepSeek API Key configuration layer so Loom can share one default key across projects, while still allowing a project-local `.env` to override it.

This is the first sub-project from `docs/features/新增功能方案.md`. It intentionally covers only the API Key configuration foundation. Project registry, batch planning, and reverse parsing will be handled as later sub-projects after this layer is stable.

## Current Context

- `loom/config.py` currently loads only `<project>/.env` and `loom.toml`.
- `loom/config.py::set_env_key()` writes `DEEPSEEK_API_KEY` into the project `.env`.
- `loom/config.py::key_is_set()` checks only the project `.env`.
- `loom/server.py::_state()` exposes `key_set` to the WebUI but does not expose the raw key.
- `loom/webui/app.js` already has a settings dialog that saves a key through the existing project-scoped API.

## Scope

Included:

- Create and use a global config directory at `%USERPROFILE%\\.loom`.
- Read global key from `%USERPROFILE%\\.loom\\.env`.
- Keep `<project>/.env` as the higher-priority override.
- Update the server state so the UI can tell whether the active key comes from global config or project override.
- Update the settings UI copy and behavior so users understand the effective source.
- Do not return or display the raw API Key in GET/state responses.

Excluded:

- Managing Claude/Codex credentials. Those remain handled by local client login or existing environment behavior.
- Managing multiple provider keys in the UI.
- Project registry or project selector work.
- Migrating an existing project `.env` key into global config automatically.

## Configuration Model

The effective DeepSeek key is resolved in this priority order:

1. Process environment variable `DEEPSEEK_API_KEY`.
2. Project-local `<project>/.env`.
3. Global `%USERPROFILE%\\.loom\\.env`.

The project-local `.env` remains the intentional override because a specific novel project may need to use a different key. The global `.env` is the default for ordinary projects.

`load_config(project_root)` should not rely on `load_dotenv(..., override=True)` ordering for `DEEPSEEK_API_KEY`, because that makes project switching and process-environment priority ambiguous. Instead, `loom/config.py` should parse project and global dotenv values with `dotenv_values()`, resolve the DeepSeek key explicitly, then update `os.environ["DEEPSEEK_API_KEY"]` to the resolved value for backend compatibility. If no key is resolved and there was no original process value, it should remove a stale `DEEPSEEK_API_KEY` left by a previous project load.

The original process value should be captured before project dotenv loading changes it. If that original value is non-empty, it always remains the effective value.

## Backend Design

Add focused helpers in `loom/config.py`:

- `global_config_dir() -> Path`: returns `%USERPROFILE%\\.loom` and creates no files.
- `global_env_path() -> Path`: returns `%USERPROFILE%\\.loom\\.env`.
- `resolve_deepseek_key(project_root: Path) -> tuple[str | None, str]`: returns the effective key and source name `process`, `project`, `global`, or `none`.
- `apply_deepseek_key(project_root: Path) -> str`: writes the resolved key into `os.environ` for existing backend code and returns the source name.
- `set_global_env_key(key: str) -> None`: creates the directory if needed and writes `DEEPSEEK_API_KEY`.
- `set_project_env_key(project_root: Path, key: str) -> None`: preserves the existing project write behavior under a clearer name.
- `key_status(project_root: Path) -> dict`: returns booleans and the effective source, without the raw key.

Keep `set_env_key()` as a compatibility wrapper for project-local writes unless all callers are updated in the same change.

Update `loom/server.py`:

- `_state()` includes a `backend.key_status` object.
- Existing `backend.key_set` remains for UI compatibility and is derived from the effective key.
- The current key save endpoint continues to support project-local writes for existing UI behavior.
- Add a small global-key save endpoint, for example `POST /api/settings/global-key`, accepting `{ "api_key": "..." }`.

Server responses must never include the actual key.

## Frontend Design

Update the existing settings dialog in `loom/webui/app.js` rather than building a separate settings surface.

The settings area should show:

- Whether an effective DeepSeek key exists.
- Whether the effective key source is process environment, project `.env`, global `.env`, or none.
- A control to save the key globally.
- A separate control to save a project override, preserving current behavior.

The UI should avoid printing secrets after save. After a successful save, it should refresh state and show a short status message.

## Error Handling

- Empty key submission is rejected with HTTP 400.
- If `%USERPROFILE%` is unavailable, fall back to `Path.home()` via Python's standard behavior.
- If writing `%USERPROFILE%\\.loom\\.env` fails, return HTTP 500 with a concise error message.
- Malformed or missing `.env` files are treated as absent values.

## Testing

Add Python tests for `loom/config.py` behavior:

- Global key is detected when no project key exists.
- Project key overrides global key.
- Process environment key overrides both dotenv files.
- `set_global_env_key()` creates the global directory and writes the expected variable.
- `key_status()` never returns a raw key and reports the correct source.

Add server-level tests only if the existing project test setup supports FastAPI tests without excessive scaffolding. If no test harness exists, cover the core behavior in config tests and manually verify the API with the local app.

## Compatibility

Existing projects continue to work:

- A project `.env` key still works.
- Existing UI paths that check only `backend.key_set` continue to function.
- Existing code that calls `set_env_key(project_root, key)` still writes to the project `.env`.

## Open Decisions Resolved

- Global UI manages DeepSeek only.
- Claude and Codex credentials are not added to this config surface.
- Project `.env` intentionally overrides global `.env`.
- The first implementation should not attempt automatic migration from project key to global key.
