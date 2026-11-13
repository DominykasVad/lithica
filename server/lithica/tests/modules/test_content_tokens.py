"""Every temporary-upload consumer shares token validation and missing errors."""

from collections.abc import Callable

import pytest

from lithica import config, errors, model
from lithica.func import file_uploads, files, posts, util
from lithica.tests.api.http import assert_error, ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_upload_documents import upload


@pytest.fixture
def token_site(
    site: Callable[[list[str]], ApiClient], user: model.User
) -> tuple[ApiClient, int, int]:
    client = site(["cards"])
    config.config["privileges"].update(
        {
            "uploads:create": "regular",
            "posts:reverse_search": "regular",
            "posts:edit:safety": "regular",
        }
    )
    media_id = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.picture(0)},
        )
    )["id"]
    card_id = upload(client, user, cards.v2_card())
    return client, media_id, card_id


ROUTES = [
    ("POST", "/posts"),
    ("PUT", "/post/{post_id}"),
    ("POST", "/posts/reverse-search"),
    ("PUT", "/modules/cards/post/{post_id}/file"),
    ("POST", "/modules/cards/file-picture"),
]


@pytest.mark.parametrize("method,route", ROUTES)
@pytest.mark.parametrize(
    "token",
    [
        "../secret",
        "../../secret",
        "/absolute/secret",
        "A" * 40,
        "a" * 39,
        "a" * 41,
        "a" * 40 + "\n",
        "0" * 40,
    ],
)
def test_missing_or_invalid_content_token(
    token_site: tuple[ApiClient, int, int],
    user: model.User,
    method: str,
    route: str,
    token: str,
) -> None:
    client, media_id, card_id = token_site
    if token != "0" * 40:
        # Seed the exact path the old lookup used: invalid tokens must be
        # refused even when the referenced .dat file exists and is usable.
        files.save(
            f"temporary-uploads/{token}.dat", cards.png_card(cards.v2_card(name="New"))
        )
    response = client.request(
        method,
        route.format(post_id=card_id if route.startswith("/modules") else media_id),
        user=user,
        body={"contentToken": token, "version": 1, "safety": "safe"},
    )
    assert_error(
        response, errors.MissingRequiredFileError, "Required file 'content' is missing."
    )


@pytest.mark.parametrize("method,route", ROUTES)
def test_saved_content_token_works(
    token_site: tuple[ApiClient, int, int],
    user: model.User,
    method: str,
    route: str,
) -> None:
    client, media_id, card_id = token_site
    card = (
        cards.v2_card()
        if route.endswith("reverse-search")
        else cards.v2_card(name="New")
    )
    content = cards.png_card(card)
    token = file_uploads.save(content)
    response = client.request(
        method,
        route.format(post_id=card_id if route.startswith("/modules") else media_id),
        user=user,
        body={"contentToken": token, "version": 1, "safety": "safe"},
    )
    if route.endswith("file-picture"):
        assert response.status_code == 200, response.text
        assert response.content == content
    elif route.endswith("reverse-search"):
        assert ok(response)["exactPost"]["id"] == card_id
    else:
        result = ok(response)
        post_id = result["post"]["id"] if route.endswith("/file") else result["id"]
        post = posts.get_post_by_id(post_id)
        assert post.checksum == util.get_sha1(content)
        assert files.get(posts.get_post_content_path(post)) == content
