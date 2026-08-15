from __future__ import annotations

from wwm.render_preview import render_text_to_html


def test_render_supports_escaped_newlines() -> None:
    html, warnings = render_text_to_html("line1\\nline2/nline3")
    assert "<br/>" in html
    assert not warnings


def test_render_keeps_link_tags_as_single_token() -> None:
    html, warnings = render_text_to_html("<Название|780|#C|15>")
    assert "Название" in html
    assert "#C" not in html
    assert "unknown tag #C" not in warnings


def test_render_reports_unbalanced_color_tag() -> None:
    _html, warnings = render_text_to_html("#E orphan close")
    assert "closing #E without open tag" in warnings


def test_render_reports_unbalanced_conditional_tags() -> None:
    _html, warnings = render_text_to_html("$S text")
    assert "opening $S without closing $E" in warnings


def test_render_does_not_break_closing_term_tag() -> None:
    html, warnings = render_text_to_html("<term>doc</term>{0}")
    assert "&lt;term&gt;doc&lt;/term&gt;" in html
    assert "unknown tag #C" not in warnings


def test_render_supports_hex_color_tags() -> None:
    html, warnings = render_text_to_html("#44729fСиний#E: #734fa0Пурпурный#E")
    assert "color:#44729f" in html
    assert "color:#734fa0" in html
    assert "closing #E without open tag" not in warnings


def test_render_supports_dollar_wrapped_variables() -> None:
    html, warnings = render_text_to_html("$STEADY_MIN_PRO_ATK_E:.1f$")
    assert "$STEADY_MIN_PRO_ATK_E:.1f$" in html
    assert "opening $S without closing $E" not in warnings


def test_render_supports_nested_link_payloads() -> None:
    source = (
        "<Заряженный навык <Бродячего меча|781|#C|10102|781>> "
        "<Меча Безымянного|#C|10102|20201006>"
    )
    html, warnings = render_text_to_html(source)
    assert "Заряженный навык Бродячего меча" in html
    assert "Меча Безымянного" in html
    assert "#C" not in html
    assert not warnings


def test_render_keeps_separator_angle_for_double_closing_pattern() -> None:
    source = (
        "<Заряженный навык <Бродячего меча|781|#C|10102|781>> "
        "<Меча Безымянного|#C|10102|20201006>"
    )
    html, _warnings = render_text_to_html(source)
    assert "&gt; <span style='color:#9AD1FF;font-weight:600'>" in html
