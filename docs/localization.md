# Localization rules

## Source priority

- Primary source is `CN`.
- `EN` is reference/help text.
- Final output is `target` language selected in project.

If `CN` and `EN` disagree semantically, prioritize `CN`.

## String states

- `official` — only official target text exists.
- `untranslated` — no official text and no user translation.
- `new` — user translation exists but master translation does not.
- `master` — user translation equals master translation.
- `changed` — user translation differs from master translation.
- `outdated` — `cn_hash` mismatch, source CN changed.

## Required invariants

Do not break:

- placeholders like `{0}`, `{month}`, `{total_day:d}`
- game link tags like `<...|...|...|...>`
- escaped sequences `\n`, `\r`, `\t`

## Glossary behavior

- Glossary is loaded from external TSV (`CN, EN, Target, Category, Strict`).
- UI panel shows matching entries for current row (`CN` contains term or `EN` contains term).
- QA reports `glossary_term_missing` when strict term is expected but missing in translation.
