from unittest.mock import patch

import pytest

from lithica import errors, model
from lithica.api import resources
from lithica.func import file_uploads, net
from lithica.tests.api.http import assert_error, assert_fits, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector, tmpdir):
    config_injector(
        {
            "data_dir": str(tmpdir),
            "privileges": {
                "uploads:create": model.User.RANK_REGULAR,
                "uploads:use_downloader": model.User.RANK_POWER,
            },
        }
    )


def test_uploading_a_file(client, user_factory):
    content = bytes(range(256)) * 16
    result = ok(
        client.post(
            "/uploads",
            user=user_factory(rank=model.User.RANK_REGULAR),
            files={"content": content},
        )
    )
    assert_fits(resources.UploadToken, result)
    assert file_uploads.get(result["token"]) == content


def test_uploading_the_same_file_twice_gives_the_same_token(client, user_factory):
    user = user_factory(rank=model.User.RANK_REGULAR)
    first = ok(client.post("/uploads", user=user, files={"content": b"content"}))
    second = ok(client.post("/uploads", user=user, files={"content": b"content"}))
    other = ok(client.post("/uploads", user=user, files={"content": b"other"}))
    assert first["token"] == second["token"]
    assert first["token"] != other["token"]


def test_uploading_from_url(client, user_factory):
    with patch("lithica.func.net.download"):
        net.download.return_value = b"downloaded"
        result = ok(
            client.post(
                "/uploads",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={"contentUrl": "http://example.com/image.png"},
            )
        )
        net.download.assert_called_once_with(
            "http://example.com/image.png", use_video_downloader=False
        )
    assert file_uploads.get(result["token"]) == b"downloaded"


def test_video_downloader_needs_its_own_privilege(client, user_factory):
    with patch("lithica.func.net.download"):
        net.download.return_value = b"downloaded"
        ok(
            client.post(
                "/uploads",
                user=user_factory(rank=model.User.RANK_POWER),
                body={"contentUrl": "http://example.com/video"},
            )
        )
        net.download.assert_called_once_with(
            "http://example.com/video", use_video_downloader=True
        )


def test_token_of_an_earlier_upload_is_not_content(client, user_factory):
    user = user_factory(rank=model.User.RANK_REGULAR)
    token = ok(client.post("/uploads", user=user, files={"content": b"content"}))[
        "token"
    ]
    assert_error(
        client.post("/uploads", user=user, body={"contentToken": token}),
        errors.MissingRequiredFileError,
        "Required file 'content' is missing.",
    )


def test_trying_to_upload_nothing(client, user_factory):
    assert_error(
        client.post("/uploads", user=user_factory(rank=model.User.RANK_REGULAR)),
        errors.MissingRequiredFileError,
    )


def test_trying_to_upload_without_privileges(client, user_factory):
    assert_error(
        client.post(
            "/uploads",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            files={"content": b"content"},
        ),
        errors.AuthError,
    )
    assert list(file_uploads.files.scan("temporary-uploads")) == []
