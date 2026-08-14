from __future__ import annotations

from wwm.overlay import merge_master_rows


def test_merge_master_rows_keeps_master_and_adds_only_approved() -> None:
    master_rows = {
        "id_a": {"cn_hash": "h1", "state": "ours", "target": "Master A"},
        "id_b": {"cn_hash": "h2", "state": "ours", "target": "Master B"},
    }
    mine_rows = {
        "id_b": {
            "cn_hash": "h2",
            "state": "approved",
            "target": "Mine Approved Update",
            "cn": "cn b",
            "en": "en b",
        },
        "id_c": {
            "cn_hash": "h3",
            "state": "approved",
            "target": "Mine Approved New",
            "cn": "cn c",
            "en": "en c",
        },
        "id_d": {
            "cn_hash": "h4",
            "state": "ours",
            "target": "Mine Pending",
            "cn": "cn d",
            "en": "en d",
        },
        "id_e": {
            "cn_hash": "h5",
            "state": "rejected",
            "target": "Mine Rejected",
            "cn": "cn e",
            "en": "en e",
        },
    }

    merged = merge_master_rows(master_rows, mine_rows)

    assert merged["id_a"]["target"] == "Master A"
    assert merged["id_b"]["target"] == "Mine Approved Update"
    assert merged["id_c"]["target"] == "Mine Approved New"
    assert "id_d" not in merged
    assert "id_e" not in merged
