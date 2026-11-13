"""Read-only picture comparison and temporary card picture responses."""

from pathlib import Path

import pytest

from lithica import config, db, model
from lithica.func import file_uploads
from lithica.tests.api.http import ok
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_upload_documents import upload


@pytest.mark.parametrize(
    "new,old_picture,new_picture,same",
    [
        (cards.png_card(cards.v2_card(name="New")), True, True, True),
        (cards.png_card(cards.v2_card(name="New"), shade=80), True, True, False),
        (cards.charx(icon=None), True, False, False),
    ],
)
def test_compare_writes_nothing(site, user, new, old_picture, new_picture, same):
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    root = Path(config.config["data_dir"])
    before = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    counts = {
        table: db.session.query(table).count()
        for table in (
            model.Post,
            model.PostDocumentVersion,
            model.Snapshot,
            model.PostContent,
        )
    }
    answer = ok(
        client.post(
            f"/modules/cards/post/{post_id}/file/compare",
            user=user,
            files={"content": new},
        )
    )
    assert answer["samePixels"] is same
    assert answer["oldPicture"] is old_picture
    assert answer["newPicture"] is new_picture
    assert (answer["similarity"] is None) is (not (old_picture and new_picture))
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before
    assert {table: db.session.query(table).count() for table in counts} == counts


@pytest.mark.parametrize("form", ["png", "charx", "no-picture"])
def test_picture_response(site, user, form):
    client = site(["cards"])
    config.config["privileges"]["uploads:create"] = "regular"
    picture = cards.png_card(cards.v2_card()) if form == "png" else cards.picture(30)
    content = (
        picture
        if form == "png"
        else cards.charx(icon=picture if form == "charx" else None)
    )
    token = file_uploads.save(content)
    response = client.post(
        "/modules/cards/file-picture",
        user=user,
        body={"contentToken": token},
        headers={"Accept": "image/png"},
    )
    if form == "no-picture":
        assert response.status_code == 404
    else:
        assert response.status_code == 200, response.text
        assert response.content == picture
        assert response.headers["Content-Type"] == "image/png"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert (
            response.headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
        )
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "route,privilege",
    [
        ("/file-picture", "uploads:create"),
        ("/post/1/file/compare", "posts:edit:content"),
    ],
)
def test_preview_privileges(site, user, route, privilege):
    client = site(["cards"])
    config.config["privileges"][privilege] = "administrator"
    response = client.post(
        "/modules/cards" + route, user=user, body={"contentToken": "0" * 40}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("token", ["../secret", "", "0" * 40])
def test_picture_missing_or_invalid_token(site, user, token):
    client = site(["cards"])
    config.config["privileges"]["uploads:create"] = "regular"
    response = client.post(
        "/modules/cards/file-picture", user=user, body={"contentToken": token}
    )
    assert response.status_code == 400


@pytest.mark.parametrize("also_body", [False, True])
def test_picture_never_accepts_query_token(site, user, also_body):
    client = site(["cards"])
    config.config["privileges"]["uploads:create"] = "regular"
    token = file_uploads.save(cards.png_card(cards.v2_card()))
    response = client.post(
        "/modules/cards/file-picture",
        user=user,
        query={"contentToken": token},
        body={"contentToken": token} if also_body else None,
    )
    assert response.status_code == 400
    assert response.json()["description"] == (
        "This route accepts contentToken only in the request body."
    )
