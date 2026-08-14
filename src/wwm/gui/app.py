from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QRegularExpression, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
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
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..base import build_versioned_base
from ..build import build_translation_release
from ..db import open_db, rebuild_cache
from ..glossary import export_glossary_from_db, load_glossary_to_db
from ..overlay import cn_hash, load_overlay, load_translation_rows, save_translation_rows
from ..project import (
    LANG_CODES,
    ProjectPaths,
    load_project_meta,
    load_recent_projects,
    open_project,
)
from ..qa import run_qa
from ..tm import rebuild_tm
from ..version import detect_client_version
from .models import QueryState, StringsRepository, StringsTableModel
from .panels import fill_glossary_panel, fill_preview_panel, fill_qa_panel, fill_tm_panel


class TagHighlighter(QSyntaxHighlighter):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        game_tag = QTextCharFormat()
        game_tag.setForeground(QColor("#F4D35E"))
        game_tag.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r"#[A-Za-z][^#\n]{0,200}#(?:[A-Za-z]|$)"), game_tag))

        placeholder = QTextCharFormat()
        placeholder.setForeground(QColor("#7BDFF2"))
        placeholder.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r"\{[^{}\n]{1,120}\}"), placeholder))

        xml_like = QTextCharFormat()
        xml_like.setForeground(QColor("#B8F2E6"))
        self.rules.append((QRegularExpression(r"<[^<>\n]{1,200}>"), xml_like))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for regex, fmt in self.rules:
            it = regex.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


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
        self._project_thread: QThread | None = None
        self._project_worker: ProjectOpenWorker | None = None
        self._project_progress: QProgressDialog | None = None

        self.setWindowTitle("WWM Translator")
        self.resize(1800, 1000)
        self._build_ui()
        self._disable_editor()

        if game_root and target_lang:
            self._open_project(game_root, target_lang)
        else:
            if not self._restore_last_project():
                self.base_warning.setVisible(True)
                self.base_warning.setText(
                    "No project opened. Click 'Open project' to choose game folder "
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
        self.table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
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
        btn_save.clicked.connect(self._save_row)
        btn_apply = QPushButton("Apply to same CN")
        btn_apply.clicked.connect(self._apply_same_cn)
        row_buttons.addWidget(btn_save)
        row_buttons.addWidget(btn_apply)
        editor_layout.addLayout(row_buttons)
        editor_splitter.addWidget(editor_box)
        editor_splitter.setSizes([760, 320])
        splitter.addWidget(left)

        right = QWidget()
        right_l = QVBoxLayout(right)
        self.tabs = QTabWidget()
        self.tm_list = QListWidget()
        self.glossary_list = QListWidget()
        self.qa_list = QListWidget()
        self.preview_list = QListWidget()
        self.tabs.addTab(self.tm_list, "TM")
        self.tabs.addTab(self.glossary_list, "Glossary")
        self.tabs.addTab(self.qa_list, "QA")
        self.tabs.addTab(self.preview_list, "Preview")
        right_l.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([1300, 500])

    def _setup_editor(self, editor: QTextEdit, read_only: bool) -> None:
        editor.setReadOnly(read_only)
        editor.setMaximumHeight(110)
        if read_only:
            editor.setProperty("readonlyField", True)
            editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        else:
            editor.setProperty("editableField", True)
        editor._tag_highlighter = TagHighlighter(editor.document())

    def _toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("State"))
        self.state_filter = QComboBox()
        self.state_filter.addItems(
            ["", "new", "changed", "master", "untranslated", "outdated", "official"]
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
        self.search.setPlaceholderText("FTS5 query")
        self.search.returnPressed.connect(self._apply_filters)
        bar.addWidget(self.search, 1)

        self.issues_only = QCheckBox("Issues")
        self.issues_only.stateChanged.connect(self._apply_filters)
        bar.addWidget(self.issues_only)

        btn_open_project = QPushButton("Open project")
        btn_open_project.clicked.connect(self._open_project_dialog)
        btn_load_master = QPushButton("Load master translation")
        btn_load_master.clicked.connect(self._load_master_overlay)
        btn_load_glossary = QPushButton("Load glossary")
        btn_load_glossary.clicked.connect(self._load_glossary)
        btn_save_glossary = QPushButton("Save glossary")
        btn_save_glossary.clicked.connect(self._save_glossary)
        btn_export = QPushButton("Export files")
        btn_export.clicked.connect(self._export_release)
        btn_qa = QPushButton("Run QA")
        btn_qa.clicked.connect(self._run_qa)
        btn_tm = QPushButton("Rebuild TM")
        btn_tm.clicked.connect(self._rebuild_tm)
        for button in (
            btn_open_project,
            btn_load_master,
            btn_load_glossary,
            btn_save_glossary,
            btn_export,
            btn_qa,
            btn_tm,
        ):
            bar.addWidget(button)
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

    def _on_row(self) -> None:
        if self.model is None or self.repo is None:
            return
        idx = self.table.currentIndex()
        row_id = self.model.row_id(idx.row())
        if not row_id:
            return
        self.current_id = row_id
        row = self.repo.get_row(row_id)
        if row is None:
            return
        self.cn.setPlainText(row["cn"])
        self.en.setPlainText(row["en"])
        self.target_official.setPlainText(row["target_official"])
        self.target_master.setPlainText(row.get("target_master", ""))
        self.target.setPlainText(row["target"])
        self._refresh_panels(row_id, row["cn"], row["en"])

    def _refresh_panels(self, row_id: str, cn_text: str, en_text: str) -> None:
        if self.conn is None:
            return
        self.tm_list.clear()
        for item in fill_tm_panel(self.conn, cn_text):
            self.tm_list.addItem(item)
        self.glossary_list.clear()
        for item in fill_glossary_panel(self.conn, cn_text, en_text):
            self.glossary_list.addItem(item)
        self.qa_list.clear()
        for item in fill_qa_panel(self.conn, row_id):
            self.qa_list.addItem(item)
        self.preview_list.clear()
        for item in fill_preview_panel(self.conn, row_id):
            self.preview_list.addItem(item)

    def _save_row(self) -> None:
        if not self.current_id or self.repo is None or self.project is None:
            return
        row = self.repo.get_row(self.current_id)
        if row is None:
            return
        self.mine_rows[self.current_id] = {
            "cn_hash": cn_hash(row["cn"]),
            "state": "ours",
            "target": self.target.toPlainText(),
            "cn": row["cn"],
            "en": row["en"],
        }
        save_translation_rows(self.project.my_translation_path, self.mine_rows)
        self._sync_repo_overlays(reload_model=True)

    def _apply_same_cn(self) -> None:
        if not self.current_id or self.repo is None or self.conn is None or self.project is None:
            return
        row = self.repo.get_row(self.current_id)
        if row is None:
            return
        updated = 0
        target_text = self.target.toPlainText()
        target_cn = row["cn"]
        batch = self.conn.execute(
            "SELECT id, cn, en FROM strings WHERE cn = ?", (target_cn,)
        ).fetchall()
        for item in batch:
            row_id = item["id"]
            self.mine_rows[row_id] = {
                "cn_hash": cn_hash(item["cn"] or ""),
                "state": "ours",
                "target": target_text,
                "cn": item["cn"] or "",
                "en": item["en"] or "",
            }
            updated += 1
        save_translation_rows(self.project.my_translation_path, self.mine_rows)
        self._sync_repo_overlays(reload_model=True)
        QMessageBox.information(self, "Propagate", f"Updated rows: {updated}")

    def _load_master_overlay(self) -> None:
        if self.project is None:
            QMessageBox.warning(self, "Project", "Open a project first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open master translation TSV", str(self.project.project_dir), "*.tsv"
        )
        if not path:
            return
        self.master_overlay_path = Path(path)
        self.master_overlay_rows = load_overlay(self.master_overlay_path)
        self._sync_repo_overlays(reload_model=True)
        QMessageBox.information(
            self, "Master translation", f"Loaded rows: {len(self.master_overlay_rows)}"
        )

    def _run_qa(self) -> None:
        if self.project is None:
            return
        result = run_qa(self.project.db_path, self._effective_overlay(), self.project.target_lang)
        QMessageBox.information(self, "QA", f"Rows: {result['rows']}\nIssues: {result['issues']}")
        if self.current_id:
            self._on_row()

    def _rebuild_tm(self) -> None:
        if self.conn is None:
            return
        result = rebuild_tm(self.conn)
        QMessageBox.information(self, "TM", f"Pairs: {result['pairs']}\nRows: {result['rows']}")

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

    def _save_glossary(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save glossary TSV", str(self.project.project_dir / "glossary.tsv"), "*.tsv"
        )
        if not path:
            return
        result = export_glossary_from_db(self.project.db_path, Path(path))
        if self.current_id:
            self._on_row()
        QMessageBox.information(self, "Glossary", f"Saved rows: {result['rows']}")

    def _sync_repo_overlays(self, reload_model: bool) -> None:
        if self.repo is None:
            return
        mine_overlay = {
            row_id: {
                "cn_hash": item.get("cn_hash", ""),
                "state": item.get("state", "ours"),
                "target": item.get("target", ""),
            }
            for row_id, item in self.mine_rows.items()
        }
        self.repo.set_overlays(self.master_overlay_rows, mine_overlay)
        if reload_model and self.model is not None:
            self.model.reload()

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
        self.table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.master_overlay_rows = {}
        self.master_overlay_path = None
        self.mine_rows = load_translation_rows(project.my_translation_path)
        self._sync_repo_overlays(reload_model=False)
        self._enable_editor()
        self._refresh_base_warning()
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
            out[row_id] = {
                "cn_hash": item.get("cn_hash", ""),
                "state": item.get("state", "ours"),
                "target": item.get("target", ""),
            }
        return out

    def _export_release(self) -> None:
        if self.project is None:
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Choose export directory")
        if not output_dir:
            return
        try:
            result = build_translation_release(
                self.project,
                Path(output_dir),
                self._effective_overlay(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Export finished",
            f"Built files: {len(result['built_files'])}\nArchive: {result['zip']}",
        )

    def _disable_editor(self) -> None:
        self.table.setEnabled(False)
        self.cn.setEnabled(False)
        self.en.setEnabled(False)
        self.target.setEnabled(False)
        self.target_master.setEnabled(False)
        self.target_official.setEnabled(False)

    def _enable_editor(self) -> None:
        self.table.setEnabled(True)
        self.cn.setEnabled(True)
        self.en.setEnabled(True)
        self.target.setEnabled(True)
        self.target_master.setEnabled(True)
        self.target_official.setEnabled(True)


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
