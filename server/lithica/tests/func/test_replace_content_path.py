"""Changing extensions removes only files superseded by a committed edit."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lithica import db, errors, model
from lithica.func import files, posts
from lithica.tests.api.http import enabled_config


@pytest.fixture
def stored_post(
    config_injector: Callable[[dict[str, Any]], None],
    tmp_path: Path,
    read_asset: Callable[[str], bytes],
    post_factory: Callable[..., model.Post],
) -> model.Post:
    # Any: site configuration includes values of several unrelated types.
    config_injector(
        enabled_config(
            {
                "data_dir": str(tmp_path),
                "data_url": "http://example.com",
                "secret": "test",
                "thumbnails": {"post_width": 300, "post_height": 300},
            }
        )
    )
    post = post_factory()
    db.session.add(post)
    posts.update_post_content(post, read_asset("png.png"))
    db.session.commit()
    return post


@pytest.mark.parametrize("commit", [True, False])
def test_old_path_lives_until_commit(
    stored_post: model.Post, read_asset: Callable[[str], bytes], commit: bool
) -> None:
    old = posts.get_post_content_path(stored_post)
    thumb = posts.get_post_thumbnail_path(stored_post)
    assert files.has(old) and files.has(thumb)
    posts.update_post_content(stored_post, read_asset("jpeg.jpg"))
    db.session.flush()
    new = posts.get_post_content_path(stored_post)
    assert old != new and files.has(old)
    if commit:
        db.session.commit()
        assert not files.has(old)
        assert files.has(new) and files.has(thumb)
    else:
        db.session.rollback()
        db.session.commit()
        assert files.has(old)


def test_repeated_replacement_keeps_final_path(
    stored_post: model.Post, read_asset: Callable[[str], bytes]
) -> None:
    original = posts.get_post_content_path(stored_post)
    posts.update_post_content(stored_post, read_asset("jpeg.jpg"))
    db.session.flush()
    intermediate = posts.get_post_content_path(stored_post)
    posts.update_post_content(stored_post, read_asset("png.png"))
    db.session.flush()
    db.session.commit()
    assert files.has(original)
    assert not files.has(intermediate)
    assert files.get(original) == read_asset("png.png")


@pytest.mark.parametrize("commit_nested", [True, False])
def test_savepoint_scopes_obsolete_paths(
    stored_post: model.Post,
    read_asset: Callable[[str], bytes],
    commit_nested: bool,
) -> None:
    original = posts.get_post_content_path(stored_post)
    nested = db.session.begin_nested()
    posts.update_post_content(stored_post, read_asset("jpeg.jpg"))
    db.session.flush()
    new = posts.get_post_content_path(stored_post)
    assert files.has(original)
    if commit_nested:
        nested.commit()
    else:
        nested.rollback()
    assert files.has(original)
    db.session.commit()
    assert files.has(original) is not commit_nested
    if commit_nested:
        assert files.has(new)


def test_deferred_content_waits_for_release(
    stored_post: model.Post, read_asset: Callable[[str], bytes]
) -> None:
    old = posts.get_post_content_path(stored_post)
    posts.update_post_content(stored_post, read_asset("jpeg.jpg"), defer_file=True)
    db.session.flush()
    new = posts.get_post_content_path(stored_post)
    assert files.has(old) and not files.has(new)
    posts.release_post_content(stored_post)
    db.session.commit()
    assert not files.has(old) and files.has(new)


def test_later_refusal_keeps_original(
    stored_post: model.Post, read_asset: Callable[[str], bytes]
) -> None:
    old = posts.get_post_content_path(stored_post)
    with pytest.raises(errors.ValidationError):
        with db.session.begin_nested():
            posts.update_post_content(
                stored_post, read_asset("jpeg.jpg"), defer_file=True
            )
            db.session.flush()
            assert not files.has(posts.get_post_content_path(stored_post))
            raise errors.ValidationError("A later validation refused the request.")
    db.session.commit()
    assert files.has(old)
    assert files.get(old) == read_asset("png.png")
