# Translation TSV format

The application supports two translation TSV schemas.

## 1) Master translation TSV

Header:

`ID	cn_hash	state	target	needs_context	notes`

Fields:

- `ID` — locale string ID.
- `cn_hash` — first 16 chars of SHA-256 for CN text.
- `state` — optional status marker (usually `ours`, `master`, `approved`, `notranslate`).
- `target` — translated text.
- `needs_context` — `1`/`0` flag.
- `notes` — free multiline notes text.

Used by:

- GUI button **Load master translation**
- CLI `--master` arguments (`qa` and `export`)

## 2) Project translation TSV

Header:

`ID	cn_hash	state	target	cn	en	needs_context	notes`

Additional fields:

- `cn` — source CN snapshot for review/debug.
- `en` — source EN snapshot for review/debug.
- `needs_context` — per-row context request flag (`1`/`0`).
- `notes` — per-row notes text.

Used by:

- GUI button **Save translation**
- stored at `data/projects/<slug>_<lang>/my_translation.tsv`

## Parsing rules

- Encoding: UTF-8/UTF-8 BOM.
- Delimiter: tab.
- Rows with fewer than 4 columns are ignored.
- Extra columns are ignored.
- IDs are normalized to lowercase internally.
