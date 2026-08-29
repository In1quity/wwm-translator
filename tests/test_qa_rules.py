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


def test_check_row_forbids_link_tags_with_extra_params() -> None:
    text = "<Название|780|#C|10102|15>"
    issues = check_row(
        row_id="row-3",
        cn=text,
        en="",
        target=text,
        glossary_rows=[],
        target_lang="ru",
    )
    issue_map = {(rule, detail) for _row_id, rule, _severity, detail in issues}
    assert ("xml_tag_forbidden", "08") in issue_map


def test_check_row_reports_mismatch_when_target_has_wrong_link_tag_shape() -> None:
    cn = "<Название|780|#C|15>"
    target = "<Название|780|#C|10102|15>"
    issues = check_row(
        row_id="row-3b",
        cn=cn,
        en="",
        target=target,
        glossary_rows=[],
        target_lang="ru",
    )
    issue_map = {(rule, detail) for _row_id, rule, _severity, detail in issues}
    assert ("xml_tag_forbidden", "08") in issue_map
    assert ("link_tag_count_mismatch", "04") in issue_map


def test_check_row_forbids_plain_angle_tags() -> None:
    issues = check_row(
        row_id="row-4",
        cn="plain",
        en="plain",
        target="Текст с <подсказка>",
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" in rules
