# Chapter Planning Checkpoint

Date: 2026-06-28
Branch: `codex/chapter-planning`
Worktree: `E:\小说\xiaoshuozengjiagongneng\.worktrees\chapter-planning`
Latest saved commit: `b127e45 fix: avoid crossing malformed chapter markers`

## Current Status

- Feature 2, "章节规划（批量卡章纲）", is in progress.
- Design doc is committed: `2044c97 docs: design chapter planning`.
- Implementation plan is committed: `d7d0f54 docs: plan chapter planning`.
- Task 1, core `loom/chapter_plan.py` service, has been implemented and committed through `b127e45`.
- Worktree was clean before this checkpoint document was added.

## Verified

Command:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest tests\test_chapter_plan.py -q
```

Result:

```text
15 passed in 2.36s
```

## Task 1 Implemented Behavior

- `outline_path(project_root, chapter_n)` returns `正文/.细纲/第N章.md`.
- `card_outline_path(project_root)` returns `外置大脑/卡章纲.md`.
- `plan_chapters(...)` validates root and ranges.
- Generates chapters sequentially with backend calls.
- Emits `progress`, `skip`, `done`, and `complete` events.
- Skips existing non-empty outlines unless `force=True`.
- Writes generated outlines atomically with trailing newline.
- Syncs generated plans into a managed section of `外置大脑/卡章纲.md`.
- Preserves user content outside managed markers.
- Preserves malformed or unparseable managed fragments instead of dropping them.
- Includes title, genre files, card outline, worldbuilding, character card, and previous outline in prompt context.
- Supports `progress=None`.

## Review State

- Spec compliance for Task 1 was approved before the latest marker-parser hardening.
- Code quality review found several marker/data-preservation edge cases, all addressed with regression tests and commits.
- Final code quality re-review after `b127e45` did not complete because the workspace ran out of subagent credits.
- Before continuing to Task 2, re-run a final Task 1 review manually or with a subagent if credits are restored.

## Remaining Work

1. Task 2: Add `/api/plan/generate` streaming endpoint and endpoint tests.
2. Task 3: Add the web UI chapter planning panel and frontend streaming behavior.
3. Task 4: Run focused tests, full tests, compile checks, `node --check`, `git diff --check`, then final review.

## Notes

- Main repository is not merged with this branch yet.
- Original feature order remains 4 -> 3 -> 2 -> 1. Features 4 and 3 were already completed on local `main`.
- Local `main` was previously ahead 24 and behind 7 relative to `origin/main`; do not pull or push casually without deciding how to handle divergence.
