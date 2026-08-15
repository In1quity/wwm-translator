from __future__ import annotations

from html import escape

COLOR_TAGS = {
    "Y": "#F4D35E",
    "G": "#8EE08E",
}
_DOLLAR_VAR_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:.+-")


def _is_hex_color_tag(text: str, pos: int) -> bool:
    if pos + 7 > len(text):
        return False
    chunk = text[pos + 1 : pos + 7]
    return all(ch in "0123456789abcdefABCDEF" for ch in chunk)


def _find_matching_angle(text: str, start: int) -> int:
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == "<":
            depth += 1
        elif text[idx] == ">":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _split_top_level_pipes(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">" and depth > 0:
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _contains_nested_pipe_link(text: str) -> bool:
    idx = 0
    while idx < len(text):
        if text[idx] != "<":
            idx += 1
            continue
        end = _find_matching_angle(text, idx)
        if end == -1:
            return False
        inner = text[idx + 1 : end]
        if len(_split_top_level_pipes(inner)) > 1:
            return True
        idx = end + 1
    return False


def _extract_visible_link_text(payload: str) -> str:
    parts = _split_top_level_pipes(payload)
    base = parts[0] if len(parts) > 1 else payload
    out: list[str] = []
    idx = 0
    while idx < len(base):
        if base[idx] != "<":
            out.append(base[idx])
            idx += 1
            continue
        end = _find_matching_angle(base, idx)
        if end == -1:
            out.append(base[idx])
            idx += 1
            continue
        inner = base[idx + 1 : end]
        nested_parts = _split_top_level_pipes(inner)
        if len(nested_parts) > 1 or _contains_nested_pipe_link(inner):
            out.append(_extract_visible_link_text(inner))
        else:
            out.append(base[idx : end + 1])
        idx = end + 1
    return "".join(out).strip()


def render_text_to_html(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out: list[str] = []
    color_stack: list[str] = []
    conditional_depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            escaped = text[i + 1]
            if escaped == "n":
                out.append("<br/>")
                i += 2
                continue
            if escaped == "r":
                i += 2
                continue
            if escaped == "t":
                out.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                i += 2
                continue
        if ch == "$":
            next_dollar = text.find("$", i + 1)
            if next_dollar != -1:
                token = text[i + 1 : next_dollar]
                token_allowed = token and all(ch_ in _DOLLAR_VAR_ALLOWED for ch_ in token)
                if token_allowed and token not in {"S", "E"}:
                    out.append(
                        "<span style='color:#7BDFF2;font-weight:600'>"
                        f"{escape(text[i : next_dollar + 1])}"
                        "</span>"
                    )
                    i = next_dollar + 1
                    continue
        if ch == "/" and i + 1 < len(text) and not (i > 0 and text[i - 1] == "<"):
            escaped = text[i + 1]
            if escaped == "n":
                out.append("<br/>")
                i += 2
                continue
            if escaped == "r":
                i += 2
                continue
            if escaped == "t":
                out.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                i += 2
                continue
        if ch == "$" and i + 1 < len(text):
            control = text[i + 1]
            if control == "S":
                conditional_depth += 1
                out.append("<span style='color:#B8A9FF;font-weight:600'>")
                i += 2
                continue
            if control == "E":
                if conditional_depth > 0:
                    conditional_depth -= 1
                    out.append("</span>")
                else:
                    warnings.append("closing $E without open $S")
                    out.append(escape("$E"))
                i += 2
                continue
        if ch == "<":
            end = _find_matching_angle(text, i)
            if end == -1 and "|" in text[i : min(len(text), i + 60)]:
                warnings.append("opening < link tag without closing >")
            if end != -1:
                inner = text[i + 1 : end]
                parts = _split_top_level_pipes(inner)
                if len(parts) > 1 or _contains_nested_pipe_link(inner):
                    visible = _extract_visible_link_text(inner)
                    # Pattern like "<...<link|...>> <link|...>" uses the second ">"
                    # as visible separator between linked names in game text.
                    keep_trailing_angle = len(parts) == 1 and end > i and text[end - 1] == ">"
                    out.append(
                        "<span style='color:#9AD1FF;font-weight:600'>"
                        f"{escape(visible)}"
                        "</span>"
                    )
                    if keep_trailing_angle:
                        out.append(escape(">"))
                    i = end + 1
                    continue
        if ch == "#" and i + 1 < len(text):
            code = text[i + 1]
            if _is_hex_color_tag(text, i):
                hex_color = text[i + 1 : i + 7]
                color_stack.append(hex_color)
                out.append(f"<span style='color:#{hex_color};font-weight:600'>")
                i += 7
                continue
            if code in COLOR_TAGS:
                color_stack.append(code)
                out.append(f"<span style='color:{COLOR_TAGS[code]};font-weight:600'>")
                i += 2
                continue
            if code == "E":
                if color_stack:
                    color_stack.pop()
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
    if color_stack:
        warnings.append("opening color tag without #E")
    if conditional_depth > 0:
        warnings.append("opening $S without closing $E")
    return "".join(out), warnings

