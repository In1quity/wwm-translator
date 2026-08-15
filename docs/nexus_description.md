# WWM Translator

WWM Translator is a standalone desktop utility for editing **Where Winds Meet** localization data
with fast QA and layered translation workflow.

## Key features

- Open game root and create a language-specific project cache.
- Parse and index `CN`, `EN`, and official target text into SQLite.
- Work with three translation layers:
  - official target (reference)
  - master translation TSV (trusted overrides)
  - personal translation TSV (editable draft)
- Review rows with `Approve/Reject`, bulk review, and state filters.
- Use productivity panels:
  - TM (trusted/reference/draft split)
  - Glossary mismatch hints
  - QA issue navigation
  - Same Source list with one-click apply
  - Rendered Preview for game tags
  - Notes and Needs Context flags
- Run QA before export and review critical issues by source.
- Export updated locale containers and release zip.

## Typical usage

1. Launch `WWMTranslator.exe`.
2. `Project -> Create DB`, choose game root and language.
3. Optionally load master translation and glossary TSV files.
4. Translate and review in the table/editor.
5. Save personal progress (`Save translation`).
6. Push approved rows into master (`Save master translation`).
7. Run QA and export final translation.

## Data safety

- Tool works on local project files and export output only.
- It does not require online services.
- Project data is kept near executable:
  - `data/projects/<game>_<lang>/project.db`
  - `data/projects/<game>_<lang>/my_translation.tsv`
- Export writes only to selected output directory.
