# Tags, markers, and placeholders

Translator behavior depends on preserving game formatting markers.

## Placeholder tokens

Examples:

- `{0}`
- `{player_name}`
- `{1:.1%}`
- `{total_day:d}`

Rule:

- keep the same placeholder set between source and translation;
- keep format specifiers (`:d`, `:.1f`, `:.1%`, etc.) intact.

## Link tags

Pattern family:

- `<Visible text|...technical payload...>`
- nested variants with additional `<...>` blocks

Rules:

- do not remove opening/closing angle brackets;
- keep the same logical tag count as source;
- keep payload separators `|` intact.

Rendered Preview:

- shows only visible text part;
- strips technical payload for readability;
- warns on malformed/unbalanced links.

## Color tags

Supported color markers:

- short: `#Y...#E`, `#G...#E`
- hex: `#RRGGBB...#E`

Rules:

- every color start must have a matching `#E`;
- do not break nested text inside color span.

## Dollar markers

Supported:

- variable blocks: `$SOME_VAR$`, `$VAR_E:.1f$`
- service markers: `$S`, `$E`

Rules:

- preserve dollar pairs and marker spelling exactly;
- do not delete service markers even if not visible in final UI.

## Escaped control markers

Common markers:

- `\n`, `/n` -> line break
- `\r`, `/r` -> carriage-return style break
- `\t`, `/t` -> tab spacing
- `\w`, `/w` -> paragraph break (double line break)

Rules:

- preserve marker characters and slash/backslash form unless intentionally normalized;
- avoid replacing markers with literal whitespace in source text.

## QA validation scope

QA checks consistency for:

- placeholders;
- link-tag structure/count;
- render parser warnings (broken tag syntax);
- glossary strict term usage.

If a text includes complex tags, edit only natural language fragments and keep all marker segments
unchanged.
