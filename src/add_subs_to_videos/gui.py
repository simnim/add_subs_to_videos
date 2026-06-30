from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import load_config, save_config
from .files import VIDEO_EXTENSIONS, find_videos, format_size_mb
from .runtime_paths import ensure_bundled_ffmpeg_on_path
from .transcribe import default_n_threads, is_model_downloaded, process_directory

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


def _download_icon(color: QColor) -> QIcon:
    """Render a download-arrow glyph (shaft + head) as a QIcon in the given color."""
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
    painter.drawLine(QPoint(8, 2), QPoint(8, 11))
    painter.drawPolyline([QPoint(4, 7), QPoint(8, 11), QPoint(12, 7)])
    painter.drawLine(QPoint(3, 14), QPoint(13, 14))
    painter.end()
    return QIcon(pixmap)


def _monospace_font(point_size: int) -> QFont:
    """Return the platform's fixed-pitch font (Menlo/Consolas/DejaVu Sans Mono)."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(point_size)
    return font


def _emoji_icon(emoji: str, size: int = 16) -> QIcon:
    """Render a single emoji glyph as a centered QIcon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = painter.font()
    font.setPointSize(int(size * 0.75))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
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


class _CurrentVideo:
    """Mutable holder for the video currently being processed, shared across
    the log handler, stdout capture, and segment callback inside one worker run."""

    def __init__(self) -> None:
        self.value: Path | None = None


class _QtLogHandler(logging.Handler):
    def __init__(self, signal: Signal, current_video: Callable[[], Path | None]):
        super().__init__()
        self._signal = signal
        self._current_video = current_video

    def emit(self, record: logging.LogRecord) -> None:
        self._signal.emit(self._current_video(), self.format(record))


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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        width = available if available > 0 else 320
        name = Path(text).name
        if name and len(name) < len(text):
            prefix = text[: -len(name)]
            prefix_width = max(width - metrics.horizontalAdvance(name), 0)
            elided_prefix = metrics.elidedText(
                prefix, Qt.TextElideMode.ElideMiddle, prefix_width
            )
            elided = elided_prefix + name
        else:
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)
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

    def focusInEvent(self, event) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.hasFocus():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = painter.pen()
            pen.setColor(QColor("#1565C0"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 9, 9)
            painter.end()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            path = Path(folder)
            self.set_folder(path)
            self.folder_dropped.emit(path)

    def mousePressEvent(self, event) -> None:
        self._browse()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._browse()
        else:
            super().keyPressEvent(event)


class _FileScanThread(QThread):
    files_ready = Signal(object)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:
        try:
            videos = [self._root] if self._root.is_file() else find_videos(self._root)
        except SystemExit as exc:
            logging.warning("Could not scan %s: %s", self._root, exc)
            videos = []
        self.files_ready.emit(videos)


class _WorkerThread(QThread):
    log_line = Signal(object, str)
    progress = Signal(object)
    file_progress = Signal(float)
    # "qlonglong" rather than the default 32-bit `int` mapping, since model
    # file sizes (e.g. large-v3 at ~3.1GB) exceed a signed 32-bit int.
    model_progress = Signal("qlonglong", "qlonglong")
    finished_run = Signal(bool)

    def __init__(
        self,
        root: Path,
        model_name: str,
        language: str | None,
        force: bool,
        debug: bool,
        threads: int,
    ) -> None:
        super().__init__()
        self._root = root
        self._model_name = model_name
        self._language = language
        self._force = force
        self._debug = debug
        self._threads = threads
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        current = _CurrentVideo()

        handler = _QtLogHandler(self.log_line, lambda: current.value)
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        saved_level = root_logger.level
        root_logger.setLevel(logging.DEBUG if self._debug else logging.INFO)

        class _StdoutCapture:
            def __init__(self, sig: Signal, current_video: Callable[[], Path | None]) -> None:
                self._sig = sig
                self._current_video = current_video

            def write(self, text: str) -> None:
                if text.strip():
                    self._sig.emit(self._current_video(), text.rstrip())

            def flush(self) -> None:
                pass

        saved_stdout = sys.stdout
        sys.stdout = _StdoutCapture(self.log_line, lambda: current.value)  # type: ignore[assignment]

        def _on_progress(event) -> None:
            if event.stage == "start":
                current.value = event.video
            self.progress.emit(event)
            if event.stage in ("done", "skip", "fail"):
                current.value = None

        def _on_segment(text: str) -> None:
            self.log_line.emit(current.value, text)

        success = True
        try:
            process_directory(
                self._root,
                model_name=self._model_name,
                language=self._language,
                force=self._force,
                show_progress=False,
                cancel=self._cancel,
                on_progress=_on_progress,
                on_segment=_on_segment,
                on_file_progress=self.file_progress.emit,
                on_model_progress=self.model_progress.emit,
                n_threads=self._threads,
            )
        except SystemExit as exc:
            success = exc.code in (0, None)
        except Exception:
            logging.exception("Unexpected error")
            success = False
        finally:
            sys.stdout = saved_stdout
            root_logger.removeHandler(handler)
            root_logger.setLevel(saved_level)

        self.finished_run.emit(success)


class MainWindow(QMainWindow):
    _AUTO_RERUN_SECONDS = 600
    _RUN_BTN_STYLE = (
        "QPushButton:enabled {"
        "  background: #D6EAFB;"
        "  border: 2px solid #2E8B57;"
        "  border-radius: 6px;"
        "}"
        "QPushButton:enabled:focus {"
        "  border: 2px solid #1565C0;"
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
        "QPushButton:focus {"
        "  border: 2px solid #1565C0;"
        "}"
    )
    _CANCEL_BTN_STYLE_ACTIVE = (
        "QPushButton {"
        "  background: palette(button);"
        "  border: 2px solid #C0392B;"
        "  border-radius: 6px;"
        "  color: #C0392B;"
        "}"
        "QPushButton:focus {"
        "  border: 2px solid #1565C0;"
        "}"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Add Subtitles to Videos")
        self.setMinimumWidth(560)
        self._folder: Path | None = None
        self._worker: _WorkerThread | None = None
        self._pending_run = False
        self._cancel_requested = False
        self._rerun_seconds_left = 0
        self._rerun_timer = QTimer(self)
        self._rerun_timer.setInterval(1000)
        self._rerun_timer.timeout.connect(self._on_rerun_tick)

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
        self._clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hint_row.addWidget(self._clear_btn)
        layout.addLayout(hint_row)

        progress_frame = QFrame()
        progress_frame.setStyleSheet(
            "QFrame {"
            "  border: 1px solid palette(mid);"
            "  border-radius: 6px;"
            "}"
        )
        progress_layout = QVBoxLayout(progress_frame)
        progress_layout.setContentsMargins(10, 8, 10, 8)
        progress_layout.setSpacing(6)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._status_label = QLabel("Ready to run")
        self._status_label.setStyleSheet("color: palette(window-text);")
        status_row.addWidget(self._status_label, 1)
        progress_layout.addLayout(status_row)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 1)
        self._overall_bar.setValue(0)
        self._overall_bar.setFormat("Ready")
        self._overall_bar.setMaximumHeight(22)
        self._overall_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        progress_layout.addWidget(self._overall_bar)

        self._file_bar = QProgressBar()
        self._file_bar.setRange(0, 100)
        self._file_bar.setValue(0)
        self._file_bar.setFormat("")
        self._file_bar.setMaximumHeight(22)
        self._file_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        progress_layout.addWidget(self._file_bar)

        layout.addWidget(progress_frame)

        self._tree_threads: list[_FileScanThread] = []
        self._tree_scan_token = 0
        self._file_row_by_path: dict[Path, int] = {}
        self._path_by_row: dict[int, Path] = {}
        self._file_logs: dict[Path, list[str]] = {}
        self._open_log_dialogs: dict[Path, QPlainTextEdit] = {}
        self._done_icon = _check_icon(QColor("#2e7d32"))
        self._skipped_icon = _check_icon(QColor("#9e9e9e"))
        self._scroll_icon = _emoji_icon("\U0001F4DC")
        self._model_not_downloaded_icon = _download_icon(QColor("#9e9e9e"))
        self._model_downloading_icon = _download_icon(QColor("#1565c0"))

        tree_header_row = QHBoxLayout()
        self._tree_label = QLabel("Files to process")
        self._tree_label.setStyleSheet(_MUTED_TEXT_STYLE)
        self._tree_label.setVisible(False)
        tree_header_row.addWidget(self._tree_label, 1)
        self._counts_label = QLabel("")
        self._counts_label.setStyleSheet(_MUTED_TEXT_STYLE)
        tree_header_row.addWidget(self._counts_label)
        layout.addLayout(tree_header_row)

        table_font = _monospace_font(11)

        self._scan_message = QLabel()
        self._scan_message.setFont(table_font)
        self._scan_message.setStyleSheet(_MUTED_TEXT_STYLE)
        self._scan_message.setTextFormat(Qt.TextFormat.PlainText)
        self._scan_message.setVisible(False)
        layout.addWidget(self._scan_message, 1)

        self._file_table = QTableWidget(0, 3)
        self._file_table.setHorizontalHeaderLabels(["File", "Status", "Logs"])
        self._file_table.setFont(table_font)
        self._file_table.verticalHeader().setVisible(False)
        self._file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._file_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._file_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._file_table.setShowGrid(True)
        self._file_table.setAlternatingRowColors(True)
        self._file_table.cellClicked.connect(self._on_file_table_cell_clicked)
        header = self._file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
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
        self._file_table.setMinimumHeight(table_height)
        self._file_table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._file_table.setVisible(False)
        layout.addWidget(self._file_table, 1)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        for m in ("tiny", "base", "small", "medium", "large-v3"):
            self._model_combo.addItem(m)
        self._model_combo.setCurrentText("medium")
        self._model_combo.currentTextChanged.connect(self._refresh_model_status_icon)
        opts.addWidget(self._model_combo)
        self._model_status_icon = QLabel()
        opts.addWidget(self._model_status_icon)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Language:"))
        self._lang_combo = QComboBox()
        self._lang_combo.addItem("Auto-detect", "")
        for code, name in _LANGUAGES:
            self._lang_combo.addItem(f"{name} ({code})", code)
        self._lang_combo.setMinimumWidth(160)
        opts.addWidget(self._lang_combo)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Threads:"))
        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(1, default_n_threads())
        self._threads_spin.setValue(default_n_threads())
        opts.addWidget(self._threads_spin)
        opts.addSpacing(16)
        self._force_check = QCheckBox("Force re-run")
        opts.addWidget(self._force_check)
        self._debug_check = QCheckBox("Debug logging")
        opts.addWidget(self._debug_check)
        self._auto_rerun_check = QCheckBox("Auto re-run")
        self._auto_rerun_check.setChecked(True)
        self._auto_rerun_check.setToolTip("Automatically re-scan and re-run every 10 minutes after a successful run")
        self._auto_rerun_check.stateChanged.connect(self._on_auto_rerun_toggled)
        opts.addWidget(self._auto_rerun_check)
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

        self._final_event = None
        self._current_video_index = 0
        self._current_total = 0

        self._load_prefs()
        self._refresh_model_status_icon()
        QTimer.singleShot(0, self._run_btn.setFocus)

    def _load_prefs(self) -> None:
        cfg = load_config()
        self._model_combo.setCurrentText(cfg.get("model", "medium"))
        saved_lang = cfg.get("language", "")
        idx = self._lang_combo.findData(saved_lang)
        self._lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._threads_spin.setValue(cfg.get("threads", default_n_threads()))
        self._auto_rerun_check.setChecked(cfg.get("auto_rerun", True))
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
            "threads": self._threads_spin.value(),
            "auto_rerun": self._auto_rerun_check.isChecked(),
        })

    def _refresh_model_status_icon(self) -> None:
        model_name = self._model_combo.currentText()
        if is_model_downloaded(model_name):
            self._model_status_icon.setPixmap(self._done_icon.pixmap(16, 16))
            self._model_status_icon.setToolTip(f"Model '{model_name}' is downloaded")
        else:
            self._model_status_icon.setPixmap(self._model_not_downloaded_icon.pixmap(16, 16))
            self._model_status_icon.setToolTip(f"Model '{model_name}' will be downloaded on first run")

    def _shutdown_threads(self) -> None:
        self._rerun_timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        for thread in list(self._tree_threads):
            thread.wait()

    def closeEvent(self, event) -> None:
        self._shutdown_threads()
        self._save_prefs()
        super().closeEvent(event)

    def _on_folder_set(self, path: Path) -> None:
        self._folder = path
        self._pending_run = False
        self._stop_rerun_countdown()
        self._run_btn.setEnabled(True)
        self._change_hint.setVisible(True)
        self._clear_btn.setHidden(False)
        self._save_prefs()
        self._start_tree_scan(path)
        self._run_btn.setFocus()

    def _clear_selection(self) -> None:
        self._folder = None
        self._drop_zone.set_folder(None)
        self._pending_run = False
        self._stop_rerun_countdown()
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
        self._path_by_row = {}
        self._file_logs = {}
        self._open_log_dialogs = {}
        self._scan_message.setText("Scanning…")
        self._scan_message.setVisible(True)
        self._counts_label.setText("")
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
                self._path_by_row = {}
                self._file_table.setVisible(False)
                self._scan_message.setText("(no video files found)")
                self._scan_message.setVisible(True)
                self._counts_label.setText("0 files to process")
            else:
                self._scan_message.setVisible(False)
                self._counts_label.setText(f"{len(files)} file(s) to process")
                self._file_table.setRowCount(len(files))
                self._file_row_by_path = {}
                self._path_by_row = {}
                for row, path in enumerate(files):
                    display = path.name
                    if self._folder is not None and self._folder.is_dir():
                        try:
                            display = str(path.relative_to(self._folder))
                        except ValueError:
                            pass
                    self._file_table.setItem(row, 0, QTableWidgetItem(display))
                    self._file_table.setItem(row, 1, QTableWidgetItem("Pending"))
                    logs_item = QTableWidgetItem()
                    logs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._file_table.setItem(row, 2, logs_item)
                    self._file_row_by_path[path] = row
                    self._path_by_row[row] = path
                self._file_table.setVisible(True)
        except RuntimeError:
            return  # widget was destroyed (e.g. window closed) before the scan finished
        if self._pending_run:
            self._pending_run = False
            self._start_worker()

    def _clear_tree_view(self) -> None:
        self._tree_scan_token += 1
        self._file_row_by_path = {}
        self._path_by_row = {}
        self._file_logs = {}
        self._open_log_dialogs = {}
        self._tree_label.setVisible(False)
        self._scan_message.setVisible(False)
        self._scan_message.setText("")
        self._counts_label.setText("")
        self._file_table.setVisible(False)
        self._file_table.setRowCount(0)

    def _on_log_line(self, video: Path | None, line: str) -> None:
        if video is not None:
            is_first_line = video not in self._file_logs
            self._file_logs.setdefault(video, []).append(line)
            if is_first_line:
                row = self._file_row_by_path.get(video)
                if row is not None:
                    item = self._file_table.item(row, 2)
                    if item is not None:
                        item.setIcon(self._scroll_icon)
                        item.setToolTip("Click to read logs")
            log_view = self._open_log_dialogs.get(video)
            if log_view is not None:
                log_view.appendPlainText(line)

    def _on_file_table_cell_clicked(self, row: int, column: int) -> None:
        if column != 2:
            return
        video = self._path_by_row.get(row)
        if video is None:
            return
        lines = self._file_logs.get(video)
        text = "\n".join(lines) if lines else "No logs captured yet."

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Logs — {video.name}")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.resize(640, 400)

        dialog_layout = QVBoxLayout(dialog)
        log_view = QPlainTextEdit()
        log_view.setReadOnly(True)
        log_view.setPlainText(text)
        mono = _monospace_font(10)
        log_view.setFont(mono)
        dialog_layout.addWidget(log_view)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        dialog_layout.addLayout(btn_row)

        self._open_log_dialogs[video] = log_view
        dialog.finished.connect(lambda _r=None, v=video: self._open_log_dialogs.pop(v, None))

        dialog.show()

    def _update_file_status(self, video: Path | None, status: str) -> None:
        if video is None:
            return
        row = self._file_row_by_path.get(video)
        if row is None:
            return
        item = self._file_table.item(row, 1)
        if item is None:
            return
        if status == "Done":
            item.setIcon(self._done_icon)
            item.setText("Done")
            item.setToolTip("Done")
        elif status == "Skipped":
            item.setIcon(self._skipped_icon)
            item.setText("Skipped")
            item.setToolTip("Skipped")
        else:
            item.setIcon(QIcon())
            item.setText(status)
            item.setToolTip("")

    def _on_progress(self, event) -> None:
        name = event.video.name if event.video else ""
        scale = _OVERALL_PROGRESS_SCALE
        if event.stage == "start":
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
            f"done {event.done + event.skipped}/{event.total}"
            f" · success {event.done} · skipped {event.skipped} · failed {event.failed}"
        )

    def _on_file_progress(self, fraction: float) -> None:
        self._file_bar.setValue(round(fraction * 100))
        if self._current_total:
            combined = (self._current_video_index - 1) + fraction
            self._overall_bar.setValue(round(combined * _OVERALL_PROGRESS_SCALE))

    def _on_model_progress(self, downloaded: int, total: int) -> None:
        self._model_status_icon.setPixmap(self._model_downloading_icon.pixmap(16, 16))
        name = self._model_combo.currentText()
        self._model_status_icon.setToolTip(f"Downloading model '{name}'…")
        if total:
            pct = downloaded / total * 100
            self._status_label.setText(
                f"Downloading model '{name}'… {format_size_mb(downloaded)} / {format_size_mb(total)}"
            )
            # QProgressBar's range/value are a 32-bit C++ int, too narrow for
            # raw byte counts on multi-GB models — use KiB instead.
            self._overall_bar.setRange(0, total // 1024 or 1)
            self._overall_bar.setValue(downloaded // 1024)
            self._overall_bar.setFormat(f"{pct:.0f}%")
        else:
            self._status_label.setText(f"Downloading model '{name}'…")
            self._overall_bar.setRange(0, 0)
            self._overall_bar.setFormat("Downloading…")

    def _cancel_run(self) -> None:
        if self._rerun_timer.isActive():
            self._stop_rerun_countdown()
            self._run_btn.setFocus()
            return
        if self._pending_run:
            self._pending_run = False
            self._run_btn.setEnabled(True)
            self._run_btn.setText("Run")
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)
            self._status_label.setText("Cancelled")
            self._run_btn.setFocus()
            return
        self._cancel_requested = True
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)
        self._status_label.setText("Cancelling…")

    def _start_rerun_countdown(self) -> None:
        self._rerun_seconds_left = self._AUTO_RERUN_SECONDS
        self._run_btn.setEnabled(True)
        self._update_rerun_button_text()
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_ACTIVE)
        self._rerun_timer.start()

    def _stop_rerun_countdown(self) -> None:
        self._rerun_timer.stop()
        self._run_btn.setText("Run")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)

    def _on_auto_rerun_toggled(self, _state: int) -> None:
        if not self._auto_rerun_check.isChecked() and self._rerun_timer.isActive():
            self._stop_rerun_countdown()

    def _update_rerun_button_text(self) -> None:
        mins, secs = divmod(max(self._rerun_seconds_left, 0), 60)
        self._run_btn.setText(f"Run (auto re-run in {mins}:{secs:02d})")

    def _on_rerun_tick(self) -> None:
        self._rerun_seconds_left -= 1
        if self._rerun_seconds_left <= 0:
            self._rerun_timer.stop()
            self._run_btn.setText("Run")
            self._run()
            return
        self._update_rerun_button_text()

    def _run(self) -> None:
        if not self._folder:
            return
        self._rerun_timer.stop()
        self._cancel_requested = False
        self._run_btn.setEnabled(False)
        self._run_btn.setText("Running")
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_ACTIVE)
        self._cancel_btn.setFocus()
        self._final_event = None
        self._current_video_index = 0
        self._current_total = 0
        self._overall_bar.setRange(0, 1)
        self._overall_bar.setValue(0)
        self._overall_bar.setFormat("Starting…")
        self._file_bar.setValue(0)
        self._file_bar.setFormat("")
        self._status_label.setText("Preparing…")
        # Rescan before starting so the file list (and what actually gets
        # processed) reflects any files added/removed since the last scan —
        # e.g. while waiting on the auto re-run countdown.
        self._pending_run = True
        self._start_tree_scan(self._folder)

    def _start_worker(self) -> None:
        lang = self._lang_combo.currentData() or None
        self._worker = _WorkerThread(
            self._folder,
            self._model_combo.currentText(),
            lang,
            self._force_check.isChecked(),
            self._debug_check.isChecked(),
            self._threads_spin.value(),
        )
        self._worker.log_line.connect(self._on_log_line)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.model_progress.connect(self._on_model_progress)
        self._worker.finished_run.connect(self._on_done)
        self._worker.start()

    def _on_done(self, success: bool) -> None:
        self._run_btn.setEnabled(True)
        self._run_btn.setText("Run")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(self._CANCEL_BTN_STYLE_IDLE)
        self._run_btn.setFocus()
        self._refresh_model_status_icon()
        if self._final_event is not None:
            e = self._final_event
            mins, secs = divmod(int(e.elapsed or 0), 60)
            elapsed_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            self._status_label.setText("Done" if success else "Finished with errors")
            self._counts_label.setText(
                f"done {e.done + e.skipped}/{e.total}"
                f" · success {e.done} · skipped {e.skipped} · failed {e.failed} · {elapsed_str}"
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
        if not self._cancel_requested and self._auto_rerun_check.isChecked():
            self._start_rerun_countdown()


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
