# WWM Translator

Standalone desktop translator for **Where Winds Meet** locale containers.

This repository now contains only translator code. Translation content is loaded from external files
and stored in local project folders.

## Core behavior

- Opens a game folder and target language (`de/en/es/fr/ja/ko/pt_br/ru/th/vi/zh_tw`).
- Extracts `CN + EN + target` into a project database.
- Loads optional master translation and glossary from TSV.
- Saves your edits to `my_translation.tsv`.
- Exports translated containers and a release zip.

## Data location

When launched as `.exe`, the app always stores data next to the executable:

`WWMTranslator/data/projects/<game_slug>_<lang>/`

Project contents:

- `project.db`
- `my_translation.tsv`
- `project.json`

Important behavior:

- app startup does **not** rebuild DB automatically;
- opening existing project uses existing DB cache;
- DB rebuild/extract is triggered only when needed during `Open project`.

## GUI workflow

1. Launch `WWMTranslator.exe`.
2. Click **Open project** and choose game root + target language.
3. Wait for extraction/progress (first run only).
4. Optionally click **Load master translation** and **Load glossary**.
5. Translate rows and click **Save translation**.
6. Click **Export files** and choose output directory.

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

## CI/Release workflow

- PR/push: lint + tests (`.github/workflows/ci.yml`)
- tag `v*`: Windows build via PyInstaller + zipped release asset upload

## Documentation

- `docs/architecture.md`
- `docs/format_translation_tsv.md`
- `docs/localization.md`
- `docs/tags.md`
- `docs/nexus_description.md`
