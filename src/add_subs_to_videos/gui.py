from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import load_config, save_config
from .files import VIDEO_EXTENSIONS, find_videos
from .runtime_paths import ensure_bundled_ffmpeg_on_path
from .transcribe import process_directory

# QProgressBar values are integers, so the overall bar's range is scaled up by
# this factor to give smooth sub-file resolution when combining the count of
# completed videos with the current video's fractional progress.
_OVERALL_PROGRESS_SCALE = 1000

# palette(placeholder-text) is too light to read against the light color
# scheme forced in main(), so secondary/hint labels use this darker grey.
_MUTED_TEXT_STYLE = "color: #444444;"

# Number of rows shown in the "Files to process" table before scrolling.
_TABLE_VISIBLE_ROWS = 6


def _check_icon(color: QColor) -> QIcon:
    """Render a checkmark glyph as a QIcon in the given color."""
    size = 16
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([QPoint(3, 8), QPoint(7, 12), QPoint(13, 4)])
    painter.end()
    return QIcon(pixmap)

# whisper.cpp's canonical (code, English name) language table —
# mirrors Model.available_languages() / whisper_lang_str ordering.
_LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"), ("zh", "Chinese"), ("de", "German"), ("es", "Spanish"),
    ("ru", "Russian"), ("ko", "Korean"), ("fr", "French"), ("ja", "Japanese"),
    ("pt", "Portuguese"), ("tr", "Turkish"), ("pl", "Polish"), ("ca", "Catalan"),
    ("nl", "Dutch"), ("ar", "Arabic"), ("sv", "Swedish"), ("it", "Italian"),
    ("id", "Indonesian"), ("hi", "Hindi"), ("fi", "Finnish"), ("vi", "Vietnamese"),
    ("he", "Hebrew"), ("uk", "Ukrainian"), ("el", "Greek"), ("ms", "Malay"),
    ("cs", "Czech"), ("ro", "Romanian"), ("da", "Danish"), ("hu", "Hungarian"),
    ("ta", "Tamil"), ("no", "Norwegian"), ("th", "Thai"), ("ur", "Urdu"),
    ("hr", "Croatian"), ("bg", "Bulgarian"), ("lt", "Lithuanian"), ("la", "Latin"),
    ("mi", "Maori"), ("ml", "Malayalam"), ("cy", "Welsh"), ("sk", "Slovak"),
    ("te", "Telugu"), ("fa", "Persian"), ("lv", "Latvian"), ("bn", "Bengali"),
    ("sr", "Serbian"), ("az", "Azerbaijani"), ("sl", "Slovenian"), ("kn", "Kannada"),
    ("et", "Estonian"), ("mk", "Macedonian"), ("br", "Breton"), ("eu", "Basque"),
    ("is", "Icelandic"), ("hy", "Armenian"), ("ne", "Nepali"), ("mn", "Mongolian"),
    ("bs", "Bosnian"), ("kk", "Kazakh"), ("sq", "Albanian"), ("sw", "Swahili"),
    ("gl", "Galician"), ("mr", "Marathi"), ("pa", "Punjabi"), ("si", "Sinhala"),
    ("km", "Khmer"), ("sn", "Shona"), ("yo", "Yoruba"), ("so", "Somali"),
    ("af", "Afrikaans"), ("oc", "Occitan"), ("ka", "Georgian"), ("be", "Belarusian"),
    ("tg", "Tajik"), ("sd", "Sindhi"), ("gu", "Gujarati"), ("am", "Amharic"),
    ("yi", "Yiddish"), ("lo", "Lao"), ("uz", "Uzbek"), ("fo", "Faroese"),
    ("ht", "Haitian Creole"), ("ps", "Pashto"), ("tk", "Turkmen"), ("nn", "Nynorsk"),
    ("mt", "Maltese"), ("sa", "Sanskrit"), ("lb", "Luxembourgish"), ("my", "Myanmar"),
    ("bo", "Tibetan"), ("tl", "Tagalog"), ("mg", "Malagasy"), ("as", "Assamese"),
    ("tt", "Tatar"), ("haw", "Hawaiian"), ("ln", "Lingala"), ("ha", "Hausa"),
    ("ba", "Bashkir"), ("jw", "Javanese"), ("su", "Sundanese"), ("yue", "Cantonese"),
]


class _QtLogHandler(logging.Handler):
    def __init__(self, signal: Signal):
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        self._signal.emit(self.format(record))


class DropZone(QFrame):
    folder_dropped = Signal(Path)

    _STYLE = (
        "DropZone {"
        "  border: 1px solid palette(mid);"
        "  border-radius: 12px;"
        "  background: #E8F4FD;"
        "}"
        "DropZone:hover {"
        "  background: #D6EAFB;"
        "  border: 1px solid palette(highlight);"
        "}"
    )

    _SELECTED_STYLE = (
        "DropZone {"
        "  border: 2px solid #2E8B57;"
        "  border-radius: 12px;"
        "  background: #E8F4FD;"
        "}"
        "DropZone:hover {"
        "  background: #D6EAFB;"
        "  border: 2px solid #2E8B57;"
        "}"
    )

    _EMPTY_NAME = "Drop a folder or video file here"
    _EMPTY_HINT = "or click to browse"

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._STYLE)
        self._folder_path: Path | None = None

        layout = QGridLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(2)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)

        self._icon_label = QLabel("\U0001F5B1️ ➡️ \U0001F449")
        icon_font = QFont()
        icon_font.setPointSize(28)
        self._icon_label.setFont(icon_font)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label, 0, 0, 2, 1, Qt.AlignmentFlag.AlignCenter)

        self._selection_name_label = QLabel()
        selection_name_font = QFont()
        selection_name_font.setPointSize(18)
        selection_name_font.setBold(True)
        self._selection_name_label.setFont(selection_name_font)
        self._selection_name_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._selection_name_label.setVisible(False)

        self._name_label = QLabel(self._EMPTY_NAME)
        name_font = QFont()
        name_font.setPointSize(14)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.addWidget(self._selection_name_label)
        title_layout.addWidget(self._name_label)
        layout.addWidget(title_box, 0, 1)

        self._selection_path_label = QLabel()
        selection_path_font = QFont()
        selection_path_font.setPointSize(11)
        self._selection_path_label.setFont(selection_path_font)
        self._selection_path_label.setStyleSheet(_MUTED_TEXT_STYLE)
        self._selection_path_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._selection_path_label.setVisible(False)

        self._path_label = QLabel(self._EMPTY_HINT)
        path_font = QFont()
        path_font.setPointSize(11)
        self._path_label.setFont(path_font)
        self._path_label.setStyleSheet(_MUTED_TEXT_STYLE)
        self._path_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        subtitle_box = QWidget()
        subtitle_layout = QVBoxLayout(subtitle_box)
        subtitle_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_layout.setSpacing(0)
        subtitle_layout.addWidget(self._selection_path_label)
        subtitle_layout.addWidget(self._path_label)
        layout.addWidget(subtitle_box, 1, 1)

        self.set_folder(None)

    def _update_selection_path_label(self, text: str) -> None:
        metrics = QFontMetrics(self._selection_path_label.font())
        available = self.width() - self._icon_label.sizeHint().width() - 48
        elided = metrics.elidedText(
            text, Qt.TextElideMode.ElideMiddle, available if available > 0 else 320
        )
        self._selection_path_label.setText(elided)

    def set_folder(self, path: Path | None) -> None:
        self._folder_path = path
        if path is None:
            self.setStyleSheet(self._STYLE)
            self.setToolTip("")
            self._selection_name_label.setVisible(False)
            self._selection_name_label.setText("")
            self._selection_path_label.setVisible(False)
            self._selection_path_label.setText("")
            self._name_label.setVisible(True)
            self._path_label.setVisible(True)
        else:
            self.setStyleSheet(self._SELECTED_STYLE)
            if path.is_dir():
                icon, label = "\U0001F4C1", "Current folder"
            else:
                icon, label = "\U0001F3AC", "Current video"
            self._selection_name_label.setVisible(True)
            self._selection_name_label.setText(f"{label}: {icon} {path.name or str(path)}")
            self._selection_path_label.setVisible(True)
            self._update_selection_path_label(str(path))
            self._name_label.setVisible(False)
            self._path_label.setVisible(False)
            self.setToolTip(str(path))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._folder_path is not None:
            self._update_selection_path_label(str(self._folder_path))

    @staticmethod
    def _is_acceptable(path: Path) -> bool:
        return path.is_dir() or (path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and self._is_acceptable(Path(urls[0].toLocalFile())):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if self._is_acceptable(path):
                self.set_folder(path)
                self.folder_dropped.emit(path)

    def mousePressEvent(self, event) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            path = Path(folder)
            self.set_folder(path)
            self.folder_dropped.emit(path)


class _FileScanThread(QThread):
    files_ready = Signal(object)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:
        videos = [self._root] if self._root.is_file() else find_videos(self._root)
        self.files_ready.emit(videos)


class _WorkerThread(QThread):
    log_line = Signal(str)
    progress = Signal(object)
    file_progress = Signal(float)
    finished_run = Signal(bool)

    def __init__(
        self,
        root: Path,
        model_name: str,
        language: str | None,
        force: bool,
    ) -> None:
        super().__init__()
        self._root = root
        self._model_name = model_name
        self._language = language
        self._force = force
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        handler = _QtLogHandler(self.log_line)
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        saved_level = root_logger.level
        root_logger.setLevel(logging.INFO)

        class _StdoutCapture:
            def __init__(self, sig: Signal) -> None:
                self._sig = sig

            def write(self, text: str) -> None:
                if text.strip():
                    self._sig.emit(text.rstrip())

            def flush(self) -> None:
                pass

        saved_stdout = sys.stdout
        sys.stdout = _StdoutCapture(self.log_line)  # type: ignore[assignment]

        success = True
        try:
            process_directory(
                self._root,
                model_name=self._model_name,
                language=self._language,
                force=self._force,
                show_progress=False,
                cancel=self._cancel,
                on_progress=self.progress.emit,
                on_segment=self.log_line.emit,
                on_file_progress=self.file_progress.emit,
            )
        except SystemExit as exc:
            success = exc.code in (0, None)
        except Exception as exc:
            self.log_line.emit(f"ERROR    {exc}")
            success = False
        finally:
            sys.stdout = saved_stdout
            root_logger.removeHandler(handler)
            root_logger.setLevel(saved_level)

        self.finished_run.emit(success)


class MainWindow(QMainWindow):
    _RUN_BTN_STYLE = (
        "QPushButton:enabled {"
        "  background: #D6EAFB;"
        "  border: 1px solid #2E8B57;"
        "  border-radius: 6px;"
        "}"
        "QPushButton:disabled {"
        "  background: palette(button);"
        "  border: 1px solid palette(mid);"
        "  border-radius: 6px;"
        f"  {_MUTED_TEXT_STYLE}"
        "}"
    )
    _CANCEL_BTN_STYLE_IDLE = (
        "QPushButton {"
        "  background: palette(button);"
        "  border: 1px solid palette(mid);"
        "  border-radius: 6px;"
        "  color: palette(button-text);"
        "}"
    )
    _CANCEL_BTN_STYLE_ACTIVE = (
        "QPushButton {"
        "  background: palette(button);"
        "  border: 1px solid #C0392B;"
        "  border-radius: 6px;"
        "  color: #C0392B;"
        "}"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Add Subtitles to Videos")
        self.setMinimumWidth(560)
        self._folder: Path | None = None
        self._worker: _WorkerThread | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self._drop_zone = DropZone()
        self._drop_zone.folder_dropped.connect(self._on_folder_set)
        layout.addWidget(self._drop_zone)

        hint_row = QHBoxLayout()
        self._change_hint = QLabel("Drop a new folder or video file above, or click to change")
        self._change_hint.setStyleSheet(_MUTED_TEXT_STYLE)
        self._change_hint.setVisible(False)
        hint_row.addWidget(self._change_hint, 1)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_selection)
        self._clear_btn.setHidden(True)
        hint_row.addWidget(self._clear_btn)
        layout.addLayout(hint_row)

        self._tree_threads: list[_FileScanThread] = []
        self._tree_scan_token = 0
        self._file_row_by_path: dict[Path, int] = {}
        self._done_icon = _check_icon(QColor("#2e7d32"))
        self._skipped_icon = _check_icon(QColor("#9e9e9e"))

        self._tree_label = QLabel("Files to process")
        self._tree_label.setStyleSheet(_MUTED_TEXT_STYLE)
        self._tree_label.setVisible(False)
        layout.addWidget(self._tree_label)

        table_font = QFont("monospace")
        table_font.setPointSize(11)

        self._scan_message = QLabel()
        self._scan_message.setFont(table_font)
        self._scan_message.setStyleSheet(_MUTED_TEXT_STYLE)
        self._scan_message.setTextFormat(Qt.TextFormat.PlainText)
        self._scan_message.setVisible(False)
        layout.addWidget(self._scan_message)

        self._file_table = QTableWidget(0, 3)
        self._file_table.setHorizontalHeaderLabels(["Subdir", "File", "Status"])
        self._file_table.setFont(table_font)
        self._file_table.verticalHeader().setVisible(False)
        self._file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._file_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._file_table.setShowGrid(True)
        self._file_table.setAlternatingRowColors(True)
        header = self._file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._file_table.setStyleSheet(
            "QTableWidget {"
            "  border: 1px solid palette(mid);"
            "  gridline-color: palette(mid);"
            "  background: palette(base);"
            "}"
            "QTableWidget::item {"
            "  padding: 4px 6px;"
            "}"
            "QHeaderView::section {"
            "  background: palette(window);"
            "  border: none;"
            "  border-bottom: 1px solid palette(mid);"
            "  padding: 4px 6px;"
            "  font-weight: bold;"
            "}"
        )
        table_height = (
            header.sizeHint().height()
            + self._file_table.verticalHeader().defaultSectionSize() * _TABLE_VISIBLE_ROWS
        )
        self._file_table.setFixedHeight(table_height)
        self._file_table.setVisible(False)
        layout.addWidget(self._file_table)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        for m in ("tiny", "base", "small", "medium", "large-v3"):
            self._model_combo.addItem(m)
        self._model_combo.setCurrentText("medium")
        opts.addWidget(self._model_combo)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Language:"))
        self._lang_combo = QComboBox()
        self._lang_combo.addItem("Auto-detect", "")
        for code, name in _LANGUAGES:
            self._lang_combo.addItem(f"{name} ({code})", code)
        self._lang_combo.setMinimumWidth(160)
        opts.addWidget(self._lang_combo)
        opts.addSpacing(16)
        self._force_check = QCheckBox("Force re-run")
        opts.addWidget(self._force_check)
        opts.addStretch()
        layout.addLayout(opts)

        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run")
        self._run_btn.setEnabled(False)
        self._run_btn.setMinimumHeight(36)
        self._run_btn.setStyleSheet(self._RUN_BTN_STYLE)
        self._run_btn.clicked.connect(self._run)
        btn_row.addWidget(self._run_btn)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setMinimumHeight(36)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)
        self._cancel_btn.clicked.connect(self._cancel_run)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: palette(window-text);")
        status_row.addWidget(self._status_label, 1)
        self._counts_label = QLabel("")
        self._counts_label.setStyleSheet(_MUTED_TEXT_STYLE)
        status_row.addWidget(self._counts_label)
        layout.addLayout(status_row)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 1)
        self._overall_bar.setValue(0)
        self._overall_bar.setFormat("Ready")
        self._overall_bar.setMaximumHeight(22)
        layout.addWidget(self._overall_bar)

        self._file_bar = QProgressBar()
        self._file_bar.setRange(0, 100)
        self._file_bar.setValue(0)
        self._file_bar.setFormat("")
        self._file_bar.setMaximumHeight(22)
        layout.addWidget(self._file_bar)

        self._final_event = None
        self._current_video_index = 0
        self._current_total = 0

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        mono = QFont("monospace")
        mono.setPointSize(10)
        self._log.setFont(mono)
        layout.addWidget(self._log)

        self._load_prefs()

    def _load_prefs(self) -> None:
        cfg = load_config()
        self._model_combo.setCurrentText(cfg.get("model", "medium"))
        saved_lang = cfg.get("language", "")
        idx = self._lang_combo.findData(saved_lang)
        self._lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        directory = cfg.get("directory", "")
        if directory and Path(directory).exists():
            path = Path(directory)
            self._drop_zone.set_folder(path)
            self._folder = path
            self._run_btn.setEnabled(True)
            self._change_hint.setVisible(True)
            self._clear_btn.setHidden(False)
            self._start_tree_scan(path)

    def _save_prefs(self) -> None:
        save_config({
            "model": self._model_combo.currentText(),
            "language": self._lang_combo.currentData() or "",
            "directory": str(self._folder) if self._folder else "",
        })

    def closeEvent(self, event) -> None:
        self._save_prefs()
        super().closeEvent(event)

    def _on_folder_set(self, path: Path) -> None:
        self._folder = path
        self._run_btn.setEnabled(True)
        self._change_hint.setVisible(True)
        self._clear_btn.setHidden(False)
        self._save_prefs()
        self._start_tree_scan(path)

    def _clear_selection(self) -> None:
        self._folder = None
        self._drop_zone.set_folder(None)
        self._run_btn.setEnabled(False)
        self._clear_btn.setHidden(True)
        self._change_hint.setVisible(False)
        self._save_prefs()
        self._clear_tree_view()

    def _start_tree_scan(self, path: Path) -> None:
        self._tree_scan_token += 1
        token = self._tree_scan_token
        self._tree_label.setVisible(True)
        self._file_table.setVisible(False)
        self._file_table.setRowCount(0)
        self._file_row_by_path = {}
        self._scan_message.setText("Scanning…")
        self._scan_message.setVisible(True)
        thread = _FileScanThread(path)
        thread.files_ready.connect(lambda files, t=token: self._on_tree_ready(t, files))
        self._tree_threads.append(thread)
        thread.finished.connect(lambda t=thread: self._tree_threads.remove(t))
        thread.start()

    def _on_tree_ready(self, token: int, files: list[Path]) -> None:
        if token != self._tree_scan_token:
            return  # superseded by a newer selection
        try:
            if not files:
                self._file_table.setRowCount(0)
                self._file_row_by_path = {}
                self._file_table.setVisible(False)
                self._scan_message.setText("(no video files found)")
                self._scan_message.setVisible(True)
                return

            self._scan_message.setVisible(False)
            self._file_table.setRowCount(len(files))
            self._file_row_by_path = {}
            locations = []
            for path in files:
                location = ""
                if self._folder is not None and self._folder.is_dir():
                    try:
                        rel_parent = path.relative_to(self._folder).parent
                        location = "" if rel_parent == Path(".") else str(rel_parent)
                    except ValueError:
                        pass
                locations.append(location)
            for row, (path, location) in enumerate(zip(files, locations)):
                self._file_table.setItem(row, 0, QTableWidgetItem(location))
                self._file_table.setItem(row, 1, QTableWidgetItem(path.name))
                self._file_table.setItem(row, 2, QTableWidgetItem("Pending"))
                self._file_row_by_path[path] = row
            self._file_table.setColumnHidden(0, not any(locations))
            self._file_table.setVisible(True)
        except RuntimeError:
            pass  # widget was destroyed (e.g. window closed) before the scan finished

    def _clear_tree_view(self) -> None:
        self._tree_scan_token += 1
        self._file_row_by_path = {}
        self._tree_label.setVisible(False)
        self._scan_message.setVisible(False)
        self._scan_message.setText("")
        self._file_table.setVisible(False)
        self._file_table.setRowCount(0)

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def _update_file_status(self, video: Path | None, status: str) -> None:
        if video is None:
            return
        row = self._file_row_by_path.get(video)
        if row is None:
            return
        item = self._file_table.item(row, 2)
        if item is None:
            return
        if status == "Done":
            item.setIcon(self._done_icon)
            item.setText("")
            item.setToolTip("Done")
        elif status == "Skipped":
            item.setIcon(self._skipped_icon)
            item.setText("")
            item.setToolTip("Skipped")
        else:
            item.setIcon(QIcon())
            item.setText(status)
            item.setToolTip("")

    def _on_progress(self, event) -> None:
        name = event.video.name if event.video else ""
        scale = _OVERALL_PROGRESS_SCALE
        if event.stage == "start":
            self._log.clear()
            self._current_video_index = event.index
            self._current_total = event.total
            self._overall_bar.setRange(0, event.total * scale)
            self._overall_bar.setValue((event.index - 1) * scale)
            self._overall_bar.setFormat(f"{event.index} of {event.total} files")
            self._file_bar.setValue(0)
            self._file_bar.setFormat(f"{name} — %p%")
            self._status_label.setText(f"Processing {name}")
            self._update_file_status(event.video, "Processing")
        elif event.stage in ("done", "skip", "fail"):
            self._overall_bar.setRange(0, event.total * scale)
            self._overall_bar.setValue(event.index * scale)
            self._overall_bar.setFormat(f"{event.index} of {event.total} files")
            self._file_bar.setValue(100)
            verb = {"done": "Finished", "skip": "Skipped", "fail": "Failed"}[event.stage]
            self._status_label.setText(f"{verb} {name}")
            status = {"done": "Done", "skip": "Skipped", "fail": "Failed"}[event.stage]
            self._update_file_status(event.video, status)
        elif event.stage == "summary":
            self._overall_bar.setRange(0, event.total * scale)
            self._overall_bar.setValue(event.total * scale)
            self._file_bar.setValue(0)
            self._file_bar.setFormat("")
            self._final_event = event

        self._counts_label.setText(
            f"done {event.done} · skipped {event.skipped} · failed {event.failed}"
        )

    def _on_file_progress(self, fraction: float) -> None:
        self._file_bar.setValue(round(fraction * 100))
        if self._current_total:
            combined = (self._current_video_index - 1) + fraction
            self._overall_bar.setValue(round(combined * _OVERALL_PROGRESS_SCALE))

    def _cancel_run(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)
        self._status_label.setText("Cancelling…")

    def _run(self) -> None:
        if not self._folder:
            return
        self._log.clear()
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_ACTIVE)
        self._final_event = None
        self._current_video_index = 0
        self._current_total = 0
        self._overall_bar.setRange(0, 1)
        self._overall_bar.setValue(0)
        self._overall_bar.setFormat("Starting…")
        self._file_bar.setValue(0)
        self._file_bar.setFormat("")
        self._status_label.setText("Preparing…")
        self._counts_label.setText("")
        lang = self._lang_combo.currentData() or None
        self._worker = _WorkerThread(
            self._folder,
            self._model_combo.currentText(),
            lang,
            self._force_check.isChecked(),
        )
        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.finished_run.connect(self._on_done)
        self._worker.start()

    def _on_done(self, success: bool) -> None:
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)
        if self._final_event is not None:
            e = self._final_event
            mins, secs = divmod(int(e.elapsed or 0), 60)
            elapsed_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            self._status_label.setText("Done" if success else "Finished with errors")
            self._counts_label.setText(
                f"done {e.done} · skipped {e.skipped} · failed {e.failed} · {elapsed_str}"
            )
            self._overall_bar.setFormat(
                f"Complete — {e.done} transcribed, {e.skipped} skipped,"
                f" {e.failed} failed in {elapsed_str}"
            )
            self._file_bar.setValue(0)
            self._file_bar.setFormat("")
        else:
            label = "Cancelled" if not success else "Done"
            self._status_label.setText(label)
            self._overall_bar.setFormat(label)
            self._file_bar.setValue(0)
            self._file_bar.setFormat("")
        self._append_log("--- Done ---" if success else "--- Finished with errors ---")


def _dev_icon_path() -> Path | None:
    """Locate assets/icon.svg relative to a source checkout (e.g. `uv run`)."""
    candidate = Path(__file__).resolve().parents[2] / "assets" / "icon.svg"
    return candidate if candidate.is_file() else None


def main() -> None:
    ensure_bundled_ffmpeg_on_path()
    app = QApplication(sys.argv)
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    icon_path = _dev_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
