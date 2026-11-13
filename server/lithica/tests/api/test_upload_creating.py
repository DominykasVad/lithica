import base64
import os
from collections.abc import Callable
from unittest.mock import patch

import pytest

from lithica import errors, model
from lithica.api import resources
from lithica.func import file_uploads, net
from lithica.tests.api.http import assert_error, assert_fits, enabled_config, ok
from lithica.tests.conftest import ApiClient


@pytest.fixture(autouse=True)
def inject_config(config_injector, tmpdir):
    config_injector(
        enabled_config(
            {
                "data_dir": str(tmpdir),
                "privileges": {
                    "uploads:create": model.User.RANK_REGULAR,
                    "uploads:use_downloader": model.User.RANK_POWER,
                },
            }
        )
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


def _temporary_files(tmpdir) -> list[str]:
    return os.listdir(os.path.join(str(tmpdir), "temporary-uploads", ".tmp"))


def test_large_upload_is_renamed_into_place(client, user_factory, tmpdir, monkeypatch):
    from lithica.func import content as content_module

    copies = []
    real_copyfile = content_module.shutil.copyfile

    def recording_copyfile(*args):
        copies.append(args)
        return real_copyfile(*args)

    monkeypatch.setattr(content_module.shutil, "copyfile", recording_copyfile)
    content = os.urandom(2 * 1024 * 1024 + 5)
    result = ok(
        client.post(
            "/uploads",
            user=user_factory(rank=model.User.RANK_REGULAR),
            files={"content": content},
        )
    )
    stored = os.path.join(str(tmpdir), "temporary-uploads", result["token"] + ".dat")
    with open(stored, "rb") as handle:
        assert handle.read() == content
    # written once, in the data directory, then renamed: never copied
    assert copies == []
    # readable like any stored file, not private like a temporary one
    assert os.stat(stored).st_mode & 0o777 == content_module.STORED_FILE_MODE
    assert _temporary_files(tmpdir) == []


def test_failed_large_upload_leaves_nothing_behind(client, user_factory, tmpdir):
    assert_error(
        client.post(
            "/uploads",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            files={"content": os.urandom(2 * 1024 * 1024)},
        ),
        errors.AuthError,
    )
    # refused before the body was read: not even the folder was made
    assert not os.path.exists(os.path.join(str(tmpdir), "temporary-uploads"))


def test_base64_upload(
    client: ApiClient, user_factory: Callable[..., model.User]
) -> None:
    from lithica import config

    config.config["max_upload_size"] = 2 * 1024 * 1024
    config.config["max_base64_upload_size"] = 2 * 1024 * 1024
    content = b"x" * (2 * 1024 * 1024)
    result = ok(
        client.post(
            "/uploads",
            user=user_factory(rank="regular"),
            body={"contentBase64": base64.b64encode(content).decode()},
        )
    )
    assert file_uploads.get(result["token"]) == content


@pytest.mark.parametrize(
    "encoded", ["a", "YWJj\n", "YQ", "YQ=", "data:;base64,YQ==", "____", 123]
)
def test_bad_base64(
    client: ApiClient, user_factory: Callable[..., model.User], encoded: object
) -> None:
    assert_error(
        client.post(
            "/uploads",
            user=user_factory(rank="regular"),
            body={"contentBase64": encoded},
        ),
        errors.ValidationError,
    )


@pytest.mark.parametrize("source", ["file", "url"])
def test_base64_excludes_other_sources(
    client: ApiClient, user_factory: Callable[..., model.User], source: str
) -> None:
    body = {"contentBase64": "YQ=="}
    files = {"content": b"a"} if source == "file" else None
    if source == "url":
        body["contentUrl"] = "https://example.com/a"
    assert_error(
        client.post(
            "/uploads", user=user_factory(rank="regular"), body=body, files=files
        ),
        errors.ValidationError,
    )


def test_base64_decoded_limit_and_empty(
    client: ApiClient, user_factory: Callable[..., model.User]
) -> None:
    from lithica import config

    config.config["max_base64_upload_size"] = 1
    user = user_factory(rank="regular")
    response = client.post("/uploads", user=user, body={"contentBase64": "YWI="})
    assert response.status_code == 413
    assert response.json()["name"] == "RequestTooLargeError"
    assert_error(
        client.post("/uploads", user=user, body={"contentBase64": ""}),
        errors.MissingRequiredFileError,
    )


def test_posts_ignore_base64(
    client: ApiClient, user_factory: Callable[..., model.User]
) -> None:
    from lithica import config

    config.config["privileges"]["posts:create:identified"] = "regular"
    assert_error(
        client.post(
            "/posts",
            user=user_factory(rank="regular"),
            body={"contentBase64": "YQ==", "safety": "safe"},
        ),
        errors.MissingRequiredFileError,
    )
