from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFileDialog

from add_subs_to_videos.gui import (
    DropZone,
    MainWindow,
    _dev_icon_path,
    _FileScanThread,
    _OVERALL_PROGRESS_SCALE,
    _WorkerThread,
)
from add_subs_to_videos.transcribe import ProgressEvent


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

    def test_drag_enter_accepts_video_file(self, dz, tmp_path):
        f = tmp_path / "clip.mp4"
        f.touch()
        event = _mime_event([f])
        dz.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_drag_enter_ignores_non_video_file(self, dz, tmp_path):
        f = tmp_path / "notes.txt"
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
        assert tmp_path.name in dz._selection_name_label.text()
        assert dz.toolTip() == str(tmp_path)

    def test_drop_keeps_browse_hint_alongside_path(self, dz, tmp_path):
        assert dz._path_label.text() == dz._EMPTY_HINT
        dz.dropEvent(_mime_event([tmp_path]))
        assert dz._path_label.text() == dz._EMPTY_HINT
        assert not dz._selection_path_label.isHidden()
        assert tmp_path.name in dz._selection_path_label.text()

    def test_drop_emits_for_video_file(self, dz, tmp_path):
        f = tmp_path / "clip.mp4"
        f.touch()
        received = []
        dz.folder_dropped.connect(received.append)
        dz.dropEvent(_mime_event([f]))
        assert received == [f]
        assert dz._folder_path == f
        assert f.name in dz._selection_name_label.text()

    def test_drop_ignores_non_video_file(self, dz, tmp_path):
        f = tmp_path / "notes.txt"
        f.touch()
        received = []
        dz.folder_dropped.connect(received.append)
        dz.dropEvent(_mime_event([f]))
        assert received == []

    def test_drop_with_multiple_urls_uses_first_only(self, dz, tmp_path):
        first = tmp_path / "clip.mp4"
        first.touch()
        second = tmp_path / "other.mkv"
        second.touch()
        received = []
        dz.folder_dropped.connect(received.append)
        dz.dropEvent(_mime_event([first, second]))
        assert received == [first]

    def test_drop_with_invalid_first_url_ignores_valid_second(self, dz, tmp_path):
        invalid = tmp_path / "notes.txt"
        invalid.touch()
        valid = tmp_path / "clip.mp4"
        valid.touch()
        received = []
        dz.folder_dropped.connect(received.append)
        dz.dropEvent(_mime_event([invalid, valid]))
        assert received == []

    def test_browse_emits_signal_on_selection(self, dz, tmp_path):
        received = []
        dz.folder_dropped.connect(received.append)
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(tmp_path)):
            dz.mousePressEvent(MagicMock())
        assert received == [tmp_path]

    @staticmethod
    def _resize_event(old_size, new_size):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QResizeEvent
        return QResizeEvent(QSize(*new_size), QSize(*old_size))

    def test_resize_re_elides_selection_path_label_when_folder_set(self, dz, tmp_path, mocker):
        dz.dropEvent(_mime_event([tmp_path]))
        spy = mocker.spy(dz, "_update_selection_path_label")
        dz.resizeEvent(self._resize_event((400, 120), (200, 120)))
        spy.assert_called_once_with(str(tmp_path))

    def test_resize_does_not_touch_selection_path_label_when_no_folder(self, dz, mocker):
        spy = mocker.spy(dz, "_update_selection_path_label")
        dz.resizeEvent(self._resize_event((400, 120), (200, 120)))
        spy.assert_not_called()

    def test_browse_does_nothing_on_cancel(self, dz):
        received = []
        dz.folder_dropped.connect(received.append)
        with patch.object(QFileDialog, "getExistingDirectory", return_value=""):
            dz.mousePressEvent(MagicMock())
        assert received == []


# ---------------------------------------------------------------------------
# _FileScanThread  (run() called directly — synchronous)
# ---------------------------------------------------------------------------


class TestFileScanThread:
    def test_emits_video_paths_for_directory(self, tmp_video_dir, qapp):
        thread = _FileScanThread(tmp_video_dir)
        received = []
        thread.files_ready.connect(received.append)
        thread.run()
        assert len(received) == 1
        assert received[0] == [tmp_video_dir / "movie.mp4", tmp_video_dir / "show.mkv", tmp_video_dir / "sub" / "episode.mp4"]

    def test_emits_single_path_for_single_file(self, tmp_path, qapp):
        f = tmp_path / "clip.mp4"
        f.touch()
        thread = _FileScanThread(f)
        received = []
        thread.files_ready.connect(received.append)
        thread.run()
        assert received == [[f]]

    def test_emits_empty_list_when_no_videos(self, tmp_path, qapp):
        thread = _FileScanThread(tmp_path)
        received = []
        thread.files_ready.connect(received.append)
        thread.run()
        assert received == [[]]

    def test_emits_empty_list_when_root_does_not_exist(self, tmp_path, qapp, caplog):
        missing = tmp_path / "deleted"
        thread = _FileScanThread(missing)
        received = []
        thread.files_ready.connect(received.append)
        with caplog.at_level("WARNING", logger="root"):
            thread.run()
        assert received == [[]]
        assert "Could not scan" in caplog.text


# ---------------------------------------------------------------------------
# _WorkerThread  (run() called directly — synchronous, process_directory mocked)
# ---------------------------------------------------------------------------


class TestWorkerThread:
    @pytest.fixture
    def mock_pd(self, mocker):
        return mocker.patch("add_subs_to_videos.gui.process_directory")

    @pytest.fixture
    def thread(self, tmp_path, qapp):
        return _WorkerThread(tmp_path, "medium", None, False, False, 4)

    def test_calls_process_directory_with_correct_args(self, thread, mock_pd, tmp_path):
        thread.run()
        mock_pd.assert_called_once_with(
            tmp_path,
            model_name="medium",
            language=None,
            force=False,
            show_progress=False,
            cancel=ANY,
            on_progress=ANY,
            on_segment=ANY,
            on_file_progress=ANY,
            on_model_progress=ANY,
            n_threads=4,
        )

    def test_segment_line_emitted_from_on_segment_callback(self, thread, mock_pd):
        lines = []
        thread.log_line.connect(lambda v, l: lines.append(l))

        def fake_process_directory(*args, **kwargs):
            kwargs["on_segment"]("[00:00 --> 00:02] hello")

        mock_pd.side_effect = fake_process_directory
        thread.run()
        assert lines == ["[00:00 --> 00:02] hello"]

    def test_segment_line_attributed_to_current_video(self, thread, mock_pd, tmp_path):
        video = tmp_path / "movie.mp4"
        received = []
        thread.log_line.connect(lambda v, l: received.append((v, l)))

        def fake_process_directory(*args, **kwargs):
            kwargs["on_progress"](
                ProgressEvent(stage="start", index=1, total=1, video=video, done=0, skipped=0, failed=0)
            )
            kwargs["on_segment"]("[00:00 --> 00:02] hello")
            kwargs["on_progress"](
                ProgressEvent(stage="done", index=1, total=1, video=video, done=1, skipped=0, failed=0)
            )

        mock_pd.side_effect = fake_process_directory
        thread.run()
        assert received == [(video, "[00:00 --> 00:02] hello")]

    def test_log_line_has_no_video_after_file_finishes(self, thread, mock_pd, tmp_path):
        video = tmp_path / "movie.mp4"
        received = []
        thread.log_line.connect(lambda v, l: received.append((v, l)))

        def fake_process_directory(*args, **kwargs):
            kwargs["on_progress"](
                ProgressEvent(stage="start", index=1, total=1, video=video, done=0, skipped=0, failed=0)
            )
            kwargs["on_progress"](
                ProgressEvent(stage="done", index=1, total=1, video=video, done=1, skipped=0, failed=0)
            )
            print("Summary: 1 transcribed")

        mock_pd.side_effect = fake_process_directory
        thread.run()
        assert received == [(None, "Summary: 1 transcribed")]

    def test_file_progress_emitted_from_on_file_progress_callback(self, thread, mock_pd):
        fractions = []
        thread.file_progress.connect(fractions.append)

        def fake_process_directory(*args, **kwargs):
            kwargs["on_file_progress"](0.5)

        mock_pd.side_effect = fake_process_directory
        thread.run()
        assert fractions == [0.5]

    def test_model_progress_emitted_from_on_model_progress_callback(self, thread, mock_pd):
        events = []
        thread.model_progress.connect(lambda d, t: events.append((d, t)))

        def fake_process_directory(*args, **kwargs):
            kwargs["on_model_progress"](50, 100)

        mock_pd.side_effect = fake_process_directory
        thread.run()
        assert events == [(50, 100)]

    def test_model_progress_survives_values_above_32_bit_int_range(self, thread, mock_pd):
        # model_progress is declared as Signal("qlonglong", "qlonglong") specifically
        # because model file sizes (e.g. large-v3, ~3.1GB) exceed the signed 32-bit
        # int range a default `Signal(int, int)` would use.
        downloaded, total = 3_500_000_000, 4_000_000_000
        events = []
        thread.model_progress.connect(lambda d, t: events.append((d, t)))

        def fake_process_directory(*args, **kwargs):
            kwargs["on_model_progress"](downloaded, total)

        mock_pd.side_effect = fake_process_directory
        thread.run()
        assert events == [(downloaded, total)]

    def test_language_forwarded(self, tmp_path, qapp, mock_pd):
        thread = _WorkerThread(tmp_path, "small", "fr", False, False, 4)
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

    def test_unexpected_exception_logs_traceback_and_finishes_false(self, thread, mock_pd):
        mock_pd.side_effect = RuntimeError("model load failed")
        lines = []
        results = []
        thread.log_line.connect(lambda v, l: lines.append(l))
        thread.finished_run.connect(results.append)
        thread.run()

        assert results == [False]
        log_text = "\n".join(lines)
        assert "model load failed" in log_text
        assert "Traceback" in log_text

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
        thread.log_line.connect(lambda v, l: lines.append(l))
        thread.run()
        assert any("hello from transcribe" in line for line in lines)

    def test_stdout_captured_as_log_line(self, thread, mock_pd):
        def _print_summary(*args, **kwargs):
            print("Summary: 1 transcribed")
        mock_pd.side_effect = _print_summary
        lines = []
        thread.log_line.connect(lambda v, l: lines.append(l))
        thread.run()
        assert any("Summary" in line for line in lines)

    def test_blank_stdout_writes_are_not_emitted_as_log_lines(self, thread, mock_pd):
        def _print_lines(*args, **kwargs):
            print("")
            print("   ")
            print("Summary: 1 transcribed")

        mock_pd.side_effect = _print_lines
        lines = []
        thread.log_line.connect(lambda v, l: lines.append(l))
        thread.run()
        assert lines == ["Summary: 1 transcribed"]

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
        thread = _WorkerThread(tmp_path, "medium", None, False, False, 4)
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
            "language": window._lang_combo.currentData(),
            "directory": str(tmp_path),
            "threads": window._threads_spin.value(),
        })

    def test_folder_dropped_shows_clear_button(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        assert not window._clear_btn.isHidden()
        assert not window._change_hint.isHidden()

    def test_clear_button_resets_folder_state(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._clear_btn.click()
        assert window._folder is None
        assert not window._run_btn.isEnabled()
        assert window._clear_btn.isHidden()
        assert window._change_hint.isHidden()
        assert window._drop_zone._folder_path is None

    def test_clear_button_persists_cleared_directory(self, mocker, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        mock_save = mocker.patch("add_subs_to_videos.gui.save_config")
        window._clear_btn.click()
        mock_save.assert_called_once_with({
            "model": window._model_combo.currentText(),
            "language": window._lang_combo.currentData() or "",
            "directory": "",
            "threads": window._threads_spin.value(),
        })

    def test_clear_button_hidden_initially(self, window):
        assert window._clear_btn.isHidden()

    def test_load_prefs_sets_model(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"model": "large-v3"})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._model_combo.currentText() == "large-v3"

    def test_load_prefs_sets_language(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"language": "ja"})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._lang_combo.currentData() == "ja"

    def test_load_prefs_falls_back_to_auto_detect_for_unknown_language_code(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"language": "xx"})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._lang_combo.currentIndex() == 0
        assert w._lang_combo.currentData() == ""

    def test_load_prefs_restores_valid_folder_and_enables_run(self, mocker, qtbot, tmp_path):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"directory": str(tmp_path)})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._folder == tmp_path
        assert not w._clear_btn.isHidden()
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
        window._lang_combo.setCurrentIndex(window._lang_combo.findData("fr"))
        window._threads_spin.setValue(2)
        window._save_prefs()
        mock_save.assert_called_once_with({
            "model": "tiny",
            "language": "fr",
            "directory": str(tmp_path),
            "threads": 2,
        })

    def test_load_prefs_sets_threads(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={"threads": 2})
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._threads_spin.value() == 2

    def test_load_prefs_defaults_threads_to_cpu_count(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.load_config", return_value={})
        mocker.patch("add_subs_to_videos.gui.default_n_threads", return_value=6)
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._threads_spin.value() == 6

    def test_threads_spin_max_is_capped_to_core_count(self, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui.default_n_threads", return_value=6)
        w = MainWindow()
        qtbot.addWidget(w)
        assert w._threads_spin.maximum() == 6

    def test_close_event_triggers_save(self, mocker, window):
        mock_save = mocker.patch("add_subs_to_videos.gui.save_config")
        window.close()
        mock_save.assert_called()

    def test_close_event_cancels_and_waits_for_running_worker(self, mocker, window):
        mock_worker = mocker.MagicMock()
        mock_worker.isRunning.return_value = True
        window._worker = mock_worker
        window.close()
        mock_worker.cancel.assert_called_once()
        mock_worker.wait.assert_called_once()

    def test_close_event_leaves_idle_worker_alone(self, mocker, window):
        mock_worker = mocker.MagicMock()
        mock_worker.isRunning.return_value = False
        window._worker = mock_worker
        window.close()
        mock_worker.cancel.assert_not_called()
        mock_worker.wait.assert_not_called()

    def test_close_event_waits_for_pending_tree_scan_threads(self, mocker, window):
        mock_thread = mocker.MagicMock()
        window._tree_threads.append(mock_thread)
        window.close()
        mock_thread.wait.assert_called_once()

    def test_on_done_true_reenables_run_and_logs_done(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run_btn.setEnabled(False)
        window._on_done(True)
        assert window._run_btn.isEnabled()
        assert "Done" in window._status_label.text()

    def test_on_done_false_reenables_run_and_logs_errors(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run_btn.setEnabled(False)
        window._on_progress(self._event("summary", index=1, total=1, failed=1))
        window._on_done(False)
        assert window._run_btn.isEnabled()
        assert "errors" in window._status_label.text()

    @staticmethod
    def _event(stage, index=1, total=10, video=None, **extra):
        return ProgressEvent(
            stage=stage,
            index=index,
            total=total,
            video=video,
            done=extra.pop("done", 0),
            skipped=extra.pop("skipped", 0),
            failed=extra.pop("failed", 0),
            **extra,
        )

    def test_on_done_without_final_event_shows_done_or_cancelled_status(self, window):
        window._on_done(True)
        assert window._status_label.text() == "Done"
        assert window._overall_bar.format() == "Done"

        window._final_event = None
        window._on_done(False)
        assert window._status_label.text() == "Cancelled"
        assert window._overall_bar.format() == "Cancelled"

    def test_on_done_formats_elapsed_under_a_minute(self, window, tmp_path):
        window._on_progress(self._event("start", index=1, total=1, video=tmp_path / "movie.mp4"))
        window._on_progress(self._event(
            "summary", index=1, total=1, elapsed=45.0, done=1, skipped=0, failed=0,
        ))
        window._on_done(True)
        assert "45s" in window._counts_label.text()
        assert "Complete — 1 transcribed, 0 skipped, 0 failed in 45s" == window._overall_bar.format()

    def test_on_done_formats_elapsed_over_a_minute(self, window, tmp_path):
        window._on_progress(self._event("start", index=1, total=1, video=tmp_path / "movie.mp4"))
        window._on_progress(self._event(
            "summary", index=1, total=1, elapsed=65.0, done=0, skipped=1, failed=0,
        ))
        window._on_done(True)
        assert "1m 05s" in window._counts_label.text()
        assert "Complete — 0 transcribed, 1 skipped, 0 failed in 1m 05s" == window._overall_bar.format()

    def test_progress_start_sets_overall_bar_range_and_value(self, window, tmp_path):
        video = tmp_path / "movie.mp4"
        window._on_progress(self._event("start", index=3, total=10, video=video))
        assert window._overall_bar.minimum() == 0
        assert window._overall_bar.maximum() == 10 * _OVERALL_PROGRESS_SCALE
        assert window._overall_bar.value() == 2 * _OVERALL_PROGRESS_SCALE
        assert window._overall_bar.format() == "3 of 10 files"

    def test_progress_start_resets_file_bar(self, window, tmp_path):
        video = tmp_path / "movie.mp4"
        window._file_bar.setValue(42)
        window._on_progress(self._event("start", index=3, total=10, video=video))
        assert window._file_bar.value() == 0

    def test_progress_done_advances_overall_bar(self, window, tmp_path):
        video = tmp_path / "movie.mp4"
        window._on_progress(self._event("start", index=3, total=10, video=video))
        window._on_progress(self._event("done", index=3, total=10, video=video))
        assert window._overall_bar.value() == 3 * _OVERALL_PROGRESS_SCALE
        assert window._overall_bar.format() == "3 of 10 files"

    @pytest.mark.parametrize("stage", ["skip", "fail"])
    def test_progress_skip_and_fail_advance_overall_bar(self, window, tmp_path, stage):
        video = tmp_path / "movie.mp4"
        window._on_progress(self._event("start", index=2, total=5, video=video))
        window._on_progress(self._event(stage, index=2, total=5, video=video))
        assert window._overall_bar.value() == 2 * _OVERALL_PROGRESS_SCALE
        assert window._overall_bar.format() == "2 of 5 files"

    def test_progress_summary_completes_overall_bar(self, window, tmp_path):
        window._on_progress(self._event("start", index=5, total=5, video=tmp_path / "movie.mp4"))
        window._on_progress(self._event("summary", index=5, total=5, elapsed=1.0))
        assert window._overall_bar.value() == window._overall_bar.maximum() == 5 * _OVERALL_PROGRESS_SCALE

    def test_on_file_progress_sets_file_bar_value_from_fraction(self, window):
        window._on_file_progress(0.43)
        assert window._file_bar.value() == 43

    def test_on_file_progress_advances_overall_bar_with_combined_progress(self, window, tmp_path):
        window._on_progress(self._event("start", index=2, total=5, video=tmp_path / "movie.mp4"))
        window._on_file_progress(0.4)
        assert window._overall_bar.value() == round((1 + 0.4) * _OVERALL_PROGRESS_SCALE)

    def test_on_file_progress_before_start_is_noop_for_overall_bar(self, window):
        window._on_file_progress(0.5)
        assert window._overall_bar.value() == 0
        assert window._overall_bar.format() == "Ready"

    def test_on_model_progress_repurposes_status_label_and_overall_bar(self, window):
        window._on_model_progress(50_000_000, 100_000_000)
        assert "Downloading model" in window._status_label.text()
        assert "medium" in window._status_label.text()
        assert window._overall_bar.minimum() == 0
        # QProgressBar's range is a 32-bit int, so byte counts are scaled to KiB.
        assert window._overall_bar.maximum() == 100_000_000 // 1024
        assert window._overall_bar.value() == 50_000_000 // 1024
        assert window._overall_bar.format() == "50%"

    def test_on_model_progress_shows_downloading_icon(self, window):
        window._on_model_progress(50, 100)
        assert (
            window._model_status_icon.pixmap().cacheKey()
            == window._model_downloading_icon.pixmap(16, 16).cacheKey()
        )

    def test_on_model_progress_with_unknown_total_is_indeterminate(self, window):
        window._on_model_progress(10, 0)
        assert window._overall_bar.minimum() == 0
        assert window._overall_bar.maximum() == 0
        assert window._overall_bar.format() == "Downloading…"

    def test_progress_start_after_model_progress_restores_file_progress_display(self, window, tmp_path):
        window._on_model_progress(100, 100)
        window._on_progress(self._event("start", index=1, total=3, video=tmp_path / "movie.mp4"))
        assert "Processing" in window._status_label.text()
        assert window._overall_bar.maximum() == 3 * _OVERALL_PROGRESS_SCALE

    def test_refresh_model_status_icon_shows_downloaded_when_cached(self, window, mocker):
        mocker.patch("add_subs_to_videos.gui.is_model_downloaded", return_value=True)
        window._refresh_model_status_icon()
        assert "is downloaded" in window._model_status_icon.toolTip()
        assert (
            window._model_status_icon.pixmap().cacheKey()
            == window._done_icon.pixmap(16, 16).cacheKey()
        )

    def test_refresh_model_status_icon_shows_not_downloaded_when_missing(self, window, mocker):
        mocker.patch("add_subs_to_videos.gui.is_model_downloaded", return_value=False)
        window._refresh_model_status_icon()
        assert "will be downloaded" in window._model_status_icon.toolTip()
        assert (
            window._model_status_icon.pixmap().cacheKey()
            == window._model_not_downloaded_icon.pixmap(16, 16).cacheKey()
        )

    def test_changing_model_combo_rechecks_download_status(self, window, mocker):
        mock_is_downloaded = mocker.patch("add_subs_to_videos.gui.is_model_downloaded", return_value=False)
        mock_is_downloaded.reset_mock()
        window._model_combo.setCurrentText("tiny")
        mock_is_downloaded.assert_called_with("tiny")

    def test_on_done_rechecks_model_status_icon(self, window, mocker):
        mocker.patch("add_subs_to_videos.gui.is_model_downloaded", return_value=True)
        window._on_model_progress(50, 100)  # leaves the icon on "downloading"
        window._on_done(True)
        assert (
            window._model_status_icon.pixmap().cacheKey()
            == window._done_icon.pixmap(16, 16).cacheKey()
        )

    def test_run_resets_progress_widgets_to_starting_state(self, window, tmp_path, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui._WorkerThread")
        video = tmp_path / "movie.mp4"
        video.touch()
        window._drop_zone.folder_dropped.emit(tmp_path)
        qtbot.waitUntil(lambda: window._file_table.rowCount() == 1)

        # Dirty up the widgets as if a previous run had completed.
        window._on_progress(self._event("start", index=1, total=2, video=video))
        window._on_progress(self._event("done", index=1, total=2, video=video))
        window._file_logs[video] = ["leftover from previous run"]

        window._run()

        assert window._overall_bar.format() == "Starting…"
        assert window._overall_bar.minimum() == 0
        assert window._overall_bar.maximum() == 1
        assert window._overall_bar.value() == 0
        assert window._file_bar.value() == 0
        assert window._file_bar.format() == ""
        assert window._status_label.text() == "Preparing…"
        assert window._file_logs == {}

        # The rescan that _run() kicks off (so newly-added files are picked
        # up) completes asynchronously and then starts the worker.
        qtbot.waitUntil(lambda: window._counts_label.text() == "1 file(s) to process")

    def test_cancel_button_disabled_initially(self, window):
        assert not window._cancel_btn.isEnabled()

    def test_cancel_button_enabled_while_running(self, window, tmp_path, mocker):
        mocker.patch("add_subs_to_videos.gui._WorkerThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run()
        assert window._cancel_btn.isEnabled()
        assert not window._run_btn.isEnabled()

    def test_cancel_button_enabled_for_rerun_countdown_on_done(self, window, tmp_path):
        window._cancel_btn.setEnabled(False)
        window._on_done(True)
        # Re-enabled so the user can cancel the auto re-run countdown that starts on completion.
        assert window._cancel_btn.isEnabled()

    def test_cancel_button_disabled_on_done_after_manual_cancel(self, window, mocker):
        window._worker = mocker.MagicMock()
        window._cancel_run()
        window._on_done(False)
        assert not window._cancel_btn.isEnabled()

    def test_on_done_starts_rerun_countdown(self, window):
        window._on_done(True)
        assert window._rerun_timer.isActive()
        assert window._run_btn.text() == "Run (auto re-run in 10:00)"
        assert window._run_btn.isEnabled()

    def test_on_done_after_manual_cancel_does_not_start_countdown(self, window, mocker):
        window._worker = mocker.MagicMock()
        window._cancel_run()
        window._on_done(False)
        assert not window._rerun_timer.isActive()
        assert window._run_btn.text() == "Run"

    def test_rerun_tick_decrements_and_updates_button_text(self, window):
        window._on_done(True)
        window._on_rerun_tick()
        assert window._run_btn.text() == "Run (auto re-run in 9:59)"

    def test_rerun_tick_at_zero_triggers_run_again(self, window, mocker):
        window._on_done(True)
        window._rerun_seconds_left = 1
        mock_run = mocker.patch.object(window, "_run")
        window._on_rerun_tick()
        mock_run.assert_called_once()
        assert not window._rerun_timer.isActive()

    def test_cancel_run_during_countdown_stops_it_without_touching_worker(self, window, mocker):
        mock_worker = mocker.MagicMock()
        window._worker = mock_worker
        window._on_done(True)
        window._cancel_run()
        assert not window._rerun_timer.isActive()
        assert window._run_btn.text() == "Run"
        assert not window._cancel_btn.isEnabled()
        mock_worker.cancel.assert_not_called()

    def test_run_during_countdown_stops_it_and_shows_running(self, window, tmp_path, mocker):
        mocker.patch("add_subs_to_videos.gui._WorkerThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._on_done(True)
        window._run()
        assert not window._rerun_timer.isActive()
        assert window._run_btn.text() == "Running"

    def test_clear_selection_during_countdown_stops_it(self, window, tmp_path):
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._on_done(True)
        window._clear_selection()
        assert not window._rerun_timer.isActive()
        assert window._run_btn.text() == "Run"

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

    def test_cancel_run_shows_cancelling_status(self, window, mocker):
        window._worker = mocker.MagicMock()
        window._cancel_run()
        assert window._status_label.text() == "Cancelling…"

    # -----------------------------------------------------------------------
    # "Files to process" table section
    # -----------------------------------------------------------------------

    def test_file_table_hidden_and_empty_initially(self, window):
        assert window._tree_label.isHidden()
        assert window._scan_message.isHidden()
        assert window._file_table.isHidden()
        assert window._file_table.rowCount() == 0

    def test_folder_set_shows_scanning_placeholder(self, window, tmp_path, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        assert not window._tree_label.isHidden()
        assert not window._scan_message.isHidden()
        assert window._scan_message.text() == "Scanning…"
        assert window._file_table.isHidden()

    def test_tree_ready_populates_table(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        files = [tmp_video_dir / "movie.mp4", tmp_video_dir / "sub" / "episode.mp4"]
        window._on_tree_ready(token, files)

        assert window._scan_message.isHidden()
        assert not window._file_table.isHidden()
        assert window._file_table.rowCount() == 2
        assert window._file_table.item(0, 0).text() == "movie.mp4"
        assert window._file_table.item(0, 1).text() == "Pending"
        assert window._file_table.item(1, 0).text() == str(Path("sub") / "episode.mp4")
        assert window._file_row_by_path == {files[0]: 0, files[1]: 1}

    def test_tree_ready_with_no_files_shows_message(self, window, tmp_path, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        token = window._tree_scan_token
        window._on_tree_ready(token, [])
        assert window._scan_message.text() == "(no video files found)"
        assert not window._scan_message.isHidden()
        assert window._file_table.isHidden()

    def test_stale_tree_result_ignored(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        stale_token = window._tree_scan_token
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        window._on_tree_ready(stale_token, [tmp_video_dir / "movie.mp4"])
        assert window._scan_message.text() == "Scanning…"
        assert window._file_table.rowCount() == 0

    def test_clear_selection_clears_and_hides_table(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        window._on_tree_ready(token, [tmp_video_dir / "movie.mp4"])
        window._clear_btn.click()
        assert window._tree_label.isHidden()
        assert window._scan_message.isHidden()
        assert window._file_table.isHidden()
        assert window._file_table.rowCount() == 0
        assert window._file_row_by_path == {}

    def test_folder_dropped_populates_table_end_to_end(self, window, tmp_video_dir, qtbot):
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        qtbot.waitUntil(lambda: window._file_table.rowCount() > 0, timeout=5000)
        names = [window._file_table.item(r, 0).text() for r in range(window._file_table.rowCount())]
        assert "movie.mp4" in names
        assert "show.mkv" in names
        assert all(window._file_table.item(r, 1).text() == "Pending" for r in range(window._file_table.rowCount()))

    def test_progress_event_updates_file_status(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        video = tmp_video_dir / "movie.mp4"
        window._on_tree_ready(token, [video])

        window._on_progress(ProgressEvent(stage="start", index=1, total=1, video=video, done=0, skipped=0, failed=0))
        assert window._file_table.item(0, 1).text() == "Processing"

        window._on_progress(ProgressEvent(stage="done", index=1, total=1, video=video, done=1, skipped=0, failed=0))
        assert window._file_table.item(0, 1).text() == "Done"

    def test_tree_ready_adds_logs_column_with_tooltip(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        video = tmp_video_dir / "movie.mp4"
        window._on_tree_ready(token, [video])

        item = window._file_table.item(0, 2)
        assert item is not None
        assert item.toolTip() == ""
        assert window._path_by_row == {0: video}

        window._on_log_line(video, "[00:00 --> 00:02] hello")
        assert item.toolTip() == "Click to read logs"

    def test_on_log_line_buckets_lines_by_video(self, window, tmp_path):
        video = tmp_path / "movie.mp4"
        window._on_log_line(video, "[00:00 --> 00:02] hello")
        window._on_log_line(None, "global line")
        window._on_log_line(video, "[00:02 --> 00:04] world")
        assert window._file_logs == {video: ["[00:00 --> 00:02] hello", "[00:02 --> 00:04] world"]}

    def test_clicking_logs_cell_opens_dialog_with_captured_lines(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        video = tmp_video_dir / "movie.mp4"
        window._on_tree_ready(token, [video])
        window._on_log_line(video, "[00:00 --> 00:02] hello")

        from PySide6.QtWidgets import QDialog, QPlainTextEdit

        created = []
        original_init = QDialog.__init__

        def capture_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created.append(self)

        mocker.patch.object(QDialog, "__init__", capture_init)
        window._on_file_table_cell_clicked(0, 2)

        assert len(created) == 1
        dialog = created[0]
        assert video.name in dialog.windowTitle()
        text_edit = dialog.findChild(QPlainTextEdit)
        assert "[00:00 --> 00:02] hello" in text_edit.toPlainText()
        dialog.close()

    def test_clicking_logs_cell_with_no_logs_shows_placeholder(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        video = tmp_video_dir / "movie.mp4"
        window._on_tree_ready(token, [video])

        from PySide6.QtWidgets import QPlainTextEdit

        window._on_file_table_cell_clicked(0, 2)
        dialogs = window.findChildren(QPlainTextEdit)
        assert dialogs
        assert dialogs[-1].toPlainText() == "No logs captured yet."
        dialogs[-1].parent().close()

    def test_clicking_non_logs_column_does_nothing(self, window, tmp_video_dir, mocker):
        mocker.patch("add_subs_to_videos.gui._FileScanThread")
        window._drop_zone.folder_dropped.emit(tmp_video_dir)
        token = window._tree_scan_token
        video = tmp_video_dir / "movie.mp4"
        window._on_tree_ready(token, [video])

        from PySide6.QtWidgets import QDialog

        before = len(window.findChildren(QDialog))
        window._on_file_table_cell_clicked(0, 0)
        assert len(window.findChildren(QDialog)) == before

    def test_run_clears_file_logs(self, window, tmp_path, mocker):
        mocker.patch("add_subs_to_videos.gui._WorkerThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._file_logs[tmp_path / "old.mp4"] = ["stale"]
        window._run()
        assert window._file_logs == {}

    def test_run_rescans_and_picks_up_file_added_after_initial_scan(self, window, tmp_path, mocker, qtbot):
        mocker.patch("add_subs_to_videos.gui._WorkerThread")
        (tmp_path / "first.mp4").touch()
        window._drop_zone.folder_dropped.emit(tmp_path)
        qtbot.waitUntil(lambda: window._file_table.rowCount() == 1)

        # Simulate a file dropped into the watched folder while idle/counting down.
        (tmp_path / "second.mp4").touch()

        window._run()

        qtbot.waitUntil(lambda: window._file_table.rowCount() == 2)
        assert window._counts_label.text() == "2 file(s) to process"

    def test_run_starts_worker_only_after_rescan_completes(self, window, tmp_path, mocker, qtbot):
        mock_worker_cls = mocker.patch("add_subs_to_videos.gui._WorkerThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        qtbot.waitUntil(lambda: window._counts_label.text() != "")

        window._run()
        assert window._pending_run
        mock_worker_cls.assert_not_called()

        qtbot.waitUntil(lambda: mock_worker_cls.return_value.start.called)
        assert not window._pending_run

    def test_cancel_during_rescan_aborts_before_worker_starts(self, window, tmp_path, mocker):
        mock_worker_cls = mocker.patch("add_subs_to_videos.gui._WorkerThread")
        window._drop_zone.folder_dropped.emit(tmp_path)
        window._run()
        assert window._pending_run

        window._cancel_run()

        assert not window._pending_run
        assert window._run_btn.text() == "Run"
        assert window._run_btn.isEnabled()
        assert not window._cancel_btn.isEnabled()
        mock_worker_cls.assert_not_called()


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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_calls_ensure_bundled_ffmpeg_on_path(mocker):
    from add_subs_to_videos import gui

    ensure = mocker.patch("add_subs_to_videos.gui.ensure_bundled_ffmpeg_on_path")
    mocker.patch("add_subs_to_videos.gui.QApplication")
    mocker.patch("add_subs_to_videos.gui._dev_icon_path", return_value=None)
    mocker.patch("add_subs_to_videos.gui.MainWindow")
    mocker.patch("add_subs_to_videos.gui.sys.exit")

    gui.main()

    ensure.assert_called_once()
