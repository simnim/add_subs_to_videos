from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFileDialog

from add_subs_to_videos.gui import DropZone, MainWindow, _dev_icon_path, _WorkerThread


def _mime_event(paths: list[Path]) -> MagicMock:
    """Minimal mock drag/drop event carrying the given paths as file URLs."""
    event = MagicMock()
    urls = [QUrl.fromLocalFile(str(p)) for p in paths]
    event.mimeData.return_value.hasUrls.return_value = bool(urls)
    event.mimeData.return_value.urls.return_value = urls
    return event


# ---------------------------------------------------------------------------
# Prevent every test from touching the real config file
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_config(mocker):
    mocker.patch("add_subs_to_videos.gui.load_config", return_value={})
    mocker.patch("add_subs_to_videos.gui.save_config")


# ---------------------------------------------------------------------------
# DropZone
# ---------------------------------------------------------------------------


class TestDropZone:
    @pytest.fixture
    def dz(self, qtbot):
        widget = DropZone()
        qtbot.addWidget(widget)
        return widget

    def test_drag_enter_accepts_directory(self, dz, tmp_path):
        event = _mime_event([tmp_path])
        dz.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_drag_enter_ignores_file_url(self, dz, tmp_path):
        f = tmp_path / "clip.mp4"
        f.touch()
        event = _mime_event([f])
        dz.dragEnterEvent(event)
        event.acceptProposedAction.assert_not_called()

    def test_drag_enter_ignores_event_with_no_urls(self, dz):
        event = _mime_event([])
        event.mimeData.return_value.hasUrls.return_value = False
        dz.dragEnterEvent(event)
        event.acceptProposedAction.assert_not_called()
        event.ignore.assert_called_once()

    def test_drop_emits_folder_dropped_signal(self, dz, tmp_path):
        received = []
        dz.folder_dropped.connect(received.append)
        dz.dropEvent(_mime_event([tmp_path]))
        assert received == [tmp_path]

    def test_drop_updates_folder_state(self, dz, tmp_path):
        dz.dropEvent(_mime_event([tmp_path]))
        assert dz._folder_path == tmp_path
        assert dz._name_label.text() == tmp_path.name
        assert dz.toolTip() == str(tmp_path)

    def test_drop_ignores_file_url(self, dz, tmp_path):
        f = tmp_path / "clip.mp4"
        f.touch()
        received = []
        dz.folder_dropped.connect(received.append)
        dz.dropEvent(_mime_event([f]))
        assert received == []

    def test_browse_emits_signal_on_selection(self, dz, tmp_path):
        received = []
        dz.folder_dropped.connect(received.append)
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(tmp_path)):
            dz.mousePressEvent(MagicMock())
        assert received == [tmp_path]

    def test_browse_does_nothing_on_cancel(self, dz):
        received = []
        dz.folder_dropped.connect(received.append)
        with patch.object(QFileDialog, "getExistingDirectory", return_value=""):
            dz.mousePressEvent(MagicMock())
        assert received == []


# ---------------------------------------------------------------------------
# _WorkerThread  (run() called directly — synchronous, process_directory mocked)
# ---------------------------------------------------------------------------


class TestWorkerThread:
    @pytest.fixture
    def mock_pd(self, mocker):
        return mocker.patch("add_subs_to_videos.gui.process_directory")

    @pytest.fixture
    def thread(self, tmp_path, qapp):
        return _WorkerThread(tmp_path, "medium", None, False)

    def test_calls_process_directory_with_correct_args(self, thread, mock_pd, tmp_path):
        thread.run()
        mock_pd.assert_called_once_with(
            tmp_path,
            model_name="medium",
            language=None,
            force=False,
            show_progress=False,
            cancel=ANY,
        )

    def test_language_forwarded(self, tmp_path, qapp, mock_pd):
        thread = _WorkerThread(tmp_path, "small", "fr", False)
        thread.run()
        assert mock_pd.call_args.kwargs["language"] == "fr"

    def test_finished_run_true_on_success(self, thread, mock_pd):
        results = []
        thread.finished_run.connect(results.append)
        thread.run()
        assert results == [True]

    def test_finished_run_false_on_system_exit_1(self, thread, mock_pd):
        mock_pd.side_effect = SystemExit(1)
        results = []
        thread.finished_run.connect(results.append)
        thread.run()
        assert results == [False]

    def test_finished_run_true_on_system_exit_0(self, thread, mock_pd):
        mock_pd.side_effect = SystemExit(0)
        results = []
        thread.finished_run.connect(results.append)
        thread.run()
        assert results == [True]

    def test_finished_run_false_on_exception(self, thread, mock_pd):
        mock_pd.side_effect = RuntimeError("boom")
        results = []
        thread.finished_run.connect(results.append)
        thread.run()
        assert results == [False]

    def test_logging_captured_as_log_line(self, thread, mock_pd):
        def _emit_log(*args, **kwargs):
            logging.getLogger().info("hello from transcribe")
        mock_pd.side_effect = _emit_log
        lines = []
        thread.log_line.connect(lines.append)
        thread.run()
        assert any("hello from transcribe" in line for line in lines)

    def test_stdout_captured_as_log_line(self, thread, mock_pd):
        def _print_summary(*args, **kwargs):
            print("Summary: 1 transcribed")
        mock_pd.side_effect = _print_summary
        lines = []
        thread.log_line.connect(lines.append)
        thread.run()
        assert any("Summary" in line for line in lines)

    def test_stdout_restored_after_run(self, thread, mock_pd):
        original = sys.stdout
        thread.run()
        assert sys.stdout is original

    def test_logging_handler_removed_after_run(self, thread, mock_pd):
        root = logging.getLogger()
        count_before = len(root.handlers)
        thread.run()
        assert len(root.handlers) == count_before

    def test_cancel_sets_event_passed_to_process_directory(self, tmp_path, qapp, mocker):
        import threading
        received_cancel = {}

        def capture_cancel(*args, cancel=None, **kwargs):
            received_cancel["event"] = cancel

        mocker.patch("add_subs_to_videos.gui.process_directory", side_effect=capture_cancel)
        thread = _WorkerThread(tmp_path, "medium", None, False)
        thread.run()
        assert isinstance(received_cancel["event"], threading.Event)

    def test_cancel_method_sets_the_event(self, thread, mock_pd):
        assert not thread._cancel.is_set()
        thread.cancel()
        assert thread._cancel.is_set()


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class TestMainWindow:
    @pytest.fixture
    def window(self, qtbot):
        w = MainWindow()
        qtbot.addWidget(w)
        return w

    def test_run_button_disabled_initially(self, window):
        assert not window._run_btn.isEnabled()

    def test_folder_dropped_enables_run_button(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        assert window._run_btn.isEnabled()

    def test_folder_dropped_stores_path(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        assert window._folder == tmp_path

    def test_folder_dropped_saves_prefs_immediately(self, mocker, window, tmp_path):
        mock_save = mocker.patch("add_subs_to_videos.gui.save_config")
        window._drop_zone.folder_dropped.emit(tmp_path)
        mock_save.assert_called_once_with({
            "model": window._model_combo.currentText(),
            "language": window._lang_edit.text().strip(),
            "directory": str(tmp_path),
        })

    def test_load_prefs_sets_model(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"model": "large-v3"})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._model_combo.currentText() == "large-v3"

    def test_load_prefs_sets_language(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"language": "ja"})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._lang_edit.text() == "ja"

    def test_load_prefs_restores_valid_folder_and_enables_run(self, mocker, qtbot, tmp_path):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"directory": str(tmp_path)})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._folder == tmp_path
        assert w._run_btn.isEnabled()

    def test_load_prefs_ignores_nonexistent_directory(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"directory": "/no/such/path"})
        w = MainWindow()
        qtbot.addWidget(w)
        assert not w._run_btn.isEnabled()

    def test_save_prefs_writes_model_language_directory(self, mocker, window, tmp_path):
        mock_save = mocker.patch("add_subs_to_videos.gui.save_config")
        window._folder = tmp_path
        window._model_combo.setCurrentText("tiny")
        window._lang_edit.setText("fr")
        window._save_prefs()
        mock_save.assert_called_once_with({
            "model": "tiny",
            "language": "fr",
            "directory": str(tmp_path),
        })

    def test_close_event_triggers_save(self, mocker, window):
        mock_save = mocker.patch("add_subs_to_videos.gui.save_config")
        window.close()
        mock_save.assert_called()

    def test_on_done_true_reenables_run_and_logs_done(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run_btn.setEnabled(False)
        window._on_done(True)
        assert window._run_btn.isEnabled()
        assert "Done" in window._log.toPlainText()

    def test_on_done_false_reenables_run_and_logs_errors(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run_btn.setEnabled(False)
        window._on_done(False)
        assert window._run_btn.isEnabled()
        assert "errors" in window._log.toPlainText()

    def test_cancel_button_disabled_initially(self, window):
        assert not window._cancel_btn.isEnabled()

    def test_cancel_button_enabled_while_running(self, window, tmp_path, mocker):
        mocker.patch("add_subs_to_videos.gui._WorkerThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run()
        assert window._cancel_btn.isEnabled()
        assert not window._run_btn.isEnabled()

    def test_cancel_button_disabled_on_done(self, window, tmp_path):
        window._cancel_btn.setEnabled(True)
        window._on_done(True)
        assert not window._cancel_btn.isEnabled()

    def test_cancel_run_calls_worker_cancel(self, window, mocker):
        mock_worker = mocker.MagicMock()
        window._worker = mock_worker
        window._cancel_run()
        mock_worker.cancel.assert_called_once()

    def test_cancel_run_disables_cancel_button(self, window, mocker):
        window._worker = mocker.MagicMock()
        window._cancel_btn.setEnabled(True)
        window._cancel_run()
        assert not window._cancel_btn.isEnabled()


# ---------------------------------------------------------------------------
# _dev_icon_path
# ---------------------------------------------------------------------------


def test_dev_icon_path_finds_repo_asset():
    icon_path = _dev_icon_path()
    assert icon_path is not None
    assert icon_path.name == "icon.svg"
    assert icon_path.is_file()


def test_dev_icon_path_returns_none_when_missing(mocker):
    mocker.patch("add_subs_to_videos.gui.Path.is_file", return_value=False)
    assert _dev_icon_path() is None
