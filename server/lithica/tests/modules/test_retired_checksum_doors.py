"""Every file entry point honors checksums reserved by a former file."""

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from lithica import config, db, model
from lithica.func import post_import, posts, util
from lithica.tests.api.http import assert_error, ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.test_admin_import import admin  # noqa: F401

Site = Callable[[list[str]], ApiClient]


def _upload(
    client: ApiClient, user: model.User, content: bytes, tags: list[str] | None = None
) -> model.Post:
    result = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": tags or []},
            files={"content": content},
        )
    )
    return posts.get_post_by_id(result["id"])


def _retire(owner: model.Post, content: bytes) -> None:
    posts.retire_checksum(owner, util.get_sha1(content), "replaced")
    db.session.commit()


@pytest.mark.parametrize("door", ["upload", "update"])
def test_retired_file_refused_at_upload_and_update(
    site: Site, user: model.User, door: str
) -> None:
    client = site([])
    owner = _upload(client, user, cards.picture(1))
    former = cards.picture(2)
    _retire(owner, former)
    if door == "upload":
        response = client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": former},
        )
    else:
        target = _upload(client, user, cards.picture(3))
        old_checksum = target.checksum
        response = client.put(
            f"/post/{target.post_id}",
            user=user,
            body={"version": target.version},
            files={"content": former},
        )
        db.session.rollback()
        db.session.refresh(target)
        assert target.checksum == old_checksum
    body = assert_error(response, posts.PostAlreadyUploadedError)
    assert body["otherPostId"] == owner.post_id
    assert str(owner.post_id) in body["description"]


def test_retired_file_reverse_search_exact(site: Site, user: model.User) -> None:
    client = site([])
    config.config["privileges"]["posts:reverse_search"] = "regular"
    owner = _upload(client, user, cards.picture(1))
    former = cards.picture(2)
    _retire(owner, former)
    answer = ok(
        client.post(
            "/posts/reverse-search",
            user=user,
            query={"fields": "id"},
            files={"content": former},
        )
    )
    assert answer["exactPost"] == {"id": owner.post_id}
    for token in ("sha1", "content-checksum"):
        found = ok(
            client.get(
                "/posts",
                user=user,
                query={"query": f"{token}:{util.get_sha1(former)}", "fields": "id"},
            )
        )
        assert found["results"] == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_retired_file_import_is_skipped(
    site: Site, user: model.User, tmp_path: Path, dry_run: bool
) -> None:
    client = site([])
    owner = _upload(client, user, cards.picture(1))
    former = cards.picture(2)
    _retire(owner, former)
    folder = tmp_path / "import"
    folder.mkdir()
    (folder / "former.png").write_bytes(former)
    result = post_import.import_folder(
        str(folder), user.name, "safe", [], dry_run=dry_run
    )
    assert result.count(post_import.SKIPPED) == 1
    assert result.count(post_import.CREATED) == 0
    assert str(owner.post_id) in result.outcomes[0].detail
    assert db.session.query(model.Post).count() == 1


def test_retired_file_admin_import_and_dry_run(
    site: Site,
    user: model.User,
    tmp_path: Path,
    admin: ModuleType,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = site([])
    owner = _upload(client, user, cards.picture(1))
    former = cards.picture(2)
    _retire(owner, former)
    folder = tmp_path / "import"
    folder.mkdir()
    (folder / "former.png").write_bytes(former)
    args = ["import", str(folder), "--user", user.name, "--safety", "safe"]
    for options in (["--dry-run"], []):
        assert admin.main([*args, *options]) == 0
        output = capsys.readouterr().out
        assert "1 skipped" in output
        assert str(owner.post_id) in output
    assert db.session.query(model.Post).count() == 1


def test_retired_file_merge_with_content_refused(site: Site, user: model.User) -> None:
    client = site([])
    config.config["privileges"]["posts:merge"] = "regular"
    owner = _upload(client, user, cards.picture(1))
    source_content = cards.picture(2)
    source = _upload(client, user, source_content)
    target = _upload(client, user, cards.picture(3))
    # A stored source predates this reservation: merge must use the same guard.
    _retire(owner, source_content)
    response = client.post(
        "/post-merge",
        user=user,
        body={
            "remove": source.post_id,
            "removeVersion": source.version,
            "mergeTo": target.post_id,
            "mergeToVersion": target.version,
            "replaceContent": True,
        },
    )
    body = assert_error(response, posts.PostAlreadyUploadedError)
    db.session.rollback()
    assert body["otherPostId"] == owner.post_id
    assert db.session.query(model.Post).count() == 3


def test_hidden_retiring_post_gives_bare_duplicate_error(
    site: Site, user: model.User
) -> None:
    client = site([])
    owner = _upload(client, user, cards.picture(1), tags=["nsfw"])
    former = cards.picture(2)
    _retire(owner, former)
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:create:identified"] = "anonymous"
    response = client.post("/posts", body={"safety": "safe"}, files={"content": former})
    body = assert_error(response, posts.PostAlreadyUploadedError)
    assert body["description"] == "Post already uploaded."
    assert "otherPostId" not in body
    assert "otherPostUrl" not in body
