import subprocess
from unittest.mock import patch

import pytest

from lithica import errors
from lithica.func import images


def test_ffmpeg_is_run_without_a_shell(read_asset):
    real_popen = subprocess.Popen
    calls = []

    def recording_popen(cli, **kwargs):
        calls.append((cli, kwargs))
        return real_popen(cli, **kwargs)

    with patch("subprocess.Popen", side_effect=recording_popen):
        image = images.Image(read_asset("png.png"))
    assert image.width > 0 and image.height > 0
    assert calls
    for cli, kwargs in calls:
        assert isinstance(cli, list)
        assert all(isinstance(part, str) for part in cli)
        assert cli[0] in ("ffmpeg", "ffprobe")
        assert not kwargs.get("shell")
        assert kwargs["stdin"] == subprocess.DEVNULL


def test_ffmpeg_is_killed_on_timeout(read_asset):
    with patch("subprocess.Popen") as popen:
        proc = popen.return_value
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
            (b"", b""),
        ]
        with pytest.raises(errors.ProcessingError, match="took too long"):
            images.Image(read_asset("png.png"))
    proc.kill.assert_called_once_with()
    assert proc.communicate.call_args_list[0].kwargs == {
        "timeout": images.FFMPEG_TIMEOUT
    }


def test_slow_ffmpeg_fails_the_request(read_asset, monkeypatch):
    # a real process that outlives the limit: "sleep" stands in for ffprobe
    monkeypatch.setattr(images, "FFMPEG_TIMEOUT", 0.2)
    real_popen = subprocess.Popen

    def sleeping_popen(cli, **kwargs):
        return real_popen(["sleep", "30"], **kwargs)

    with patch("subprocess.Popen", side_effect=sleeping_popen):
        with pytest.raises(errors.ProcessingError, match="took too long"):
            images.Image(read_asset("png.png"))
