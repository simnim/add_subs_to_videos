from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .config import load_config, save_config
from .transcribe import process_directory


class _QtLogHandler(logging.Handler):
    def __init__(self, signal: Signal):
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        self._signal.emit(self.format(record))


class DropZone(QFrame):
    folder_dropped = Signal(Path)

    _EMPTY_STYLE = (
        "DropZone {"
        "  border: 2px dashed palette(mid);"
        "  border-radius: 8px;"
        "  background: palette(base);"
        "}"
    )
    _SELECTED_STYLE = (
        "DropZone {"
        "  border: 1px solid palette(mid);"
        "  border-radius: 10px;"
        "  background: palette(alternate-base);"
        "}"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self._folder_path: Path | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._placeholder_label = QLabel("Drop a folder here\nor click to browse")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_font = QFont()
        placeholder_font.setPointSize(14)
        self._placeholder_label.setFont(placeholder_font)
        self._placeholder_label.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self._placeholder_label, 1)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(32, 32)
        self._icon_label.setPixmap(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon).pixmap(32, 32)
        )
        layout.addWidget(self._icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._name_label = QLabel()
        name_font = QFont()
        name_font.setPointSize(13)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        text_col.addWidget(self._name_label)

        self._path_label = QLabel()
        path_font = QFont()
        path_font.setPointSize(11)
        self._path_label.setFont(path_font)
        self._path_label.setStyleSheet("color: palette(window-text);")
        text_col.addWidget(self._path_label)

        layout.addLayout(text_col, 1)

        self.set_folder(None)

    def _update_path_label(self, path: Path) -> None:
        metrics = QFontMetrics(self._path_label.font())
        elided = metrics.elidedText(
            str(path), Qt.TextElideMode.ElideMiddle, self._path_label.width() or 320
        )
        self._path_label.setText(elided)

    def set_folder(self, path: Path | None) -> None:
        self._folder_path = path
        if path is None:
            self._icon_label.setVisible(False)
            self._name_label.setVisible(False)
            self._path_label.setVisible(False)
            self._placeholder_label.setVisible(True)
            self.setToolTip("")
            self.setStyleSheet(self._EMPTY_STYLE)
        else:
            self._placeholder_label.setVisible(False)
            self._icon_label.setVisible(True)
            self._name_label.setVisible(True)
            self._path_label.setVisible(True)
            self._name_label.setText(path.name or str(path))
            self._update_path_label(path)
            self.setToolTip(str(path))
            self.setStyleSheet(self._SELECTED_STYLE)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._folder_path is not None:
            self._update_path_label(self._folder_path)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and Path(urls[0].toLocalFile()).is_dir():
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.is_dir():
                self.set_folder(path)
                self.folder_dropped.emit(path)

    def mousePressEvent(self, event) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            path = Path(folder)
            self.set_folder(path)
            self.folder_dropped.emit(path)


class _WorkerThread(QThread):
    log_line = Signal(str)
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

        self._change_hint = QLabel("Drop a new folder above, or click to change")
        self._change_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._change_hint.setStyleSheet("color: palette(placeholder-text);")
        self._change_hint.setVisible(False)
        layout.addWidget(self._change_hint)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        for m in ("tiny", "base", "small", "medium", "large-v3"):
            self._model_combo.addItem(m)
        self._model_combo.setCurrentText("medium")
        opts.addWidget(self._model_combo)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Language:"))
        self._lang_edit = QLineEdit()
        self._lang_edit.setPlaceholderText("auto")
        self._lang_edit.setFixedWidth(60)
        opts.addWidget(self._lang_edit)
        opts.addSpacing(16)
        self._force_check = QCheckBox("Force re-run")
        opts.addWidget(self._force_check)
        opts.addStretch()
        layout.addLayout(opts)

        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run")
        self._run_btn.setEnabled(False)
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._run)
        btn_row.addWidget(self._run_btn)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setMinimumHeight(36)
        self._cancel_btn.clicked.connect(self._cancel_run)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

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
        self._lang_edit.setText(cfg.get("language", ""))
        directory = cfg.get("directory", "")
        if directory and Path(directory).is_dir():
            path = Path(directory)
            self._drop_zone.set_folder(path)
            self._folder = path
            self._run_btn.setEnabled(True)
            self._change_hint.setVisible(True)

    def _save_prefs(self) -> None:
        save_config({
            "model": self._model_combo.currentText(),
            "language": self._lang_edit.text().strip(),
            "directory": str(self._folder) if self._folder else "",
        })

    def closeEvent(self, event) -> None:
        self._save_prefs()
        super().closeEvent(event)

    def _on_folder_set(self, path: Path) -> None:
        self._folder = path
        self._run_btn.setEnabled(True)
        self._change_hint.setVisible(True)
        self._save_prefs()

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def _cancel_run(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)

    def _run(self) -> None:
        if not self._folder:
            return
        self._log.clear()
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        lang = self._lang_edit.text().strip() or None
        self._worker = _WorkerThread(
            self._folder,
            self._model_combo.currentText(),
            lang,
            self._force_check.isChecked(),
        )
        self._worker.log_line.connect(self._append_log)
        self._worker.finished_run.connect(self._on_done)
        self._worker.start()

    def _on_done(self, success: bool) -> None:
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._append_log("--- Done ---" if success else "--- Finished with errors ---")


def _dev_icon_path() -> Path | None:
    """Locate assets/icon.svg relative to a source checkout (e.g. `uv run`)."""
    candidate = Path(__file__).resolve().parents[2] / "assets" / "icon.svg"
    return candidate if candidate.is_file() else None


def main() -> None:
    app = QApplication(sys.argv)
    icon_path = _dev_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
