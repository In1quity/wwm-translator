# Tags and placeholders

The translator validates tag integrity between source (`CN`) and translation (`target`).

## Placeholders

Pattern examples:

- `{0}`
- `{player_name}`
- `{total_day:d}`

Rule:

- Keep the same placeholder set in translation as in source.

## Link tags

Pattern:

`<...|...|...|...>`

Rule:

- Keep tag count and structure consistent with source.

## Escaped sequences

Keep escaped control characters intact:

- `\n`
- `\r`
- `\t`

## Practical recommendation

When editing long strings, avoid rewriting tag-containing segments unless needed. Translate
surrounding text while preserving structural markers exactly.
