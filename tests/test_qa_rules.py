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
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" not in rules


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
    issue_map = {(rule, severity, detail) for _row_id, rule, severity, detail in issues}
    assert ("angle_tag_suspect", "warning", "10") in issue_map


def test_check_row_forbids_unknown_latin_xml_tags() -> None:
    issues = check_row(
        row_id="row-4b",
        cn="plain",
        en="plain",
        target="Текст с <customTag>",
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" in rules


def test_check_row_allows_plain_tags_when_present_in_cn() -> None:
    cn = "<term><src>Hidden Mountain</src><dst>Скрытая Гора</dst></term>"
    target = "<term><src>Hidden Mountain</src><dst>Тайная Гора</dst></term>"
    issues = check_row(
        row_id="row-5",
        cn=cn,
        en="",
        target=target,
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" not in rules


def test_check_row_allows_tags_with_attributes_from_cn() -> None:
    cn = (
        "<LINK id='link2' color='#8c5823' goto_id='60249' is_underline='true'>"
        "前往【挑战】"
        "</LINK>"
    )
    target = (
        "<LINK id='link2' color='#8c5823' goto_id='60249' is_underline='true'>"
        "Перейти"
        "</LINK>"
    )
    issues = check_row(
        row_id="row-7",
        cn=cn,
        en="",
        target=target,
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" not in rules


def test_check_row_forbids_unknown_tag_with_attributes() -> None:
    cn = "plain source"
    target = "<UNKNOWN id='x'>bad</UNKNOWN>"
    issues = check_row(
        row_id="row-8",
        cn=cn,
        en="",
        target=target,
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "xml_tag_forbidden" in rules


def test_check_row_allows_single_color_tag_from_cn() -> None:
    cn = "#Y测试#E"
    target = "#YТест#E"
    issues = check_row(
        row_id="row-9",
        cn=cn,
        en="",
        target=target,
        glossary_rows=[],
        target_lang="ru",
    )
    rules = {rule for _row_id, rule, _severity, _detail in issues}
    assert "color_tag_forbidden" not in rules


def test_check_row_forbids_single_color_tag_missing_in_cn() -> None:
    cn = "#Y测试#E"
    target = "#QТест#E"
    issues = check_row(
        row_id="row-10",
        cn=cn,
        en="",
        target=target,
        glossary_rows=[],
        target_lang="ru",
    )
    issue_map = {(rule, detail) for _row_id, rule, _severity, detail in issues}
    assert ("color_tag_forbidden", "09") in issue_map
