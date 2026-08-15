from __future__ import annotations

from html import escape

COLOR_TAGS = {
    "Y": "#F4D35E",
    "G": "#8EE08E",
}


def render_text_to_html(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out: list[str] = []
    stack: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "#" and i + 1 < len(text):
            code = text[i + 1]
            if code in COLOR_TAGS:
                stack.append(code)
                out.append(f"<span style='color:{COLOR_TAGS[code]};font-weight:600'>")
                i += 2
                continue
            if code == "E":
                if stack:
                    stack.pop()
                    out.append("</span>")
                else:
                    warnings.append("closing #E without open tag")
                    out.append(escape("#E"))
                i += 2
                continue
            warnings.append(f"unknown tag #{code}")
            out.append(escape(f"#{code}"))
            i += 2
            continue
        if ch == "{":
            end = text.find("}", i + 1)
            if end != -1:
                token = text[i : end + 1]
                out.append(
                    "<span style='color:#7BDFF2;font-weight:600'>"
                    f"{escape(token)}"
                    "</span>"
                )
                i = end + 1
                continue
        if ch == "\n":
            out.append("<br/>")
        else:
            out.append(escape(ch))
        i += 1
    if stack:
        warnings.append("opening color tag without #E")
    return "".join(out), warnings

