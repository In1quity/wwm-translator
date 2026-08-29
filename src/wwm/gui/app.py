from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from PyQt6.QtCore import QModelIndex, QObject, QRegularExpression, Qt, QThread, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..base import build_versioned_base
from ..build import build_translation_release
from ..db import open_db, rebuild_cache
from ..glossary import load_glossary_to_db
from ..overlay import (
    cn_hash,
    load_overlay,
    load_translation_rows,
    merge_master_rows,
    normalize_master_rows,
    save_overlay,
    save_translation_rows,
)
from ..project import (
    LANG_CODES,
    ProjectPaths,
    load_project_meta,
    load_recent_projects,
    open_project,
)
from ..qa import (
    check_row_into_db,
    qa_detail_message,
    qa_rule_category,
    qa_rule_title,
    run_qa,
    run_qa_on_map,
)
from ..tm import rebuild_tm
from ..version import detect_client_version
from .models import QueryState, StringsRepository, StringsTableModel
from .panels import (
    fill_glossary_panel,
    fill_qa_overview_panel,
    fill_qa_panel,
    fill_same_source_panel,
    fill_tm_panel,
    render_preview_html,
)


class TagHighlighter(QSyntaxHighlighter):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        game_tag = QTextCharFormat()
        game_tag.setForeground(QColor("#F4D35E"))
        game_tag.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r"#[A-DF-Za-df-z][^#\n]{0,400}#E"), game_tag))
        self.rules.append((QRegularExpression(r"#[0-9A-Fa-f]{6}[^#\n]{0,400}#E"), game_tag))

        placeholder = QTextCharFormat()
        placeholder.setForeground(QColor("#7BDFF2"))
        placeholder.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r"\{[^{}\n]{1,120}\}"), placeholder))

        control_markers = QTextCharFormat()
        control_markers.setForeground(QColor("#FF8C42"))
        control_markers.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r"\\[nrtw]"), control_markers))
        self.rules.append((QRegularExpression(r"/[nrtw]"), control_markers))
        self.rules.append((QRegularExpression(r"\$[A-Za-z0-9_:.+\-]+\$"), control_markers))
        self.rules.append((QRegularExpression(r"\$(?:S|E|P|N)"), control_markers))

        xml_like = QTextCharFormat()
        xml_like.setForeground(QColor("#B8F2E6"))
        self.rules.append((QRegularExpression(r"<[^<>\n]{1,200}>"), xml_like))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for regex, fmt in self.rules:
            it = regex.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class ActionCellDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:  # noqa: D401
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg is not None:
            painter.fillRect(option.rect, bg)

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        fg_name = str(fg.name()) if fg is not None else ""
        is_active = fg_name == QColor("#f0f0f0").name()
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        pressed = bool(option.state & QStyle.StateFlag.State_Sunken)
        if is_active:
            fill = QColor("#355d3f")
        else:
            fill = QColor("#2f2f2f")
        if hover:
            fill = fill.lighter(125)
        if pressed:
            fill = fill.darker(125)
        button_rect = option.rect.adjusted(6, 4, -6, -4)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor("#555555"))
        painter.setBrush(fill)
        painter.drawRoundedRect(button_rect, 5, 5)
        painter.setPen(QColor("#f0f0f0") if is_active else QColor("#b5b5b5"))
        painter.drawText(button_rect, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()


class ProjectOpenWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, game_root: Path, target_lang: str) -> None:
        super().__init__()
        self.game_root = game_root
        self.target_lang = target_lang

    def run(self) -> None:
        try:
            self.progress.emit("Opening project...")
            project = open_project(self.game_root, self.target_lang)
            if self._has_existing_cache(project):
                self.progress.emit("Using existing project database...")
                self.finished.emit(project)
                return
            self.progress.emit("Reading client version...")
            _ = detect_client_version(project.game_root)
            self.progress.emit("Extracting base locale data...")
            base_result = build_versioned_base(project, force=False)
            base_dir = Path(base_result["base_dir"])
            version = str(base_result["version"])
            self.progress.emit("Building project database...")
            rebuild_cache(
                project.db_path, base_dir, version, project.target_lang, project.game_root
            )
            self.finished.emit(project)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _has_existing_cache(self, project: ProjectPaths) -> bool:
        if not project.db_path.is_file():
            return False
        conn = sqlite3.connect(str(project.db_path))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='strings'"
            ).fetchone()
            if row is None:
                return False
            count_row = conn.execute("SELECT COUNT(*) FROM strings").fetchone()
            count = int(count_row[0] if count_row else 0)
            return count > 0
        finally:
            conn.close()


class ExportWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        project: ProjectPaths,
        output_dir: Path,
        overlay_rows: dict[str, dict[str, str]],
    ) -> None:
        super().__init__()
        self.project = project
        self.output_dir = output_dir
        self.overlay_rows = overlay_rows

    def run(self) -> None:
        try:
            self.progress.emit("Building translation release...")
            result = build_translation_release(
                self.project,
                self.output_dir,
                self.overlay_rows,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class QAWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        db_path: Path,
        overlay_rows: dict[str, dict[str, str]],
        target_lang: str,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.overlay_rows = overlay_rows
        self.target_lang = target_lang

    def run(self) -> None:
        try:
            self.progress.emit("Running QA...")
            result = run_qa(self.db_path, self.overlay_rows, self.target_lang)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, game_root: Path | None = None, target_lang: str | None = None) -> None:
        super().__init__()
        self.project: ProjectPaths | None = None
        self.conn = None
        self.repo = None
        self.model = None
        self.master_overlay_rows: dict[str, dict[str, str]] = {}
        self.mine_rows: dict[str, dict[str, str]] = {}
        self.master_overlay_path: Path | None = None
        self.current_id: str | None = None
        self._target_baseline = ""
        self._notes_baseline = ""
        self._current_cn = ""
        self._current_en = ""
        self._current_official = ""
        self._preview_row_ids: dict[int, str] = {}
        self._render_preview_source = "ours"
        self._pending_export_overlay: dict[str, dict[str, str]] = {}
        self._loading_row = False
        self._selection_snapshot: list[tuple[str, int]] = []
        self._project_thread: QThread | None = None
        self._project_worker: ProjectOpenWorker | None = None
        self._project_progress: QProgressDialog | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self._export_output_dir: Path | None = None
        self._qa_thread: QThread | None = None
        self._qa_worker: QAWorker | None = None
        self._qa_progress: QProgressDialog | None = None
        self._keep_qa_overview_on_row_sync = False
        self._deferred_panel_refresh_row_id: str | None = None
        self._qa_tab_needs_refresh = False

        self.setWindowTitle("WWM Translator")
        self.resize(1800, 1000)
        self._build_ui()
        self._setup_shortcuts()
        self._disable_editor()

        if game_root and target_lang:
            self._open_project(game_root, target_lang)
        else:
            if not self._restore_last_project():
                self.base_warning.setVisible(True)
                self.base_warning.setText(
                    "No project opened. Click 'Create DB' to choose game folder "
                    "and target language."
                )

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QTextEdit[readonlyField="true"] {
                background-color: #262626;
                color: #a9a9a9;
                border: 1px solid #3a3a3a;
            }
            QTextEdit[editableField="true"] {
                background-color: #1f1f1f;
                color: #f0f0f0;
                border: 1px solid #4a4a4a;
            }
            QLabel[warningBanner="true"] {
                background-color: #5e2222;
                color: #ffe8e8;
                border: 1px solid #8b2d2d;
                padding: 6px;
            }
            """
        )
        root = QWidget()
        layout = QVBoxLayout(root)
        self._build_menu()
        layout.addLayout(self._toolbar())

        self.base_warning = QLabel("")
        self.base_warning.setProperty("warningBanner", True)
        self.base_warning.setVisible(False)
        layout.addWidget(self.base_warning)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        left = QWidget()
        left_l = QVBoxLayout(left)
        editor_splitter = QSplitter(Qt.Orientation.Vertical)
        left_l.addWidget(editor_splitter, 1)

        self.table = QTableView()
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setMouseTracking(True)
        self.table.setItemDelegateForColumn(0, ActionCellDelegate(self.table))
        self.table.setItemDelegateForColumn(1, ActionCellDelegate(self.table))
        self.table.pressed.connect(self._capture_selection_snapshot)
        self.table.clicked.connect(self._on_row)
        editor_splitter.addWidget(self.table)

        editor_box = QWidget()
        editor_layout = QVBoxLayout(editor_box)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.cn = QTextEdit()
        self._setup_editor(self.cn, read_only=True)
        self.en = QTextEdit()
        self._setup_editor(self.en, read_only=True)
        self.target = QTextEdit()
        self._setup_editor(self.target, read_only=False)
        self.target_master = QTextEdit()
        self._setup_editor(self.target_master, read_only=True)
        self.target_official = QTextEdit()
        self._setup_editor(self.target_official, read_only=True)

        grid.addWidget(QLabel("CN"), 0, 0)
        grid.addWidget(QLabel("Target ours"), 0, 1)
        grid.addWidget(self.cn, 1, 0)
        grid.addWidget(self.target, 1, 1)
        grid.addWidget(QLabel("EN"), 2, 0)
        grid.addWidget(QLabel("Target master"), 2, 1)
        grid.addWidget(self.en, 3, 0)
        grid.addWidget(self.target_master, 3, 1)
        grid.addWidget(QLabel("Target official"), 4, 0, 1, 2)
        grid.addWidget(self.target_official, 5, 0, 1, 2)
        editor_layout.addLayout(grid)

        row_buttons = QHBoxLayout()
        btn_save = QPushButton("Save translation")
        btn_save.clicked.connect(self._save_translations)
        btn_save_master = QPushButton("Save master translation")
        btn_save_master.clicked.connect(self._save_master_translation)
        btn_apply = QPushButton("Apply to same source text")
        btn_apply.clicked.connect(self._apply_same_cn)
        self.btn_needs_context = QCheckBox("Needs Context")
        self.btn_needs_context.stateChanged.connect(self._toggle_needs_context)
        row_buttons.addWidget(btn_save)
        row_buttons.addWidget(btn_save_master)
        row_buttons.addWidget(btn_apply)
        row_buttons.addWidget(self.btn_needs_context)
        editor_layout.addLayout(row_buttons)
        editor_splitter.addWidget(editor_box)
        editor_splitter.setSizes([760, 320])
        splitter.addWidget(left)

        right = QWidget()
        right_l = QVBoxLayout(right)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tm_list = QListWidget()
        self.glossary_list = QListWidget()
        self.qa_tab = QWidget()
        qa_layout = QVBoxLayout(self.qa_tab)
        self.qa_show_all_btn = QPushButton("Show all errors")
        self.qa_show_all_btn.clicked.connect(self._show_qa_overview_panel)
        qa_layout.addWidget(self.qa_show_all_btn)
        self.qa_tree = QTreeWidget()
        self.qa_tree.setHeaderLabels(["Rule", "Details"])
        self.qa_tree.setColumnWidth(0, 360)
        self.qa_tree.itemClicked.connect(self._on_qa_item_click)
        qa_layout.addWidget(self.qa_tree, 1)
        self.same_source_list = QListWidget()
        self.same_source_list.itemClicked.connect(self._on_same_source_click)
        self.rendered_preview = QTextBrowser()
        self.render_preview_ours = QRadioButton("Our Translation")
        self.render_preview_official = QRadioButton("Official Target")
        self.render_preview_ours.setChecked(True)
        self.render_preview_ours.toggled.connect(self._refresh_rendered_preview)
        self.render_preview_official.toggled.connect(self._refresh_rendered_preview)
        rendered_tab = QWidget()
        rendered_layout = QVBoxLayout(rendered_tab)
        rendered_switch = QHBoxLayout()
        rendered_switch.addWidget(self.render_preview_ours)
        rendered_switch.addWidget(self.render_preview_official)
        rendered_layout.addLayout(rendered_switch)
        rendered_layout.addWidget(self.rendered_preview, 1)

        self.notes_tab = QTextEdit()
        self.notes_tab.setPlaceholderText("Row notes")
        self.tabs.addTab(self.tm_list, "TM")
        self.tabs.addTab(self.glossary_list, "Glossary")
        self.tabs.addTab(self.qa_tab, "QA")
        self.tabs.addTab(self.same_source_list, "Same Source")
        self.tabs.addTab(rendered_tab, "Rendered Preview")
        self.tabs.addTab(self.notes_tab, "Notes")
        right_l.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([1300, 500])

    def _setup_editor(self, editor: QTextEdit, read_only: bool) -> None:
        editor.setReadOnly(read_only)
        editor.setMaximumHeight(110)
        if read_only:
            editor.setProperty("readonlyField", True)
            editor.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByKeyboard
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            editor.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        else:
            editor.setProperty("editableField", True)
        editor._tag_highlighter = TagHighlighter(editor.document())

    def _build_menu(self) -> None:
        menu_bar: QMenuBar = self.menuBar()
        project_menu = menu_bar.addMenu("Project")
        translation_menu = menu_bar.addMenu("Translation")
        tools_menu = menu_bar.addMenu("Tools")
        export_menu = menu_bar.addMenu("Export")

        action_create_db = QAction("Create DB", self)
        action_create_db.triggered.connect(self._open_project_dialog)
        action_load_master = QAction("Load master translation", self)
        action_load_master.triggered.connect(self._load_master_overlay)
        action_load_mine = QAction("Load my translation", self)
        action_load_mine.triggered.connect(self._load_my_translation)
        action_load_glossary = QAction("Load glossary", self)
        action_load_glossary.triggered.connect(self._load_glossary)

        action_save_translation = QAction("Save translation", self)
        action_save_translation.triggered.connect(self._save_translations)
        action_save_master = QAction("Save master translation", self)
        action_save_master.triggered.connect(self._save_master_translation)

        action_run_qa = QAction("Run QA", self)
        action_run_qa.triggered.connect(self._run_qa)
        action_rebuild_tm = QAction("Rebuild translation memory", self)
        action_rebuild_tm.triggered.connect(self._rebuild_tm)

        action_export = QAction("Export translation", self)
        action_export.triggered.connect(self._export_release)

        project_menu.addActions(
            [
                action_create_db,
                action_load_master,
                action_load_mine,
                action_load_glossary,
            ]
        )
        translation_menu.addActions([action_save_translation, action_save_master])
        tools_menu.addActions([action_run_qa, action_rebuild_tm])
        export_menu.addAction(action_export)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_translations)
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, activated=self._approve_current_row)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self._reject_current_row)
        QShortcut(QKeySequence("Ctrl+Alt+N"), self, activated=self._toggle_needs_context_shortcut)

    def _toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("State"))
        self.state_filter = QComboBox()
        self.state_filter.addItems(
            [
                "",
                "new",
                "changed",
                "master",
                "approved",
                "rejected",
                "untranslated",
                "outdated",
                "official",
                "official_match",
            ]
        )
        self.state_filter.currentTextChanged.connect(self._apply_filters)
        bar.addWidget(self.state_filter)

        bar.addWidget(QLabel("Category"))
        self.category_filter = QComboBox()
        self.category_filter.addItems(
            ["", "notranslate", "skill", "weapon", "format", "dialog", "ui_label", "other"]
        )
        self.category_filter.currentTextChanged.connect(self._apply_filters)
        bar.addWidget(self.category_filter)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.returnPressed.connect(self._apply_filters)
        bar.addWidget(self.search, 1)

        self.issues_only = QCheckBox("Issues")
        self.issues_only.stateChanged.connect(self._apply_filters)
        bar.addWidget(self.issues_only)
        self.row_counter = QLabel("Rows: 0")
        bar.addWidget(self.row_counter)
        return bar

    def _apply_filters(self) -> None:
        if self.model is None:
            return
        self.model.set_query(
            QueryState(
                state=self.state_filter.currentText().strip(),
                category=self.category_filter.currentText().strip(),
                issues_only=self.issues_only.isChecked(),
                search=self.search.text().strip(),
            )
        )
        self._update_row_counter()

    def _update_row_counter(self) -> None:
        if self.model is None:
            self.row_counter.setText("Rows: 0")
            return
        self.row_counter.setText(f"Rows: {self.model.rowCount()}")

    def _persist_current_row(self) -> bool:
        if not self.current_id or self.repo is None:
            return False
        row = self.repo.get_row(self.current_id)
        if row is None:
            return False
        key = self.current_id.lower()
        target_text = self.target.toPlainText()
        notes_text = self.notes_tab.toPlainText()
        needs_context = "1" if self.btn_needs_context.isChecked() else "0"
        existing = self.mine_rows.get(key, {})
        old_snapshot = dict(existing)

        target_changed = target_text != self._target_baseline
        notes_changed = notes_text != self._notes_baseline
        needs_changed = (existing.get("needs_context", "0") == "1") != (needs_context == "1")
        if not target_changed and not notes_changed and not needs_changed:
            return False

        state = existing.get("state", "ours")
        if target_changed and state in {"approved", "rejected"}:
            state = "ours"

        self.mine_rows[key] = {
            "cn_hash": cn_hash(row["cn"]),
            "state": state,
            "target": target_text,
            "cn": row["cn"],
            "en": row["en"],
            "needs_context": needs_context,
            "notes": notes_text,
        }
        self._sync_repo_overlays(reload_model=False)
        if self.model is not None:
            self.model.refresh_row_by_id(key)
        changed = self.mine_rows.get(key, {}) != old_snapshot
        if changed and self.conn is not None and self.project is not None:
            check_row_into_db(
                self.conn,
                row["id"],
                self._effective_overlay(),
                self.project.target_lang,
            )
        self._target_baseline = target_text
        self._notes_baseline = notes_text
        self._refresh_rendered_preview()
        return changed

    def _on_row(self, index: QModelIndex | None = None) -> None:
        if self.model is None or self.repo is None:
            return
        idx = index if index is not None else self.table.currentIndex()
        if not idx.isValid():
            return
        row_id = self.model.row_id(idx.row())
        if not row_id:
            return
        if idx.column() == 0:
            self._mark_rows_from_selection(
                "approved",
                fallback_row_id=row_id,
                fallback_row=idx.row(),
            )
            return
        if idx.column() == 1:
            self._mark_rows_from_selection(
                "rejected",
                fallback_row_id=row_id,
                fallback_row=idx.row(),
            )
            return
        if self.current_id and self.current_id != row_id:
            self._persist_current_row()
        row = self.repo.get_row(row_id)
        if row is None:
            return
        self._fill_editor_row(row_id, row)
        self._refresh_panels(row_id, row["cn"], row["en"])

    def _fill_editor_row(self, row_id: str, row: dict[str, str]) -> None:
        self._loading_row = True
        self.current_id = row_id
        self.cn.setPlainText(row["cn"])
        self.en.setPlainText(row["en"])
        self.target_official.setPlainText(row["target_official"])
        self.target_master.setPlainText(row.get("target_master", ""))
        self.target.setPlainText(row["target"])
        mine_item = self.mine_rows.get((row_id or "").lower(), {})
        self.btn_needs_context.setChecked(mine_item.get("needs_context", "0") == "1")
        self.notes_tab.setPlainText(mine_item.get("notes", ""))
        self._target_baseline = row["target"]
        self._notes_baseline = mine_item.get("notes", "")
        self._current_cn = row["cn"]
        self._current_en = row["en"]
        self._current_official = row["target_official"]
        self._loading_row = False
        self._refresh_rendered_preview()

    def _mark_row(self, row_id: str, next_state: str, row_index: int) -> None:
        if self.repo is None or self.model is None:
            return
        if self.current_id:
            self._persist_current_row()
        row = self.repo.get_row(row_id)
        if row is None:
            return
        key = row_id.lower()
        current = self.mine_rows.get(key)
        if (
            next_state in {"approved", "rejected"}
            and not (row.get("target_master", "") or "").strip()
            and not (row.get("target", "") or "").strip()
        ):
            return
        toggled_state = "ours"
        if current is None or current.get("state", "ours") != next_state:
            toggled_state = next_state
        if current:
            target_text = current.get("target", row.get("target", ""))
            notes_text = current.get("notes", "")
            needs_context = current.get("needs_context", "0")
        else:
            target_text = row.get("target", "")
            notes_text = ""
            needs_context = "0"
        self.mine_rows[key] = {
            "cn_hash": cn_hash(row["cn"]),
            "state": toggled_state,
            "target": target_text,
            "cn": row["cn"],
            "en": row["en"],
            "notes": notes_text,
            "needs_context": needs_context,
        }
        self._sync_repo_overlays(reload_model=False)
        self.model.refresh_row(row_index)
        latest = self.repo.get_row(row_id)
        if latest is None:
            return
        self._fill_editor_row(row_id, latest)
        self._refresh_panels(row_id, latest["cn"], latest["en"])

    def _selected_rows(self) -> list[tuple[str, int]]:
        if self.model is None:
            return []
        indexes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        out: list[tuple[str, int]] = []
        for idx in indexes:
            row_id = self.model.row_id(idx.row())
            if row_id:
                out.append((row_id, idx.row()))
        return out

    def _capture_selection_snapshot(self, _index: QModelIndex) -> None:
        # Clicking an action cell can collapse selection before click handler runs.
        # Keep the pre-click selection so bulk approve/reject still works.
        self._selection_snapshot = self._selected_rows()

    def _mark_rows_from_selection(
        self,
        next_state: str,
        fallback_row_id: str,
        fallback_row: int,
    ) -> None:
        selected = self._selected_rows()
        if len(selected) <= 1 and len(self._selection_snapshot) > 1:
            selected = list(self._selection_snapshot)
        self._selection_snapshot = []
        if not selected:
            selected = [(fallback_row_id, fallback_row)]
        if len(selected) == 1:
            row_id, row_index = selected[0]
            self._mark_row(row_id, next_state, row_index)
            return

        if self.repo is None:
            return
        self._persist_current_row()
        actionable = 0
        for row_id, _row_index in selected:
            row = self.repo.get_row(row_id)
            if row is None:
                continue
            has_target = (row.get("target", "") or "").strip()
            has_master = (row.get("target_master", "") or "").strip()
            if not has_target and not has_master:
                continue
            actionable += 1
        if actionable <= 0:
            QMessageBox.information(self, "Review", "No rows eligible for this action.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm bulk review",
            f"Apply '{next_state}' to {actionable} visible selected rows?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        changed_rows = 0
        self.table.setUpdatesEnabled(False)
        try:
            for row_id, _row_index in selected:
                row = self.repo.get_row(row_id)
                if row is None:
                    continue
                has_target = (row.get("target", "") or "").strip()
                has_master = (row.get("target_master", "") or "").strip()
                if not has_target and not has_master:
                    continue
                key = row_id.lower()
                current = self.mine_rows.get(key)
                toggled_state = "ours"
                if current is None or current.get("state", "ours") != next_state:
                    toggled_state = next_state
                if current:
                    target_text = current.get("target", row.get("target", ""))
                    notes_text = current.get("notes", "")
                    needs_context = current.get("needs_context", "0")
                else:
                    target_text = row.get("target", "")
                    notes_text = ""
                    needs_context = "0"
                new_item = {
                    "cn_hash": cn_hash(row["cn"]),
                    "state": toggled_state,
                    "target": target_text,
                    "cn": row["cn"],
                    "en": row["en"],
                    "notes": notes_text,
                    "needs_context": needs_context,
                }
                if self.mine_rows.get(key) != new_item:
                    changed_rows += 1
                self.mine_rows[key] = new_item
        finally:
            self.table.setUpdatesEnabled(True)
        if changed_rows == 0:
            return
        self._sync_repo_overlays(reload_model=True)
        if self.current_id:
            latest = self.repo.get_row(self.current_id)
            if latest is not None:
                self._fill_editor_row(self.current_id, latest)
                self._refresh_panels(self.current_id, latest["cn"], latest["en"])

    def _refresh_panels(self, row_id: str, cn_text: str, en_text: str) -> None:
        if self.conn is None:
            return
        self.tm_list.clear()
        for item in fill_tm_panel(
            self.conn,
            cn_text,
            self.master_overlay_rows,
            self.mine_rows,
            row_id,
        ):
            self.tm_list.addItem(item)
        self.glossary_list.clear()
        for item in fill_glossary_panel(self.conn, cn_text, en_text, self.target.toPlainText()):
            self.glossary_list.addItem(item)
        if self._keep_qa_overview_on_row_sync:
            self._keep_qa_overview_on_row_sync = False
        else:
            self._fill_row_qa_panel(row_id)
        self.same_source_list.clear()
        self._preview_row_ids.clear()
        for index, (item, preview_row_id) in enumerate(fill_same_source_panel(self.conn, row_id)):
            self.same_source_list.addItem(item)
            self._preview_row_ids[index] = preview_row_id

    def _fill_row_qa_panel(self, row_id: str) -> int:
        self.qa_tree.clear()
        grouped: dict[str, dict[str, list[tuple[str, str, str]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for issue in fill_qa_panel(self.conn, row_id):
            rule = str(issue.get("rule", ""))
            severity = str(issue.get("severity", ""))
            detail = str(issue.get("detail", ""))
            detail_message = str(issue.get("detail_message", "") or detail)
            category = str(issue.get("category", "other"))
            grouped[category][rule].append((severity, detail, detail_message))

        total = 0
        for category in sorted(grouped):
            category_groups = grouped[category]
            category_total = sum(len(items) for items in category_groups.values())
            category_label = category.replace("_", " ").title()
            category_node = QTreeWidgetItem([f"{category_label} ({category_total})", ""])
            category_node.setExpanded(True)
            for rule in sorted(category_groups):
                issues = category_groups[rule]
                rule_node = QTreeWidgetItem([f"{qa_rule_title(rule)} ({len(issues)})", ""])
                rule_node.setExpanded(True)
                for severity, detail, detail_message in issues:
                    pretty_detail = detail_message
                    if detail and detail_message != detail:
                        pretty_detail = f"{detail} | {detail_message}"
                    child = QTreeWidgetItem(["", f"{severity} | {pretty_detail}"])
                    child.setData(0, Qt.ItemDataRole.UserRole, row_id)
                    rule_node.addChild(child)
                    total += 1
                category_node.addChild(rule_node)
            self.qa_tree.addTopLevelItem(category_node)
        return total

    def _show_qa_overview_panel(self) -> None:
        if self.conn is None:
            return
        self.tabs.setCurrentWidget(self.qa_tab)
        self.qa_tree.clear()
        for bucket in fill_qa_overview_panel(self.conn, per_rule_limit=300):
            rule = str(bucket.get("rule", ""))
            rule_title = str(bucket.get("rule_title", qa_rule_title(rule)))
            category = str(bucket.get("category", qa_rule_category(rule)))
            category_label = category.replace("_", " ").title()
            severity = str(bucket.get("severity", ""))
            total = int(bucket.get("total", 0) or 0)
            items = bucket.get("items", [])
            if not isinstance(items, list):
                items = []
            shown = len(items)
            suffix = f"{shown}/{total}" if shown < total else str(total)
            title = f"{severity} | {category_label} | {rule_title} ({suffix})"
            parent = QTreeWidgetItem([title, ""])
            parent.setExpanded(False)
            for issue_row_id, detail, detail_message in items:
                issue_row = str(issue_row_id)
                pretty_detail = str(detail_message or detail)
                if detail and detail_message and str(detail) != str(detail_message):
                    pretty_detail = f"{detail} | {detail_message}"
                child = QTreeWidgetItem([issue_row, pretty_detail])
                child.setData(0, Qt.ItemDataRole.UserRole, issue_row)
                parent.addChild(child)
            self.qa_tree.addTopLevelItem(parent)

    def _has_row_selection(self) -> bool:
        if self.model is None:
            return False
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return False
        return selection_model.hasSelection()

    def _refresh_rendered_preview(self) -> None:
        if self.current_id is None:
            self.rendered_preview.setHtml("")
            return
        source_text = self.target.toPlainText()
        self._render_preview_source = "ours"
        if self.render_preview_official.isChecked():
            source_text = self.target_official.toPlainText()
            self._render_preview_source = "official"
        html, warnings = render_preview_html(source_text)
        if warnings:
            warning_html = "<br/>".join(f"[warning] {msg}" for msg in warnings)
            html = html.replace("</body>", f"<hr/><div>{warning_html}</div></body>")
        self.rendered_preview.setHtml(html)

    def _on_same_source_click(self, item) -> None:
        if self.model is None:
            return
        row_index = self.same_source_list.row(item)
        target_row_id = self._preview_row_ids.get(row_index)
        if not target_row_id:
            return
        model_index = self.model.index_of(target_row_id)
        if model_index is None:
            QMessageBox.information(
                self,
                "Same Source",
                "Selected row is filtered out by current filters/search.",
            )
            return
        idx = self.model.index(model_index, 2)
        self.table.selectRow(model_index)
        self.table.scrollTo(idx)
        self._on_row(idx)

    def _on_qa_item_click(self, item: QTreeWidgetItem, _column: int) -> None:
        if self.model is None or self.repo is None:
            return
        target_row_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not target_row_id:
            return
        target_row_id = str(target_row_id)
        self.model.set_qa_highlight_row(target_row_id)
        # Keep grouped overview visible when navigating from QA tree to table row.
        self._keep_qa_overview_on_row_sync = True
        model_index = self.model.index_of(target_row_id)
        if model_index is None:
            QMessageBox.information(
                self,
                "QA",
                "Issue row is filtered out by current filters/search.",
            )
            return
        idx = self.model.index(model_index, 2)
        self.table.selectRow(model_index)
        self.table.scrollTo(idx)
        if self.current_id and self.current_id != target_row_id:
            self._persist_current_row()
        row = self.repo.get_row(target_row_id)
        if row is None:
            return
        self._fill_editor_row(target_row_id, row)
        self._deferred_panel_refresh_row_id = target_row_id

    def _on_tab_changed(self, tab_index: int) -> None:
        qa_tab_index = self.tabs.indexOf(self.qa_tab)
        if tab_index != qa_tab_index:
            if (
                self._deferred_panel_refresh_row_id
                and self.repo is not None
                and self.current_id == self._deferred_panel_refresh_row_id
            ):
                row = self.repo.get_row(self.current_id)
                if row is not None:
                    self._refresh_panels(self.current_id, row["cn"], row["en"])
                self._deferred_panel_refresh_row_id = None
            return
        if self.conn is None:
            return
        if self._qa_tab_needs_refresh or self.qa_tree.topLevelItemCount() == 0:
            self._reload_qa_tab_view()

    def _approve_current_row(self) -> None:
        if self.current_id is None or self.model is None:
            return
        model_index = self.model.index_of(self.current_id)
        if model_index is None:
            return
        self._mark_row(self.current_id, "approved", model_index)

    def _reject_current_row(self) -> None:
        if self.current_id is None or self.model is None:
            return
        model_index = self.model.index_of(self.current_id)
        if model_index is None:
            return
        self._mark_row(self.current_id, "rejected", model_index)

    def _toggle_needs_context(self, _state: int) -> None:
        if not self.current_id or self._loading_row:
            return
        self._persist_current_row()

    def _toggle_needs_context_shortcut(self) -> None:
        self.btn_needs_context.setChecked(not self.btn_needs_context.isChecked())

    def _save_translations(self) -> None:
        if self.project is None:
            return
        self._persist_current_row()
        result = save_translation_rows(self.project.my_translation_path, self.mine_rows)
        if self.current_id:
            self._on_row()
        QMessageBox.information(self, "Translation", f"Saved rows: {result['rows']}")

    def _save_master_translation(self) -> None:
        if self.project is None:
            return
        self._persist_current_row()
        default_master = self.project.project_dir / "master_translation.tsv"
        output_path = self.master_overlay_path or default_master
        merged = merge_master_rows(self.master_overlay_rows, self.mine_rows)
        save_overlay(output_path, merged)

        accepted = {k: v for k, v in self.mine_rows.items() if v.get("state", "") == "approved"}
        merged_updates = 0
        for row_id, item in accepted.items():
            old_target = self.master_overlay_rows.get(row_id, {}).get("target", "")
            if old_target != item.get("target", ""):
                merged_updates += 1

        self.master_overlay_path = output_path
        self.master_overlay_rows = merged
        self._sync_repo_overlays(reload_model=True)
        if self.current_id:
            self._on_row()
        QMessageBox.information(
            self,
            "Master translation",
            (
                f"Saved rows: {len(merged)}\n"
                f"Accepted updates applied: {merged_updates}\n"
                f"Output: {output_path}"
            ),
        )

    def _apply_same_cn(self) -> None:
        if not self.current_id or self.repo is None or self.conn is None or self.project is None:
            return
        self._persist_current_row()
        row = self.repo.get_row(self.current_id)
        if row is None:
            return
        updated = 0
        unchanged = 0
        auto_approved = 0
        official_match = 0
        target_text = self.target.toPlainText()
        target_cn = row["cn"]
        batch = self.conn.execute(
            "SELECT id, cn, en, target_official FROM strings WHERE cn = ?", (target_cn,)
        ).fetchall()
        for item in batch:
            row_id = (item["id"] or "").lower()
            current = self.mine_rows.get(row_id, {})
            current_target = current.get("target", "")
            if current_target == target_text:
                unchanged += 1
                continue
            state = current.get("state", "ours")
            if state in {"approved", "rejected"}:
                state = "ours"
            master_target = self.master_overlay_rows.get(row_id, {}).get("target", "")
            if target_text.strip() and target_text.strip() == (master_target or "").strip():
                state = "approved"
                auto_approved += 1
            elif (
                target_text.strip()
                and target_text.strip() == (item["target_official"] or "").strip()
                and target_text.strip() != (master_target or "").strip()
            ):
                official_match += 1
            self.mine_rows[row_id] = {
                "cn_hash": cn_hash(item["cn"] or ""),
                "state": state,
                "target": target_text,
                "cn": item["cn"] or "",
                "en": item["en"] or "",
                "needs_context": current.get("needs_context", "0"),
                "notes": current.get("notes", ""),
            }
            updated += 1
        self._sync_repo_overlays(reload_model=True)
        self._on_row()
        QMessageBox.information(
            self,
            "Propagate",
            (
                f"Updated: {updated}\n"
                f"Unchanged: {unchanged}\n"
                f"Auto-approved: {auto_approved}\n"
                f"Official match: {official_match}"
            ),
        )

    def _load_master_overlay(self) -> None:
        if self.project is None:
            QMessageBox.warning(self, "Project", "Create DB first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open master translation TSV", str(self.project.project_dir), "*.tsv"
        )
        if not path:
            return
        self.master_overlay_path = Path(path)
        self.master_overlay_rows = normalize_master_rows(load_overlay(self.master_overlay_path))
        self._sync_repo_overlays(reload_model=True)
        if self.current_id:
            self._on_row()
        QMessageBox.information(
            self, "Master translation", f"Loaded rows: {len(self.master_overlay_rows)}"
        )

    def _load_my_translation(self) -> None:
        if self.project is None:
            QMessageBox.warning(self, "Project", "Create DB first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open my translation TSV", str(self.project.project_dir), "*.tsv"
        )
        if not path:
            return
        self.mine_rows = load_translation_rows(Path(path))
        self._sync_repo_overlays(reload_model=True)
        if self.current_id:
            self._on_row()
        QMessageBox.information(self, "My translation", f"Loaded rows: {len(self.mine_rows)}")

    def _run_qa(self) -> None:
        if self.project is None:
            return
        if self._qa_thread is not None:
            QMessageBox.information(self, "QA", "QA is already in progress.")
            return
        self._persist_current_row()
        self._qa_progress = QProgressDialog("Running QA...", "", 0, 0, self)
        self._qa_progress.setWindowTitle("Please wait")
        self._qa_progress.setCancelButton(None)
        self._qa_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._qa_progress.setMinimumDuration(0)
        self._qa_progress.show()

        self._qa_thread = QThread(self)
        self._qa_worker = QAWorker(
            self.project.db_path,
            self._effective_overlay(),
            self.project.target_lang,
        )
        self._qa_worker.moveToThread(self._qa_thread)
        self._qa_thread.started.connect(self._qa_worker.run)
        self._qa_worker.progress.connect(self._on_qa_progress)
        self._qa_worker.finished.connect(self._on_qa_ready)
        self._qa_worker.failed.connect(self._on_qa_failed)
        self._qa_worker.finished.connect(self._qa_thread.quit)
        self._qa_worker.failed.connect(self._qa_thread.quit)
        self._qa_thread.finished.connect(self._cleanup_qa_runner)
        self._qa_thread.start()

    def _on_qa_progress(self, message: str) -> None:
        if self._qa_progress is not None:
            self._qa_progress.setLabelText(message)

    def _on_qa_failed(self, message: str) -> None:
        if self._qa_progress is not None:
            self._qa_progress.close()
        QMessageBox.critical(self, "QA failed", message)

    def _on_qa_ready(self, result_obj: object) -> None:
        if self._qa_progress is not None:
            self._qa_progress.close()
        if not isinstance(result_obj, dict):
            QMessageBox.critical(self, "QA failed", "Invalid QA result returned.")
            return
        self._qa_tab_needs_refresh = True
        QMessageBox.information(
            self,
            "QA",
            f"Rows: {result_obj.get('rows', 0)}\nIssues: {result_obj.get('issues', 0)}",
        )
        qa_tab_index = self.tabs.indexOf(self.qa_tab)
        if self.tabs.currentIndex() == qa_tab_index:
            self._reload_qa_tab_view()

    def _qa_issue_count(self) -> int:
        total = 0
        for idx in range(self.qa_tree.topLevelItemCount()):
            parent = self.qa_tree.topLevelItem(idx)
            total += parent.childCount()
        return total

    def _reload_qa_tab_view(self) -> None:
        if self.conn is None:
            return
        self.qa_tree.clear()
        self._qa_tab_needs_refresh = False
        if self._has_row_selection() and self.current_id:
            row_issues = self._fill_row_qa_panel(self.current_id)
            if row_issues > 0:
                return
        self._show_qa_overview_panel()

    def _cleanup_qa_runner(self) -> None:
        if self._qa_worker is not None:
            self._qa_worker.deleteLater()
        if self._qa_thread is not None:
            self._qa_thread.deleteLater()
        self._qa_worker = None
        self._qa_thread = None
        self._qa_progress = None

    def _rebuild_tm(self) -> None:
        if self.conn is None:
            return
        try:
            result = rebuild_tm(self.conn, self.master_overlay_rows)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "TM rebuild failed", str(exc))
            return
        QMessageBox.information(
            self,
            "TM",
            (
                f"Pairs: {result['pairs']}\n"
                f"Rows: {result['rows']}\n"
                f"Master trusted pairs: {result.get('master_pairs', 0)}"
            ),
        )

    def _load_glossary(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open glossary TSV", str(self.project.project_dir), "*.tsv"
        )
        if not path:
            return
        result = load_glossary_to_db(self.project.db_path, Path(path))
        if self.current_id:
            self._on_row()
        QMessageBox.information(self, "Glossary", f"Loaded rows: {result['rows']}")

    def _sync_repo_overlays(self, reload_model: bool) -> None:
        if self.repo is None:
            return
        mine_overlay = {
            row_id: {
                "cn_hash": item.get("cn_hash", ""),
                "state": item.get("state", "ours"),
                "target": item.get("target", ""),
                "notes": item.get("notes", ""),
                "needs_context": item.get("needs_context", "0"),
                "cn": item.get("cn", ""),
                "en": item.get("en", ""),
            }
            for row_id, item in self.mine_rows.items()
        }
        self.repo.set_overlays(self.master_overlay_rows, mine_overlay)
        if reload_model and self.model is not None:
            self.model.reload()
        self._update_row_counter()

    def _refresh_base_warning(self) -> None:
        if self.project is None:
            self.base_warning.setVisible(False)
            self.base_warning.setText("")
            return
        warning = ""
        try:
            client_version = detect_client_version(self.project.game_root)
            meta = load_project_meta(self.project)
            base_version = str(meta.get("version", "")).strip()
            if base_version and base_version != client_version:
                warning = (
                    f"Client version {client_version} differs from extracted base {base_version}. "
                    "Re-open project and re-extract base."
                )
        except Exception:
            warning = ""
        self.base_warning.setVisible(bool(warning))
        self.base_warning.setText(warning)

    def _open_project_dialog(self) -> None:
        game_dir = QFileDialog.getExistingDirectory(self, "Select game root folder")
        if not game_dir:
            return
        langs = [lang for lang in LANG_CODES.keys() if lang != "zh_cn"]
        target_lang, ok = QInputDialog.getItem(
            self, "Target language", "Choose target language", langs, 0, False
        )
        if not ok or not target_lang:
            return
        self._open_project(Path(game_dir), target_lang)

    def _open_project(self, game_root: Path, target_lang: str) -> None:
        if self._project_thread is not None:
            QMessageBox.information(self, "Project", "Project loading is already in progress.")
            return
        self._disable_editor()
        self._project_progress = QProgressDialog("Preparing project...", "", 0, 0, self)
        self._project_progress.setWindowTitle("Please wait")
        self._project_progress.setCancelButton(None)
        self._project_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._project_progress.setMinimumDuration(0)
        self._project_progress.show()

        self._project_thread = QThread(self)
        self._project_worker = ProjectOpenWorker(game_root, target_lang)
        self._project_worker.moveToThread(self._project_thread)
        self._project_thread.started.connect(self._project_worker.run)
        self._project_worker.progress.connect(self._on_project_progress)
        self._project_worker.finished.connect(self._on_project_ready)
        self._project_worker.failed.connect(self._on_project_failed)
        self._project_worker.finished.connect(self._project_thread.quit)
        self._project_worker.failed.connect(self._project_thread.quit)
        self._project_thread.finished.connect(self._cleanup_project_loader)
        self._project_thread.start()

    def _restore_last_project(self) -> bool:
        recents = load_recent_projects()
        if not recents:
            return False
        recent = recents[0]
        try:
            project = open_project(recent.game_root, recent.target_lang)
            if not project.db_path.is_file():
                return False
            self._attach_project(project)
            return True
        except Exception:
            return False

    def _on_project_progress(self, message: str) -> None:
        if self._project_progress is not None:
            self._project_progress.setLabelText(message)

    def _on_project_failed(self, message: str) -> None:
        if self._project_progress is not None:
            self._project_progress.close()
        QMessageBox.critical(self, "Project open failed", message)

    def _on_project_ready(self, project_obj: object) -> None:
        project = project_obj
        if not isinstance(project, ProjectPaths):
            if self._project_progress is not None:
                self._project_progress.close()
            QMessageBox.critical(self, "Project open failed", "Invalid project data returned.")
            return

        self._attach_project(project)
        if self._project_progress is not None:
            self._project_progress.close()

    def _attach_project(self, project: ProjectPaths) -> None:
        if self.conn is not None:
            self.conn.close()

        self.project = project
        self.conn = open_db(project.db_path, ensure=True)
        self.repo = StringsRepository(self.conn)
        self.model = StringsTableModel(self.repo)
        self.table.setModel(self.model)
        self.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(1, 34)
        self.master_overlay_rows = {}
        self.master_overlay_path = None
        self.mine_rows = load_translation_rows(project.my_translation_path)
        self._sync_repo_overlays(reload_model=False)
        self._enable_editor()
        self._refresh_base_warning()
        self._update_row_counter()
        self.setWindowTitle(f"WWM Translator | {project.game_root.name} | {project.target_lang}")

    def _cleanup_project_loader(self) -> None:
        if self._project_worker is not None:
            self._project_worker.deleteLater()
        if self._project_thread is not None:
            self._project_thread.deleteLater()
        self._project_worker = None
        self._project_thread = None
        self._project_progress = None

    def _effective_overlay(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for row_id, item in self.master_overlay_rows.items():
            out[row_id] = {
                "cn_hash": item.get("cn_hash", ""),
                "state": item.get("state", "ours"),
                "target": item.get("target", ""),
            }
        for row_id, item in self.mine_rows.items():
            if item.get("state", "ours") == "rejected":
                continue
            out[row_id] = {
                "cn_hash": item.get("cn_hash", ""),
                "state": item.get("state", "ours"),
                "target": item.get("target", ""),
            }
        return out

    def _effective_export_overlay(self) -> dict[str, dict[str, str]]:
        # Final export uses only official target + saved master overrides.
        return {
            row_id: {
                "cn_hash": item.get("cn_hash", ""),
                "state": item.get("state", "ours"),
                "target": item.get("target", ""),
            }
            for row_id, item in self.master_overlay_rows.items()
        }

    def _export_release(self) -> None:
        if self.project is None:
            return
        if self._export_thread is not None:
            QMessageBox.information(self, "Export", "Export is already in progress.")
            return
        self._persist_current_row()
        output_dir = Path(sys.executable).resolve().parent / "export"
        overlay_rows = self._effective_export_overlay()
        self._pending_export_overlay = overlay_rows

        if self.conn is None:
            return
        final_map, source_map, stats = self._build_final_export_map(overlay_rows)
        qa_result = run_qa_on_map(
            self.conn,
            final_map,
            self.project.target_lang,
            source_map=source_map,
        )
        if int(qa_result.get("critical", 0)) > 0:
            critical_items = qa_result.get("critical_items", [])
            source_critical = {"master": 0, "official": 0, "empty": 0, "unknown": 0}
            for _row_id, _rule, _severity, _detail, source in critical_items:
                source_critical[source] = source_critical.get(source, 0) + 1
            preview = "\n".join(
                (
                    f"{row_id} | {qa_rule_title(rule)} | "
                    f"{qa_detail_message(detail)} | source={source.upper()}"
                )
                for row_id, rule, _severity, detail, source in critical_items[:20]
            )
            reply = QMessageBox.question(
                self,
                "Critical QA issues before export",
                (
                    f"Critical issues: {qa_result['critical']}\n"
                    f"Master: {source_critical.get('master', 0)} | "
                    f"Official: {source_critical.get('official', 0)} | "
                    f"Empty: {source_critical.get('empty', 0)}\n"
                    "Top issues:\n"
                    f"{preview}\n\n"
                    "Export anyway?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        unsaved_approved = [
            row_id
            for row_id, item in self.mine_rows.items()
            if item.get("state", "") == "approved" and row_id not in overlay_rows
        ]
        if unsaved_approved:
            QMessageBox.information(
                self,
                "Export warning",
                (
                    f"Approved but not yet saved to master: {len(unsaved_approved)}\n"
                    "Use Save master translation to include them in export."
                ),
            )
        self._export_output_dir = output_dir

        self._export_progress = QProgressDialog("Exporting translation...", "", 0, 0, self)
        self._export_progress.setWindowTitle("Please wait")
        self._export_progress.setCancelButton(None)
        self._export_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._export_progress.setMinimumDuration(0)
        self._export_progress.show()

        self._export_thread = QThread(self)
        self._export_worker = ExportWorker(self.project, output_dir, overlay_rows)
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_ready)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_worker.failed.connect(self._export_thread.quit)
        self._export_thread.finished.connect(self._cleanup_export_loader)
        self._export_thread.start()

    def _build_final_export_map(
        self,
        overlay_rows: dict[str, dict[str, str]],
    ) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
        if self.conn is None:
            return {}, {}, {"rows": 0, "official": 0, "master": 0, "empty": 0}
        rows = self.conn.execute("SELECT id, target_official FROM strings").fetchall()
        final_map: dict[str, str] = {}
        source_map: dict[str, str] = {}
        official_count = 0
        master_count = 0
        empty_count = 0
        for row in rows:
            row_id = (row["id"] or "").lower()
            master_target = (overlay_rows.get(row_id, {}).get("target", "") or "").strip()
            official_target = (row["target_official"] or "").strip()
            if master_target:
                final_map[row_id] = master_target
                source_map[row_id] = "master"
                master_count += 1
            elif official_target:
                final_map[row_id] = official_target
                source_map[row_id] = "official"
                official_count += 1
            else:
                final_map[row_id] = ""
                source_map[row_id] = "empty"
                empty_count += 1
        return final_map, source_map, {
            "rows": len(rows),
            "official": official_count,
            "master": master_count,
            "empty": empty_count,
        }

    def _on_export_progress(self, message: str) -> None:
        if self._export_progress is not None:
            self._export_progress.setLabelText(message)

    def _on_export_failed(self, message: str) -> None:
        if self._export_progress is not None:
            self._export_progress.close()
        QMessageBox.critical(self, "Export failed", message)

    def _on_export_ready(self, result_obj: object) -> None:
        if self._export_progress is not None:
            self._export_progress.close()
        if not isinstance(result_obj, dict):
            QMessageBox.critical(self, "Export failed", "Invalid export result returned.")
            return
        output_dir = self._export_output_dir or Path("")
        built_files = result_obj.get("built_files", [])
        archive = result_obj.get("zip", "")
        built_count = len(built_files) if isinstance(built_files, list) else 0
        _final_map, _source_map, stats = self._build_final_export_map(self._pending_export_overlay)
        message = (
            f"Built files: {built_count}\n"
            f"Archive: {archive}\n"
            f"Output: {output_dir}\n"
            f"Rows total: {stats['rows']}\n"
            f"From official: {stats['official']}\n"
            f"Master overrides: {stats['master']}\n"
            f"Empty rows: {stats['empty']}"
        )
        QMessageBox.information(self, "Export finished", message)

    def _cleanup_export_loader(self) -> None:
        if self._export_worker is not None:
            self._export_worker.deleteLater()
        if self._export_thread is not None:
            self._export_thread.deleteLater()
        self._export_worker = None
        self._export_thread = None
        self._export_progress = None
        self._export_output_dir = None
        self._pending_export_overlay = {}

    def _disable_editor(self) -> None:
        self.table.setEnabled(False)
        self.cn.setEnabled(False)
        self.en.setEnabled(False)
        self.target.setEnabled(False)
        self.target_master.setEnabled(False)
        self.target_official.setEnabled(False)
        self.notes_tab.setEnabled(False)
        self.btn_needs_context.setEnabled(False)
        self.same_source_list.setEnabled(False)
        self.rendered_preview.setEnabled(False)

    def _enable_editor(self) -> None:
        self.table.setEnabled(True)
        self.cn.setEnabled(True)
        self.en.setEnabled(True)
        self.target.setEnabled(True)
        self.target_master.setEnabled(True)
        self.target_official.setEnabled(True)
        self.notes_tab.setEnabled(True)
        self.btn_needs_context.setEnabled(True)
        self.same_source_list.setEnabled(True)
        self.rendered_preview.setEnabled(True)


def main() -> int:
    parser = argparse.ArgumentParser(description="WWM Translator GUI")
    parser.add_argument("--game-root", default="")
    parser.add_argument("--target-lang", default="")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    game_root = Path(args.game_root).resolve() if args.game_root else None
    target_lang = args.target_lang.strip().lower() or None
    window = MainWindow(game_root, target_lang)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
