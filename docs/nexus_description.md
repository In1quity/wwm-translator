# WWM Translator

Standalone translator utility for Where Winds Meet localization containers.

## Features

- Open game root folder and choose target language
- Extract CN + EN + target language into searchable project DB
- Load external master translation TSV
- Load external glossary TSV
- Translate in GUI with tags/placeholders checks
- Export updated locale containers and zip package
- Keep project data locally in `data/` near executable

## How to use

1. Download and unpack `WWMTranslator-<version>-win64.zip`.
2. Run `WWMTranslator.exe`.
3. Click **Open project**, select game root folder and target language.
4. Wait for initial extraction progress (first open only).
5. Optionally load master translation and glossary.
6. Translate and click **Save translation**.
7. Click **Export files** for final game containers.

## Safety

- Tool does not modify repository files.
- Translation data is stored in local project folders near exe:
  - `data/projects/<game>_<lang>/project.db`
  - `data/projects/<game>_<lang>/my_translation.tsv`
- Exported files are written only to selected output directory.
