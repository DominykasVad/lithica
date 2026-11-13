"""Replacing uploaded cards preserves history and keeps pictures deliberately."""

import pytest

from lithica import config, db, model
from lithica.func import documents, files, posts, util
from lithica.tests.api.http import ok
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_upload_documents import upload


@pytest.fixture(autouse=True)
def picture_privilege(site):
    config.config["privileges"]["posts:edit:typed_relations"] = "regular"


def replace(client, user, post_id, content, **body):
    response = client.put(
        f"/modules/cards/post/{post_id}/file",
        user=user,
        body={"version": posts.get_post_by_id(post_id).version, **body},
        files={"content": content},
    )
    if response.status_code >= 400:
        # The fixture shares a session; emulate request-close rollback.
        db.session.rollback()
    return response


@pytest.mark.parametrize("keep,shade", [(True, 80), (True, 0), (False, 80)])
def test_png_replace(site, user, keep, shade):
    client = site(["cards"])
    original = cards.png_card(cards.v2_card(), shade=0)
    post_id = upload(client, user, cards.v2_card(), safety="unsafe", tags=["nsfw"])
    old_checksum = util.get_sha1(original)
    result = ok(
        replace(
            client,
            user,
            post_id,
            cards.png_card(cards.v2_card(name="New"), shade=shade),
            keepOldPicture=keep,
        )
    )
    post = posts.get_post_by_id(post_id)
    assert post.version == 2 and post.last_edit_time is not None
    assert documents.get(post).version == 1
    assert documents.get_version(post, 1).note == "File replaced."
    assert documents.get_version(post, 0).data
    assert result["samePicture"] == (shade == 0)
    kept_id = result["keptPostId"]
    if keep and shade != 0:
        kept = posts.get_post_by_id(kept_id)
        assert kept.kind == "media" and not kept.listed and kept.safety == "unsafe"
        assert kept.user_id == user.user_id
        assert [t.first_name for t in kept.tags] == ["nsfw"]
        assert kept.contents and db.session.get(model.PostDocument, kept_id) is None
        assert files.get(posts.get_post_content_path(kept)) == original
        relations = (
            db.session.query(model.PostTypedRelation)
            .filter_by(from_post_id=kept_id)
            .all()
        )
        assert {(r.to_post_id, r.type) for r in relations} == {
            (post_id, "avatar-of"),
            (post_id, "gallery-of"),
        }
        assert db.session.get(model.PostRetiredChecksum, old_checksum) is None
    else:
        assert kept_id is None
        assert (
            db.session.get(model.PostRetiredChecksum, old_checksum).post_id == post_id
        )


def test_identical_data_changes_file_only(site, user):
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    result = ok(
        replace(client, user, post_id, cards.png_card(cards.v2_card(), shade=80))
    )
    assert result["keptPostId"] is not None
    assert documents.get(posts.get_post_by_id(post_id)).version == 0


@pytest.mark.parametrize("mode", ["same", "plain", "duplicate", "stale"])
def test_refusal_changes_nothing(site, user, mode):
    client = site(["cards"])
    original = cards.png_card(cards.v2_card())
    post_id = upload(client, user, cards.v2_card())
    post = posts.get_post_by_id(post_id)
    before = files.get(posts.get_post_content_path(post))
    assert before is not None
    before_bytes = before.read()
    new = cards.png_card(cards.v2_card(name="New"), shade=80)
    body = {}
    if mode == "same":
        new = original
    elif mode == "plain":
        new = cards.picture(80)
    elif mode == "duplicate":
        upload(client, user, cards.v2_card(name="New"), shade=80)
    else:
        body["version"] = 0
    count = db.session.query(model.Post).count()
    response = replace(client, user, post_id, new, **body)
    assert response.status_code == (409 if mode == "stale" else 400), response.text
    post = posts.get_post_by_id(post_id)
    assert post.version == 1 and documents.get(post).version == 0
    assert files.get(posts.get_post_content_path(post)) == before_bytes
    assert db.session.query(model.Post).count() == count


def test_charx_to_png_and_back(site, user):
    client = site(["cards"])
    post_id = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.charx(icon=cards.picture(30))},
        )
    )["id"]
    post = posts.get_post_by_id(post_id)
    old_path = posts.get_post_content_path(post)
    original_checksum = post.checksum
    result = ok(
        replace(client, user, post_id, cards.png_card(cards.v2_card(), shade=80))
    )
    assert result["keptPostId"] is not None
    assert not files.has(old_path)
    assert (
        db.session.get(model.PostRetiredChecksum, original_checksum).reason
        == "replaced"
    )
    png_path = posts.get_post_content_path(post)
    ok(replace(client, user, post_id, cards.charx(icon=None), keepOldPicture=False))
    assert not files.has(png_path)
    assert files.has(posts.get_post_content_path(post))
