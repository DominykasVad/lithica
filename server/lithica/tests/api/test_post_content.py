"""The content pipeline, from an upload over HTTP to the rows of the post."""

import logging
from datetime import datetime
from unittest.mock import patch

import pytest

from lithica import db, model, registry
from lithica.func import posts, tags
from lithica.tests.api.http import ok

EXTRACTED_AT = datetime(2020, 2, 3, 4, 5, 6)


def _extract(mime_type, handle):
    data = handle.read()
    yield registry.ExtractedContent(
        "probe_file", {"mimeType": mime_type, "size": len(data)}
    )
    if mime_type == "image/png":
        yield registry.ExtractedContent("probe_png", {"header": data[1:4].decode()})


def _auto_tag(contents):
    mime_types = [
        content.payload["mimeType"]
        for content in contents
        if "mimeType" in content.payload
    ]
    return {
        "meta": ["probed"] + ["is_" + mime.split("/")[1] for mime in mime_types],
        "no_such_category": ["orphan"],
    }


def _probe_module(extract=_extract, auto_tag=_auto_tag, version=7):
    return registry.Module(
        name="probe",
        content_kinds=[
            registry.ContentKind("probe_file", schema_version=version),
            registry.ContentKind("probe_png"),
        ],
        extractors=[
            registry.Extractor(frozenset({"image/png", "image/jpeg"}), extract)
        ],
        auto_tag=auto_tag,
    )


@pytest.fixture(autouse=True)
def site(config_injector, tmpdir, tag_category_factory, fake_datetime):
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "data_url": "http://example.com/data/",
            "secret": "test",
            "allow_broken_uploads": False,
            "delete_source_files": True,
            "thumbnails": {
                "post_width": 300,
                "post_height": 300,
                "avatar_width": 30,
                "avatar_height": 30,
            },
            "convert": {"gif": {"to_mp4": False, "to_webm": False}},
            "tag_name_regex": r"^\S+$",
            "webhooks": [],
            "privileges": {
                "posts:create:identified": model.User.RANK_REGULAR,
                "posts:edit:content": model.User.RANK_REGULAR,
                "posts:edit:tags": model.User.RANK_REGULAR,
                "posts:edit:safety": model.User.RANK_REGULAR,
                "posts:merge": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
                "uploads:use_downloader": model.User.RANK_POWER,
                # nobody in these tests may create a tag by hand
                "tags:create": model.User.RANK_ADMINISTRATOR,
                "users:edit:any:email": model.User.RANK_MODERATOR,
            },
        }
    )
    db.session.add_all(
        [
            tag_category_factory(name="default", default=True),
            tag_category_factory(name="meta"),
        ]
    )
    db.session.flush()
    with fake_datetime(EXTRACTED_AT):
        yield


@pytest.fixture
def user(user_factory):
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    return user


def _upload(client, user, asset, tags=()):
    created = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": list(tags)},
            files={"content": asset},
            query={"fields": "id,version,tags"},
        )
    )
    return created


def _contents(post_id):
    db.session.expire_all()
    return [
        (content.kind, content.schema_version, content.payload)
        for content in posts.get_post_by_id(post_id).contents
    ]


def _tags(post_id):
    db.session.expire_all()
    return {
        tag.first_name: tag.category.name for tag in posts.get_post_by_id(post_id).tags
    }


def test_upload_without_modules_stores_no_content(client, user, read_asset):
    created = _upload(client, user, read_asset("png.png"))
    assert _contents(created["id"]) == []
    assert created["tags"] == []


def test_upload_runs_the_extractors(client, user, read_asset):
    registry.use([_probe_module(auto_tag=None)])
    asset = read_asset("png.png")
    created = _upload(client, user, asset)

    assert _contents(created["id"]) == [
        ("probe_file", 7, {"mimeType": "image/png", "size": len(asset)}),
        ("probe_png", 1, {"header": "PNG"}),
    ]
    rows = posts.get_post_by_id(created["id"]).contents
    assert {row.extracted_at for row in rows} == {EXTRACTED_AT}
    assert created["tags"] == []


def test_upload_of_a_type_no_extractor_reads(client, user, read_asset):
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("gif.gif"))
    assert _contents(created["id"]) == []
    assert created["tags"] == []


def test_failing_extractor_does_not_fail_the_upload(client, user, read_asset, caplog):
    def broken(_mime_type, _handle):
        raise ValueError("not what I expected")

    registry.use([_probe_module(extract=broken)])
    with caplog.at_level(logging.ERROR):
        created = _upload(client, user, read_asset("png.png"), tags=[])
    assert _contents(created["id"]) == []
    assert created["tags"] == []
    assert "An extractor of module 'probe' failed" in caplog.text
    # the post is whole: it can be fetched and has its file
    assert ok(client.get("/post/%d" % created["id"], user=user))["mimeType"] == (
        "image/png"
    )


def test_upload_adds_the_tags_of_the_modules(client, user, read_asset, tag_factory):
    existing = tag_factory(names=["is_png", "png_file"])
    db.session.add(existing)
    db.session.flush()
    registry.use([_probe_module()])

    # the uploader may not create tags; the module's tags are not theirs
    created = _upload(client, user, read_asset("png.png"), tags=["PNG_FILE"])

    assert _tags(created["id"]) == {
        # asked for by the uploader and wanted by the module: once, and the
        # existing tag keeps its category
        "is_png": existing.category.name,
        # created in the category the module names
        "probed": "meta",
        # the site has no such category: the default one
        "orphan": "default",
    }
    assert {tag["names"][0] for tag in created["tags"]} == {
        "is_png",
        "probed",
        "orphan",
    }


def test_tags_created_for_a_module_are_in_the_history(client, user, read_asset):
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("png.png"))
    db.session.expire_all()
    snapshots = {
        (snapshot.resource_type, snapshot.resource_name): snapshot
        for snapshot in db.session.query(model.Snapshot)
    }
    assert set(snapshots) == {
        ("post", str(created["id"])),
        ("tag", "probed"),
        ("tag", "is_png"),
        ("tag", "orphan"),
    }
    assert {snapshot.user_id for snapshot in snapshots.values()} == {user.user_id}
    assert snapshots["tag", "probed"].data["category"] == "meta"
    assert sorted(snapshots["post", str(created["id"])].data["tags"]) == [
        "is_png",
        "orphan",
        "probed",
    ]


def test_failing_auto_tag_hook_does_not_fail_the_upload(client, user, read_asset):
    def broken(_contents):
        raise RuntimeError("no")

    registry.use([_probe_module(auto_tag=broken)])
    created = _upload(client, user, read_asset("png.png"))
    assert created["tags"] == []
    assert len(_contents(created["id"])) == 2


def _update(client, user, post_id, version, **kwargs):
    return ok(
        client.put(
            "/post/%d" % post_id,
            user=user,
            query={"fields": "id,version,tags"},
            **{"body": {"version": version}, **kwargs},
        )
    )


def test_tags_that_cannot_be_created_do_not_fail_the_upload(
    client, user, read_asset, caplog
):
    registry.use([_probe_module()])
    refused = tags.InvalidTagNameError("Name is taken by something else.")
    real = tags.get_or_create_tags_by_names

    def create_all_but_one(names):
        if names == ["is_png"]:
            raise refused
        return real(names)

    with (
        patch.object(tags, "get_or_create_tags_by_names", create_all_but_one),
        caplog.at_level(logging.WARNING),
    ):
        created = _upload(client, user, read_asset("png.png"))

    # what was added before the failure stays, the rest is given up
    assert [tag["names"][0] for tag in created["tags"]] == ["probed"]
    assert len(_contents(created["id"])) == 2
    assert "Automatic tags were not all added: Name is taken" in caplog.text


def test_new_content_replaces_the_extracted_content(client, user, read_asset):
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("png.png"))
    # a row of a module that has been switched off since
    post = posts.get_post_by_id(created["id"])
    post.contents.append(
        model.PostContent(
            kind="gone_v1", schema_version=1, payload={}, extracted_at=EXTRACTED_AT
        )
    )
    db.session.commit()
    old_ids = {row.post_content_id for row in post.contents}

    jpeg = read_asset("jpeg.jpg")
    updated = _update(
        client, user, created["id"], created["version"], files={"content": jpeg}
    )

    assert _contents(created["id"]) == [
        ("probe_file", 7, {"mimeType": "image/jpeg", "size": len(jpeg)}),
    ]
    new_ids = {
        row.post_content_id for row in posts.get_post_by_id(created["id"]).contents
    }
    assert not old_ids & new_ids
    assert db.session.query(model.PostContent).count() == 1
    # tags from the old content stay, the new content adds its own
    assert {tag["names"][0] for tag in updated["tags"]} == {
        "probed",
        "is_png",
        "orphan",
        "is_jpeg",
    }
    assert ("tag", "is_jpeg") in {
        (snapshot.resource_type, snapshot.resource_name)
        for snapshot in db.session.query(model.Snapshot)
    }


def test_new_content_and_new_tags_in_one_request(client, user, read_asset, tag_factory):
    db.session.add(tag_factory(names=["by_hand"]))
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("png.png"))
    updated = _update(
        client,
        user,
        created["id"],
        created["version"],
        body={"version": created["version"], "tags": ["by_hand"]},
        files={"content": read_asset("jpeg.jpg")},
    )
    # the request's tags replace the post's; the module's are added to them
    assert {tag["names"][0] for tag in updated["tags"]} == {
        "by_hand",
        "probed",
        "is_jpeg",
        "orphan",
    }


def test_update_without_content_leaves_the_extracted_content(
    client, user, read_asset, tag_factory
):
    db.session.add(tag_factory(names=["by_hand"]))
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("png.png"))
    before = _contents(created["id"])
    ids = {row.post_content_id for row in posts.get_post_by_id(created["id"]).contents}

    calls = []
    registry.use(
        [
            _probe_module(
                extract=lambda m, f: calls.append("extract") or [],
                auto_tag=lambda contents: calls.append("tag") or {},
            )
        ]
    )
    updated = _update(
        client,
        user,
        created["id"],
        created["version"],
        body={"version": created["version"], "tags": ["by_hand"], "safety": "unsafe"},
    )

    assert calls == []
    assert _contents(created["id"]) == before
    assert ids == {
        row.post_content_id for row in posts.get_post_by_id(created["id"]).contents
    }
    # removing a module's tag by hand sticks
    assert [tag["names"][0] for tag in updated["tags"]] == ["by_hand"]


def test_new_content_without_modules_clears_the_extracted_content(
    client, user, read_asset
):
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("png.png"))
    registry.use([])
    _update(
        client,
        user,
        created["id"],
        created["version"],
        files={"content": read_asset("jpeg.jpg")},
    )
    assert _contents(created["id"]) == []


def test_deleting_a_post_deletes_its_extracted_content(client, user, read_asset):
    registry.use([_probe_module()])
    created = _upload(client, user, read_asset("png.png"))
    posts.delete(posts.get_post_by_id(created["id"]))
    db.session.commit()
    assert db.session.query(model.PostContent).count() == 0


@pytest.mark.parametrize("replace_content", [True, False])
def test_merging_posts(client, user, read_asset, replace_content):
    registry.use([_probe_module()])
    png = read_asset("png.png")
    source = _upload(client, user, png)
    target = _upload(client, user, read_asset("jpeg.jpg"))
    target_contents = _contents(target["id"])

    ok(
        client.post(
            "/post-merge",
            user=user,
            body={
                "remove": source["id"],
                "removeVersion": source["version"],
                "mergeTo": target["id"],
                "mergeToVersion": target["version"],
                "replaceContent": replace_content,
            },
        )
    )

    if replace_content:
        # the target has the source's file now, and what is in that file
        assert _contents(target["id"]) == [
            ("probe_file", 7, {"mimeType": "image/png", "size": len(png)}),
            ("probe_png", 1, {"header": "PNG"}),
        ]
    else:
        assert _contents(target["id"]) == target_contents
    assert db.session.query(model.PostContent).count() == len(_contents(target["id"]))
