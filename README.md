# WWM Translator

Standalone desktop translator for **Where Winds Meet** locale containers.

This repository contains translator tooling only. Translation text is loaded from game files and TSV
overlays, then stored in local project data.

Part of the locale parsing logic is based on the original community project:
[DOG729/wwm_russian](https://github.com/DOG729/wwm_russian).

## Core capabilities

- Open a game folder and choose one target language per project.
- Extract `CN + EN + official target` into `project.db`.
- Work with layered translation data:
  - `Official target` (from game files)
  - `Master translation` (external TSV overlay)
  - `My translation` (personal TSV overlay, editable)
- Review with per-row `Approve/Reject`, batch review, and `Needs Context`.
- Use side panels: `TM`, `Glossary`, `QA`, `Same Source`, `Rendered Preview`, `Notes`.
- Save `My translation` and merge approved rows into `Master`.
- Export final containers from `Official + saved Master overrides`.

## Data layout

When launched as `.exe`, app data is stored next to the executable:

`WWMTranslator/data/projects/<game_slug>_<lang>/`

Project files:

- `project.db`
- `my_translation.tsv`
- `project.json`

Startup behavior:

- app does not rebuild DB on every launch;
- existing project cache is reused;
- extraction runs only when needed during project open.

## GUI flow (current)

1. Launch `WWMTranslator.exe`.
2. Open `Project -> Create DB`, choose game root and target language.
3. Wait for extraction (first run).
4. Optionally load:
   - `Project -> Load master translation`
   - `Project -> Load glossary`
5. Translate in table/editor, use `Approve/Reject`, `Needs Context`, and `Notes`.
6. Save personal layer via `Translation -> Save translation`.
7. Apply approved rows to master via `Translation -> Save master translation`.
8. Run `Tools -> Run QA` (background worker).
9. Export via `Export -> Export translation`.

## QA and export behavior

- `Run QA` validates placeholders, link tags, glossary strict terms, and render tag consistency.
- QA panel supports row-level errors and project-wide error overview with navigation to row.
- Before export, app runs QA on final assembled output (`Official + Master`).
- Critical export QA dialog includes issue source split (`MASTER` / `OFFICIAL` / `EMPTY`).
- Export can continue with explicit `Export anyway`.

## CLI quick reference

Install:

```bash
python -m pip install -e .
```

Commands:

```bash
python -m wwm.cli project --game-root "D:/WhereWindsMeet" --lang ru
python -m wwm.cli extract --game-root "D:/WhereWindsMeet" --lang ru
python -m wwm.cli qa --game-root "D:/WhereWindsMeet" --lang ru --master "D:/translations/master_ru.tsv"
python -m wwm.cli export --game-root "D:/WhereWindsMeet" --lang ru --output "D:/out" --master "D:/translations/master_ru.tsv"
python -m wwm.cli gui
```

## Build executable

```bash
powershell -ExecutionPolicy Bypass -File packaging/build_exe.ps1
```

Output directory:

`dist/WWMTranslator/`

## CI/Release

- PR/push: lint + tests (`.github/workflows/ci.yml`)
- Tag `v*`: Windows build with PyInstaller + zipped release asset upload

## Documentation

- `docs/architecture.md`
- `docs/workflow.md`
- `docs/format_translation_tsv.md`
- `docs/localization.md`
- `docs/tags.md`
- `docs/nexus_description.md`
