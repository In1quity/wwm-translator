from __future__ import annotations

from wwm.qa import check_row


def test_check_row_reports_forbidden_xml_tags() -> None:
    issues = check_row(
        row_id="row-1",
        cn="plain source",
        en="plain source",
        target="Текст с <tag>внутри</tag>",
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" in rules


def test_check_row_allows_game_link_tags() -> None:
    text = "<Название|780|#C|15>"
    issues = check_row(
        row_id="row-2",
        cn=text,
        en="",
        target=text,
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" not in rules
