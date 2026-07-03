# Project Registry Design

## Goal

Add centralized project management so Loom can remember created/opened projects in a per-user registry and show them on startup, while preserving the current create/open/sample flows.

## Scope

This implements feature 3 from `docs/features/新增功能方案.md`: project registry and project picker. It does not implement chapter planning or reverse parsing.

## Registry

Loom stores project metadata in `~/.loom/projects.json`, next to the global API key file introduced by feature 4.

Format:

```json
{
  "default_dir": "E:/小说",
  "projects": {
    "修仙之重生记忆": {
      "path": "E:/小说/修仙之重生记忆",
      "created": "2026-06-01T12:00:00",
      "last_open": "2026-06-24T09:30:00"
    }
  }
}
```

The key under `projects` is a stable display name derived from the folder name. If two projects share the same folder name, the existing entry with the same resolved path is updated; a different path gets a suffix such as `名称 (2)`.

Broken or missing registry files should not block startup. Invalid JSON falls back to an empty registry and the next successful write replaces it with valid JSON.

## Backend API

`loom/projects.py` owns all registry I/O.

Functions:

- `registry_path() -> Path`
- `load_registry() -> dict`
- `save_registry(data: dict) -> None`
- `register(path: Path, *, default_dir: Path | None = None) -> dict`
- `list_all() -> dict`
- `remove(name: str) -> bool`
- `set_default_dir(path: Path) -> dict`
- `get_default_dir() -> str`

Server endpoints:

- `GET /api/projects` returns the registry plus `exists` for each project.
- `POST /api/projects/register` with `{ root }` validates that `root` is a Loom project, registers it, and returns the updated project list.
- `DELETE /api/projects/{name}` removes a registry entry and returns the updated project list.
- `PUT /api/projects/default-dir` with `{ path }` stores the preferred parent directory and returns the updated project list.

Existing endpoints also register projects after success:

- `POST /api/project/create`
- `POST /api/sample/open`
- `POST /api/project/open`

## Frontend

The welcome screen keeps the current new/open/sample controls. Above them, Loom adds a compact project list when the registry has entries.

Behavior:

- On startup, call `GET /api/projects`.
- If `localStorage.loom_root` opens successfully, enter it as today and refresh the registry in the background.
- If no saved project opens, show the welcome screen with the project list.
- Clicking an existing project calls `openProject(path, false)`.
- A missing project is shown disabled with a remove button.
- Manual open and create flows keep working exactly as before, then update the project list.
- The default parent field uses `registry.default_dir` when present.

## Error Handling

- Registry writes use atomic writes.
- Missing project paths do not crash the UI.
- Removing an unknown project is idempotent.
- Registering a non-Loom folder returns HTTP 400.

## Testing

Unit tests cover registry CRUD, duplicate handling, invalid JSON fallback, existence flags, default directory storage, and server auto-registration from create/open/sample flows.

Frontend verification covers syntax and basic DOM integration through existing `node --check` plus manual state-shape checks in tests where practical.
