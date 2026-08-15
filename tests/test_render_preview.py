from __future__ import annotations

from wwm.render_preview import render_text_to_html


def test_render_supports_escaped_newlines() -> None:
    html, warnings = render_text_to_html("line1\\nline2/nline3")
    assert "<br/>" in html
    assert not warnings


def test_render_keeps_link_tags_as_single_token() -> None:
    html, warnings = render_text_to_html("<Название|780|#C|15>")
    assert "#C" in html
    assert "unknown tag #C" not in warnings


def test_render_reports_unbalanced_color_tag() -> None:
    _html, warnings = render_text_to_html("#E orphan close")
    assert "closing #E without open tag" in warnings


def test_render_reports_unbalanced_conditional_tags() -> None:
    _html, warnings = render_text_to_html("$S text")
    assert "opening $S without closing $E" in warnings
