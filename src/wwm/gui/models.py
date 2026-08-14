from __future__ import annotations

import sqlite3
from collections import OrderedDict
from dataclasses import dataclass

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from ..overlay import cn_hash

HEADERS = ["state", "category", "id", "cn", "en", "target", "target_official"]
ACTION_HEADERS = ["+", "-"]
_EMPTY_MODEL_INDEX = QModelIndex()
STATE_COLORS = {
    "new": QColor("#8a7420"),
    "changed": QColor("#8a7420"),
    "master": QColor("#245a7a"),
    "outdated": QColor("#8b2d2d"),
    "approved": QColor("#2d6b3c"),
    "rejected": QColor("#6b2d2d"),
    "official": QColor("#3f3f3f"),
    "untranslated": QColor("#555555"),
    "notranslate": QColor("#4a4a4a"),
    "ours": QColor("#8a7420"),
}


@dataclass
class QueryState:
    state: str = ""
    category: str = ""
    issues_only: bool = False
    search: str = ""
    sort_by: str = "id"
    sort_desc: bool = False


class StringsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.master_overlay: dict[str, dict[str, str]] = {}
        self.mine_overlay: dict[str, dict[str, str]] = {}
        self._search_cache_key: tuple[str, str, bool, str, str, bool] | None = None
        self._search_cache_ids: list[str] = []
        self._ensure_overlay_temp_table()

    def set_overlay(self, overlay: dict[str, dict[str, str]]) -> None:
        self.set_overlays(overlay, {})

    def set_overlays(
        self,
        master_overlay: dict[str, dict[str, str]],
        mine_overlay: dict[str, dict[str, str]],
    ) -> None:
        self.master_overlay = master_overlay
        self.mine_overlay = mine_overlay
        self._reload_overlay_temp_table()
        self.clear_search_cache()

    def clear_search_cache(self) -> None:
        self._search_cache_key = None
        self._search_cache_ids = []

    def count(self, q: QueryState) -> int:
        if self._can_use_sql_state_filter(q):
            return self._count_sql_state(q)
        if self._use_materialized_ids(q):
            return len(self._get_search_ids(q))
        if not q.state and not q.search:
            where, params = _where_without_state(q)
            where = _append_visibility_clause(where)
            row = self.conn.execute(f"SELECT COUNT(*) FROM strings s {where}", params).fetchone()
            return int(row[0] if row else 0)
        count = 0
        for item in self._iter_filtered_rows(q):
            _ = item
            count += 1
        return count

    def fetch(self, q: QueryState, limit: int, offset: int) -> list[dict[str, str]]:
        if self._use_materialized_ids(q):
            out: list[dict[str, str]] = []
            ordered_ids = self._get_search_ids(q)[offset : offset + limit]
            if not ordered_ids:
                return out
            rows_by_id: dict[str, sqlite3.Row] = {}
            for row in self._iter_rows_by_ids(set(ordered_ids)):
                rows_by_id[(row["id"] or "").lower()] = row
            for row_id in ordered_ids:
                row = rows_by_id.get((row_id or "").lower())
                if row is None:
                    continue
                state, target_ours, _target_master = self.resolve_overlay(
                    row["id"], row["cn"], row["target_official"]
                )
                out.append(
                    {
                        "state": state,
                        "category": row["category"],
                        "id": row["id"],
                        "cn": row["cn"],
                        "en": row["en"],
                        "target": target_ours,
                        "target_official": row["target_official"],
                    }
                )
            return out

        if self._can_use_sql_page_fetch(q):
            return self._fetch_sql_page(q, limit, offset)

        out: list[dict[str, str]] = []
        idx = 0
        end = offset + limit
        for item in self._iter_filtered_rows(q):
            if idx >= end:
                break
            if idx >= offset:
                out.append(item)
            idx += 1
        return out

    def get_row(self, row_id: str) -> dict[str, str] | None:
        row = self.conn.execute(
            "SELECT id, cn, en, target_official, category FROM strings WHERE id = ?",
            (row_id,),
        ).fetchone()
        if row is None:
            return None
        state, target_ours, target_master = self.resolve_overlay(
            row["id"], row["cn"], row["target_official"]
        )
        return {
            "id": row["id"],
            "cn": row["cn"],
            "en": row["en"],
            "target_official": row["target_official"],
            "target": target_ours,
            "target_master": target_master,
            "state": state,
            "category": row["category"],
        }

    def resolve_overlay(
        self, row_id: str, cn_text: str, target_official: str
    ) -> tuple[str, str, str]:
        key = (row_id or "").lower()
        current_hash = cn_hash(cn_text or "")
        master_item = self.master_overlay.get(key)
        mine_item = self.mine_overlay.get(key)

        target_master = master_item.get("target", "") if master_item else ""

        if mine_item:
            target_mine = mine_item.get("target", "")
            if mine_item.get("cn_hash", "") != current_hash:
                return ("outdated", target_mine, target_master)
            if master_item and master_item.get("cn_hash", "") != current_hash:
                return ("outdated", target_mine, target_master)
            mine_state = mine_item.get("state", "ours")
            if mine_state in ("approved", "notranslate", "rejected"):
                return (mine_state, target_mine, target_master)
            if not master_item:
                return ("new", target_mine, "")
            if target_mine.strip() != target_master.strip():
                return ("changed", target_mine, target_master)
            return ("ours", target_mine, target_master)

        if master_item:
            if master_item.get("cn_hash", "") != current_hash:
                return ("outdated", target_master, target_master)
            return ("master", target_master, target_master)

        if (target_official or "").strip():
            return ("official", "", "")
        return ("untranslated", "", "")

    def qa_for(self, row_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT rule, severity, detail FROM qa_issues WHERE id = ? "
            "ORDER BY severity DESC, rule",
            (row_id,),
        ).fetchall()

    def _iter_filtered_rows(self, q: QueryState):
        where, params = _where_without_state(q)
        where = _append_visibility_clause(where)
        if self._use_materialized_ids(q):
            ids = self._get_search_ids(q)
            if not ids:
                return
            page_size = 2000
            offset = 0
            while True:
                page = self.fetch(q, limit=page_size, offset=offset)
                if not page:
                    break
                for row in page:
                    yield row
                offset += page_size
            return

        offset = 0
        step = 10000
        order = _sql_order_clause(q)
        query = (
            "SELECT s.id, s.cn, s.en, s.target_official, s.category "
            f"FROM strings s {where} ORDER BY {order} LIMIT ? OFFSET ?"
        )
        while True:
            rows = self.conn.execute(query, (*params, step, offset)).fetchall()
            if not rows:
                break
            for row in rows:
                state, target_ours, _target_master = self.resolve_overlay(
                    row["id"], row["cn"], row["target_official"]
                )
                if q.state and state != q.state:
                    continue
                yield {
                    "state": state,
                    "category": row["category"],
                    "id": row["id"],
                    "cn": row["cn"],
                    "en": row["en"],
                    "target": target_ours,
                    "target_official": row["target_official"],
                }
            offset += step

    def _query_key(self, q: QueryState) -> tuple[str, str, bool, str, str, bool]:
        return (
            q.state,
            q.category,
            q.issues_only,
            (q.search or "").casefold(),
            q.sort_by,
            q.sort_desc,
        )

    def _get_search_ids(self, q: QueryState) -> list[str]:
        key = self._query_key(q)
        if self._search_cache_key == key:
            return self._search_cache_ids
        self._search_cache_ids = self._compute_search_ids(q)
        self._search_cache_key = key
        return self._search_cache_ids

    def _compute_search_ids(self, q: QueryState) -> list[str]:
        needle = (q.search or "").casefold()
        sparse_states = {
            "changed",
            "approved",
            "rejected",
            "notranslate",
            "outdated",
            "new",
            "master",
            "ours",
        }
        if not needle and q.state == "new" and not self.mine_overlay:
            return []

        if needle:
            candidate_ids = self._search_candidate_ids(needle)
            for row_id in self._overlay_ids():
                mine_target = self.mine_overlay.get(row_id, {}).get("target", "")
                master_target = self.master_overlay.get(row_id, {}).get("target", "")
                if (
                    needle in row_id.casefold()
                    or needle in mine_target.casefold()
                    or needle in master_target.casefold()
                ):
                    candidate_ids.add((row_id or "").lower())
            if not candidate_ids:
                return []
            source_rows = self._iter_rows_by_ids(candidate_ids)
        elif q.state in sparse_states:
            candidate_ids = self._overlay_ids()
            if not candidate_ids:
                return []
            source_rows = self._iter_rows_by_ids(candidate_ids)
        else:
            where, params = _where_without_state(q)
            where = _append_visibility_clause(where)
            offset = 0
            step = 10000
            query = (
                "SELECT s.id, s.cn, s.en, s.target_official, s.category "
                f"FROM strings s {where} ORDER BY s.id LIMIT ? OFFSET ?"
            )

            def _stream_rows():
                nonlocal offset
                while True:
                    rows = self.conn.execute(query, (*params, step, offset)).fetchall()
                    if not rows:
                        break
                    yield from rows
                    offset += step

            source_rows = _stream_rows()

        matched_items: list[dict[str, str]] = []
        for row in source_rows:
            state, target_ours, _target_master = self.resolve_overlay(
                row["id"], row["cn"], row["target_official"]
            )
            item = {
                "state": state,
                "category": row["category"],
                "id": row["id"],
                "cn": row["cn"],
                "en": row["en"],
                "target": target_ours,
                "target_official": row["target_official"],
            }
            if _hide_en_only_row(item):
                continue
            if needle and not _row_matches_search(item, needle):
                continue
            if q.state and item["state"] != q.state:
                continue
            if q.category and item["category"] != q.category:
                continue
            if q.issues_only and not self._has_issue(item["id"]):
                continue
            matched_items.append(item)

        reverse = q.sort_desc
        sort_by = q.sort_by if q.sort_by in HEADERS else "id"
        matched_items.sort(
            key=lambda x: ((x.get(sort_by) or "").casefold(), (x.get("id") or "").casefold()),
            reverse=reverse,
        )
        return [(item["id"] or "").lower() for item in matched_items]

    def _use_materialized_ids(self, q: QueryState) -> bool:
        overlay_states = {
            "changed",
            "approved",
            "rejected",
            "notranslate",
            "outdated",
            "new",
            "master",
            "ours",
        }
        return bool(q.search) or q.sort_by in ("state", "target") or (q.state in overlay_states)

    def _search_candidate_ids(self, needle: str) -> set[str]:
        ids: set[str] = set()
        fts_failed = False
        try:
            for row in self.conn.execute(
                "SELECT id FROM strings_fts WHERE strings_fts MATCH ? LIMIT 200000",
                (_as_fts_literal(needle),),
            ):
                ids.add((row["id"] or "").lower())
        except sqlite3.OperationalError:
            fts_failed = True

        if len(needle) >= 2:
            like = f"%{needle}%"
            for row in self.conn.execute(
                "SELECT id FROM strings WHERE lower(id) LIKE ? LIMIT 50000",
                (like,),
            ):
                ids.add((row["id"] or "").lower())

        if fts_failed or len(needle) < 3:
            like = f"%{needle}%"
            for row in self.conn.execute(
                """
                SELECT id
                FROM strings
                WHERE cn LIKE ? COLLATE NOCASE
                   OR en LIKE ? COLLATE NOCASE
                   OR target_official LIKE ? COLLATE NOCASE
                LIMIT 50000
                """,
                (like, like, like),
            ):
                ids.add((row["id"] or "").lower())
        return ids

    def _overlay_ids(self) -> set[str]:
        return set(self.master_overlay.keys()) | set(self.mine_overlay.keys())

    def _iter_rows_by_ids(self, ids: set[str]):
        if not ids:
            return
        ordered = sorted(ids)
        batch_size = 800
        for i in range(0, len(ordered), batch_size):
            chunk = ordered[i : i + batch_size]
            placeholders = ",".join("?" for _ in chunk)
            sql = (
                "SELECT id, cn, en, target_official, category "
                f"FROM strings WHERE id IN ({placeholders}) ORDER BY id"
            )
            yield from self.conn.execute(sql, chunk)

    def _can_use_sql_page_fetch(self, q: QueryState) -> bool:
        if q.search:
            return False
        if not q.state:
            return True
        return self._can_use_sql_state_filter(q)

    def _fetch_sql_page(self, q: QueryState, limit: int, offset: int) -> list[dict[str, str]]:
        where, params = _where_without_state(q)
        where = _append_visibility_clause(where)
        if self._can_use_sql_state_filter(q):
            where = _append_sql_state_clause(where, q.state)
        order = _sql_order_clause(q)
        rows = self.conn.execute(
            (
                "SELECT s.id, s.cn, s.en, s.target_official, s.category "
                f"FROM strings s {where} ORDER BY {order} LIMIT ? OFFSET ?"
            ),
            (*params, limit, offset),
        ).fetchall()
        out: list[dict[str, str]] = []
        for row in rows:
            state, target_ours, _target_master = self.resolve_overlay(
                row["id"], row["cn"], row["target_official"]
            )
            if q.state and state != q.state:
                continue
            out.append(
                {
                    "state": state,
                    "category": row["category"],
                    "id": row["id"],
                    "cn": row["cn"],
                    "en": row["en"],
                    "target": target_ours,
                    "target_official": row["target_official"],
                }
            )
        return out

    def fetch_sql_page_after_id(
        self, q: QueryState, limit: int, last_id: str
    ) -> list[dict[str, str]]:
        where, params = _where_without_state(q)
        where = _append_visibility_clause(where)
        clause = "WHERE s.id > ?" if not where else f"{where} AND s.id > ?"
        rows = self.conn.execute(
            (
                "SELECT s.id, s.cn, s.en, s.target_official, s.category "
                f"FROM strings s {clause} ORDER BY s.id COLLATE NOCASE ASC LIMIT ?"
            ),
            (*params, last_id, limit),
        ).fetchall()
        out: list[dict[str, str]] = []
        for row in rows:
            state, target_ours, _target_master = self.resolve_overlay(
                row["id"], row["cn"], row["target_official"]
            )
            out.append(
                {
                    "state": state,
                    "category": row["category"],
                    "id": row["id"],
                    "cn": row["cn"],
                    "en": row["en"],
                    "target": target_ours,
                    "target_official": row["target_official"],
                }
            )
        return out

    def _has_issue(self, row_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM qa_issues WHERE id = ? LIMIT 1", (row_id,)
        ).fetchone()
        return row is not None

    def _ensure_overlay_temp_table(self) -> None:
        self.conn.execute("CREATE TEMP TABLE IF NOT EXISTS overlay_ids (id TEXT PRIMARY KEY)")

    def _reload_overlay_temp_table(self) -> None:
        self._ensure_overlay_temp_table()
        self.conn.execute("DELETE FROM overlay_ids")
        overlay_ids = self._overlay_ids()
        if not overlay_ids:
            return
        self.conn.executemany(
            "INSERT OR IGNORE INTO overlay_ids(id) VALUES(?)",
            [((row_id or "").lower(),) for row_id in overlay_ids],
        )

    def _count_sql_state(self, q: QueryState) -> int:
        where, params = _where_without_state(q)
        where = _append_visibility_clause(where)
        where = _append_sql_state_clause(where, q.state)
        row = self.conn.execute(f"SELECT COUNT(*) FROM strings s {where}", params).fetchone()
        return int(row[0] if row else 0)

    def _can_use_sql_state_filter(self, q: QueryState) -> bool:
        return q.state in ("official", "untranslated") and q.sort_by not in ("state", "target")


class StringsTableModel(QAbstractTableModel):
    def __init__(self, repo: StringsRepository) -> None:
        super().__init__()
        self.repo = repo
        self.q = QueryState()
        self.page_size = 500
        self.max_cached_pages = 12
        self.total = 0
        self.cache: OrderedDict[int, list[dict[str, str]]] = OrderedDict()
        self.reload()

    def rowCount(self, parent: QModelIndex = _EMPTY_MODEL_INDEX) -> int:  # noqa: N802
        _ = parent
        return self.total

    def columnCount(self, parent: QModelIndex = _EMPTY_MODEL_INDEX) -> int:  # noqa: N802
        _ = parent
        return len(ACTION_HEADERS) + len(HEADERS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._column_name(section)
        return section + 1

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row = self._row(index.row())
        if row is None:
            return None
        column = index.column()
        if column < len(ACTION_HEADERS):
            row_id = (row.get("id") or "").lower()
            mine_state = self.repo.mine_overlay.get(row_id, {}).get("state", "ours")
            is_accept = column == 0
            is_active = mine_state == ("approved" if is_accept else "rejected")
            if role == Qt.ItemDataRole.DisplayRole:
                return ACTION_HEADERS[column]
            if role == Qt.ItemDataRole.ToolTipRole:
                if is_accept:
                    return "Accept: include in master translation"
                return "Reject: exclude from master translation"
            if role == Qt.ItemDataRole.ForegroundRole:
                if is_active:
                    return QColor("#f0f0f0")
                return QColor("#7a7a7a")
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignCenter)
            if role == Qt.ItemDataRole.BackgroundRole:
                return STATE_COLORS.get(row["state"], None)
            return None

        col = HEADERS[column - len(ACTION_HEADERS)]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[col]
        if role == Qt.ItemDataRole.BackgroundRole:
            return STATE_COLORS.get(row["state"], None)
        return None

    def set_query(self, q: QueryState) -> None:
        q.sort_by = self.q.sort_by
        q.sort_desc = self.q.sort_desc
        self.q = q
        self.reload()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        if column < 0 or column >= len(ACTION_HEADERS) + len(HEADERS):
            return
        if column < len(ACTION_HEADERS):
            return
        self.q.sort_by = HEADERS[column - len(ACTION_HEADERS)]
        self.q.sort_desc = order == Qt.SortOrder.DescendingOrder
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self.repo.clear_search_cache()
        self.total = self.repo.count(self.q)
        self.cache.clear()
        self.endResetModel()

    def row_id(self, index: int) -> str | None:
        row = self._row(index)
        if row is None:
            return None
        return str(row["id"])

    def refresh_row(self, row_index: int) -> None:
        if row_index < 0 or row_index >= self.total:
            return
        page = row_index // self.page_size
        rel = row_index % self.page_size
        chunk = self.cache.get(page)
        if chunk is None or rel >= len(chunk):
            return
        row_id = chunk[rel].get("id", "")
        fresh = self.repo.get_row(row_id)
        if fresh is None:
            return
        chunk[rel] = {
            "state": fresh["state"],
            "category": fresh["category"],
            "id": fresh["id"],
            "cn": fresh["cn"],
            "en": fresh["en"],
            "target": fresh["target"],
            "target_official": fresh["target_official"],
        }
        top_left = self.index(row_index, 0)
        bottom_right = self.index(row_index, self.columnCount() - 1)
        self.dataChanged.emit(top_left, bottom_right)

    def refresh_row_by_id(self, row_id: str) -> None:
        key = (row_id or "").lower()
        if not key:
            return
        for page, chunk in self.cache.items():
            for rel, item in enumerate(chunk):
                if (item.get("id") or "").lower() == key:
                    self.refresh_row(page * self.page_size + rel)
                    return

    def _column_name(self, section: int) -> str:
        if section < len(ACTION_HEADERS):
            return ACTION_HEADERS[section]
        data_idx = section - len(ACTION_HEADERS)
        if data_idx < len(HEADERS):
            return HEADERS[data_idx]
        return ""

    def _row(self, index: int) -> dict[str, str] | None:
        page = index // self.page_size
        if page not in self.cache:
            self.cache[page] = self._load_page(page)
            self.cache.move_to_end(page)
            while len(self.cache) > self.max_cached_pages:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(page)
        rel = index % self.page_size
        chunk = self.cache.get(page, [])
        if rel >= len(chunk):
            return None
        return chunk[rel]

    def _load_page(self, page: int) -> list[dict[str, str]]:
        if (
            page > 0
            and page - 1 in self.cache
            and not self.q.search
            and not self.q.state
            and not self.q.sort_desc
            and self.q.sort_by == "id"
        ):
            prev = self.cache[page - 1]
            if prev:
                return self.repo.fetch_sql_page_after_id(self.q, self.page_size, prev[-1]["id"])
        return self.repo.fetch(self.q, self.page_size, page * self.page_size)


def _where_without_state(q: QueryState) -> tuple[str, tuple]:
    clauses = []
    params: list[str] = []
    if q.category:
        clauses.append("s.category = ?")
        params.append(q.category)
    if q.issues_only:
        clauses.append("EXISTS (SELECT 1 FROM qa_issues q WHERE q.id = s.id)")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, tuple(params)


def _row_matches_search(item: dict[str, str], needle: str) -> bool:
    return (
        needle in (item["id"] or "").casefold()
        or needle in (item["cn"] or "").casefold()
        or needle in (item["en"] or "").casefold()
        or needle in (item["target"] or "").casefold()
        or needle in (item["target_official"] or "").casefold()
    )


def _as_fts_literal(value: str) -> str:
    escaped = (value or "").replace('"', '""')
    return f'"{escaped}"'


def _sql_order_clause(q: QueryState) -> str:
    allowed = {"category", "id", "cn", "en", "target_official"}
    sort_by = q.sort_by if q.sort_by in allowed else "id"
    direction = "DESC" if q.sort_desc else "ASC"
    if sort_by == "id":
        return f"s.id COLLATE NOCASE {direction}"
    return f"s.{sort_by} COLLATE NOCASE {direction}, s.id COLLATE NOCASE ASC"


def _append_visibility_clause(where: str) -> str:
    hidden = "(trim(ifnull(s.cn,'')) = '')"
    if where:
        return f"{where} AND NOT {hidden}"
    return f"WHERE NOT {hidden}"


def _append_sql_state_clause(where: str, state: str) -> str:
    if state == "official":
        clause = (
            "NOT EXISTS (SELECT 1 FROM overlay_ids oi WHERE oi.id = lower(s.id)) "
            "AND trim(ifnull(s.target_official,'')) != ''"
        )
    elif state == "untranslated":
        clause = (
            "NOT EXISTS (SELECT 1 FROM overlay_ids oi WHERE oi.id = lower(s.id)) "
            "AND trim(ifnull(s.target_official,'')) = ''"
        )
    else:
        clause = "1=1"
    if where:
        return f"{where} AND {clause}"
    return f"WHERE {clause}"


def _hide_en_only_row(item: dict[str, str]) -> bool:
    cn = (item.get("cn") or "").strip()
    return not cn
