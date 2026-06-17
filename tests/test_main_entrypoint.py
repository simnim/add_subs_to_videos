from __future__ import annotations

import runpy


def test_main_module_invokes_cli_main(mocker):
    mock_main = mocker.patch("add_subs_to_videos.cli.main")
    runpy.run_module("add_subs_to_videos.__main__", run_name="__main__")
    mock_main.assert_called_once()
