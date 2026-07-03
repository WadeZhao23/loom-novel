# Chapter Planning Design

## Goal

Add batch chapter planning so an author can enter a target chapter count, generate per-chapter scene outlines in sequence, see progress as each chapter completes, and edit the generated outlines before writing prose.

## Requirements

- Add a backend module `loom/chapter_plan.py` with `plan_chapters(root, total, backend, start_from=1, force=False, progress=None)`.
- Generate one chapter outline at a time through the configured AI backend.
- Stream progress events while generating.
- Persist each completed chapter immediately.
- Support partial planning by `start_from`.
- Do not overwrite existing per-chapter outlines unless `force=True`.
- Add `POST /api/plan/generate` with body `{ root, total_chapters, start_from?, force? }`.
- Add a web UI chapter planning panel with total/start/overwrite controls, a progress indicator, and quick editing access for generated outlines.

## Recommended Approach

Use the current chapter-writing architecture as the integration point. The project already treats `正文/.细纲/第N章.md` as the editable outline that the writing pipeline consumes, so batch planning should write each generated outline there. This makes the new feature immediately useful: after planning chapters 1-20, the existing “write chapter” flow reads the planned outline for each chapter.

Keep a lightweight whole-book view in `外置大脑/卡章纲.md` by appending or replacing generated chapter summary blocks. This gives the author a single editable planning document without making it the only source of truth for per-chapter writing.

## Alternatives Considered

1. **Only update `外置大脑/卡章纲.md`.** This is simple, but the existing writing pipeline reads per-chapter outlines from `正文/.细纲/第N章.md`, so generated planning would not directly drive chapter drafting.
2. **Add a separate planning database.** This gives stronger metadata, but it is unnecessary for a local Markdown project and would add migration risk.
3. **Recommended: write per-chapter outline files and sync the card-outline document.** This matches current Loom behavior, keeps files human-editable, and gives the UI a simple editing path.

## Backend Design

`loom/chapter_plan.py` will own planning-specific behavior:

- `outline_path(root, chapter)` returns `正文/.细纲/第N章.md`.
- `load_existing_plan(root)` reads the current card-outline file if present.
- `build_prompt(root, chapter, total, card_outline, previous_outline)` creates a planning prompt using title, worldbuilding, character card, existing card outline, selected genre files, and the previous generated outline.
- `plan_chapters(...)` validates inputs, loops over the requested chapter range, emits events, calls `backend.complete(...)`, writes each chapter outline atomically, and returns a summary.

Events will be plain dictionaries, matching the existing `/api/write` NDJSON style:

- `{ "type": "progress", "chapter": N, "total": M }`
- `{ "type": "skip", "chapter": N, "path": "..." }`
- `{ "type": "done", "chapter": N, "outline": "...", "path": "..." }`
- `{ "type": "complete", "planned": X, "skipped": Y }`
- `{ "type": "error", "message": "..." }`

The backend will reject invalid totals, invalid starts, non-Loom roots, and invalid empty model output. Existing outline files are preserved unless `force=True`.

## API Design

`POST /api/plan/generate` returns `StreamingResponse` with `application/x-ndjson`, consistent with `/api/write`.

Request body:

```json
{
  "root": "E:/小说/某本书",
  "total_chapters": 20,
  "start_from": 1,
  "force": false
}
```

The endpoint will load the current project config, construct the backend with `get_backend(load_config(root))`, pass events through a worker queue, and stream one JSON object per line. Error handling follows `/api/write`: expected backend/config/file errors become stream error events instead of hanging the response.

## Frontend Design

The main app gets a compact “章节规划” section in the sidebar near the chapter list. It will include:

- total chapter count input, defaulting to at least the current next chapter;
- start-from input, defaulting to `DATA.next_chapter`;
- overwrite toggle;
- generate button;
- status/progress text;
- a small generated-outline list where each item opens the relevant `正文/.细纲/第N章.md` file for editing.

The UI will reuse the current fetch streaming pattern from `writeChapter()`: read `response.body`, split newline-delimited JSON events, update progress, and show done/skip/error messages. It will call `refresh()` after completion so the rest of project state stays current.

## Testing

Add focused backend tests before implementation:

- generating chapters 1..3 writes three outline files and emits progress/done/complete events;
- `start_from=3,total=5` only writes chapters 3..5;
- existing outline is skipped when `force=False`;
- existing outline is overwritten when `force=True`;
- invalid ranges raise `ValueError`;
- server endpoint streams NDJSON events and uses the configured backend path with a patched fake backend.

Add lightweight frontend syntax verification through `node --check loom/webui/app.js`. Full browser automation is optional because this is an incremental static UI change and current project tests do not include browser infrastructure.

## Compatibility

- Existing chapter writing behavior remains unchanged.
- Existing file editing endpoints remain unchanged.
- Existing projects without `正文/.细纲` will have the directory created lazily.
- The API uses NDJSON rather than browser-native SSE because the current Loom streaming endpoint already uses NDJSON; the feature requirement’s “SSE” event shapes are preserved as JSON events.
