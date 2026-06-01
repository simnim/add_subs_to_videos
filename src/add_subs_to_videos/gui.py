from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .transcribe import process_directory


class _QtLogHandler(logging.Handler):
    def __init__(self, signal: Signal):
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        self._signal.emit(self.format(record))


class DropZone(QLabel):
    folder_dropped = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.setText("Drop a folder here\nor click to browse")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(120)
        font = QFont()
        font.setPointSize(14)
        self.setFont(font)
        self.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #888;"
            "  border-radius: 8px;"
            "  color: #555;"
            "  background: #f5f5f5;"
            "  padding: 16px;"
            "}"
        )

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
                self.setText(str(path))
                self.folder_dropped.emit(path)

    def mousePressEvent(self, event) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            path = Path(folder)
            self.setText(str(path))
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

        self._run_btn = QPushButton("Run")
        self._run_btn.setEnabled(False)
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._run)
        layout.addWidget(self._run_btn)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        mono = QFont("monospace")
        mono.setPointSize(10)
        self._log.setFont(mono)
        layout.addWidget(self._log)

        self._load_prefs()

    def _load_prefs(self) -> None:
        s = QSettings("add_subs_to_videos", "add_subs_to_videos")
        self._model_combo.setCurrentText(s.value("model", "medium"))
        self._lang_edit.setText(s.value("language", ""))
        folder = s.value("last_folder", "")
        if folder and Path(folder).is_dir():
            self._drop_zone.setText(folder)
            self._folder = Path(folder)
            self._run_btn.setEnabled(True)

    def _save_prefs(self) -> None:
        s = QSettings("add_subs_to_videos", "add_subs_to_videos")
        s.setValue("model", self._model_combo.currentText())
        s.setValue("language", self._lang_edit.text().strip())
        if self._folder:
            s.setValue("last_folder", str(self._folder))

    def closeEvent(self, event) -> None:
        self._save_prefs()
        super().closeEvent(event)

    def _on_folder_set(self, path: Path) -> None:
        self._folder = path
        self._run_btn.setEnabled(True)

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def _run(self) -> None:
        if not self._folder:
            return
        self._log.clear()
        self._run_btn.setEnabled(False)
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
        self._append_log("--- Done ---" if success else "--- Finished with errors ---")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
