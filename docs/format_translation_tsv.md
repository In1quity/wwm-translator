# Translation TSV format

The application uses two TSV overlay types.

## 1) Master translation TSV

Preferred header:

`ID	cn_hash	state	target`

Supported extended header (legacy-compatible):

`ID	cn_hash	state	target	needs_context	notes`

Field meaning:

- `ID` — locale row id.
- `cn_hash` — first 16 chars of SHA-256 from source CN.
- `state` — persisted as normalized master state (`ours`).
- `target` — translation override text.
- `needs_context`, `notes` — optional/pass-through compatibility fields.

Important behavior:

- personal review states (`approved` / `rejected`) are not master-authoritative;
- when loaded, master states are normalized (review states do not remain in master layer).

Used by:

- GUI: `Project -> Load master translation`
- GUI: `Translation -> Save master translation`
- CLI: `--master` in QA/export commands

## 2) Personal translation TSV (`my_translation.tsv`)

Header:

`ID	cn_hash	state	target	cn	en	needs_context	notes`

Fields:

- `state` — personal workflow state (`ours`, `approved`, `rejected`, etc.).
- `target` — editable personal translation.
- `cn`, `en` — source snapshots for local review/debug.
- `needs_context` — personal context flag (`1`/`0`).
- `notes` — personal note text.

Used by:

- GUI: `Translation -> Save translation`
- Stored at: `data/projects/<slug>_<lang>/my_translation.tsv`

## Parsing and compatibility rules

- Encoding: UTF-8 or UTF-8 BOM.
- Delimiter: tab.
- IDs are normalized to lowercase.
- Rows with fewer than 4 columns are ignored.
- Extra columns are ignored.
- Missing optional columns default to safe values.
