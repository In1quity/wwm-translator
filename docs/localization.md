# Localization rules

## Source priority

- Primary semantic source is `CN`.
- `EN` is reference-only context.
- Official target is baseline reference for the selected language.

If `CN` and `EN` conflict, follow `CN`.

## Translation layers

- `Official target`  
  In-game translation currently shipped by the game.
- `Master translation`  
  External trusted overlay used for final export overrides.
- `My translation`  
  Personal editable draft/review layer.

Effective row text in editor is based on layered comparison, not on DB-only values.

## Row state model

Main states:

- `official` — only official target exists.
- `untranslated` — no official/master/my text.
- `new` — my translation exists, no master equivalent.
- `master` — my translation equals master translation.
- `changed` — my translation differs from master translation.
- `outdated` — source CN changed (`cn_hash` mismatch).
- `approved` / `rejected` — personal review marks.
- `official_match` — my translation equals official target and differs from master.

Notes:

- `approved/rejected` are personal workflow states.
- editing my text can reset personal review status.
- auto-approve may apply when my text equals master text.

## Review behavior

- `Approve` sets personal review status for row/selection.
- `Reject` sets personal review status for row/selection and does not clear text.
- `Save master translation` applies approved personal text into master overlay.
- Master file should remain clean from personal-only review semantics.

## Notes and context

- `Needs Context` is an independent per-row flag.
- `Notes` is a per-row multiline field.
- Both are persisted in personal TSV workflow.

## Glossary behavior

- Glossary loads from external TSV (`CN, EN, Target, Category, Strict`).
- Glossary panel shows row-relevant entries based on source text matches.
- Strict terms are validated by QA (`glossary_term_missing`).

## Required invariants

Never break structural markers:

- placeholders (`{...}`)
- link tags (`<...|...>`)
- color tags (`#Y...#E`, `#RRGGBB...#E`)
- dollar markers (`$...$`, `$S`, `$E`)
- escaped control markers (`\n`, `/w`, etc.)
