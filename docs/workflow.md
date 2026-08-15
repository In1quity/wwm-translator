# Workflow

## Translator workflow (GUI)

1. Start `WWMTranslator.exe`.
2. Open `Project -> Create DB`.
3. Select game root and target language.
4. Wait for extraction/caching (first run or missing cache).
5. Optionally load:
   - `Project -> Load master translation`
   - `Project -> Load my translation`
   - `Project -> Load glossary`
6. Work in the main table:
   - edit `Target ours`
   - review via `✓ / ×`
   - use filters/search/issues state
7. Use side tabs:
   - `TM`, `Glossary`, `QA`, `Same Source`, `Rendered Preview`, `Notes`
8. Save personal layer via `Translation -> Save translation`.
9. Merge approved rows into master via `Translation -> Save master translation`.
10. Run QA via `Tools -> Run QA` (background worker).
11. Export via `Export -> Export translation`.

## Review workflow details

- `Approve/Reject` can be applied to single row or selected visible rows.
- For bulk review, app confirms actionable row count before applying.
- Rows with empty `My` and empty `Master` are skipped for bulk review.
- Editing text after review resets personal review status as needed.
- `Needs Context` is per-row and independent from translation state.

## QA workflow details

- `Run QA` validates all rows and stores results in `qa_issues`.
- QA tab has two modes:
  - row-focused errors (when a row is selected)
  - project-wide overview (button or no selected row)
- Clicking an issue in QA overview navigates to the row for fix.

## Export workflow details

- Final output is built from:
  - official target text
  - plus saved master overrides
- Personal `my_translation` is not exported directly.
- Before export, QA runs against final assembled output.
- Critical issues dialog supports explicit `Export anyway`.
- Dialog shows issue source split:
  - `MASTER`
  - `OFFICIAL`
  - `EMPTY`

## File lifecycle

- Game source: selected folder (`Package/...`, `LocalData/...`).
- Working DB: `data/projects/<slug>_<lang>/project.db`.
- Personal layer: `data/projects/<slug>_<lang>/my_translation.tsv`.
- Master layer: loaded/saved TSV path (`master_translation.tsv` by default in project dir).
- Export output: chosen output directory plus zip package.

## CI workflow

Defined in `.github/workflows/ci.yml`.

- On push/pull_request:
  - install dependencies
  - run `ruff`
  - run `pytest`
- On tag `v*`:
  - run Windows build (`packaging/build_exe.ps1`)
  - create `WWMTranslator-v<tag>-win64.zip`
  - upload release asset
