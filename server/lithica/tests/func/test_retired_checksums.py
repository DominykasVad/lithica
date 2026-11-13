"""Former files reserve their original post without widening searches."""

import pytest
import sqlalchemy as sa

from lithica import db, model
from lithica.func import posts, util


def test_retired_duplicate_and_own_return(
    post_factory, read_asset, config_injector, tmp_path
):
    config_injector(
        {
            "data_url": "http://example.com",
            "data_dir": str(tmp_path),
            "secret": "test",
            "thumbnails": {"post_width": 300, "post_height": 300},
        }
    )
    content = read_asset("png.png")
    owner, other = post_factory(), post_factory()
    db.session.add_all([owner, other])
    db.session.flush()
    posts.retire_checksum(owner, util.get_sha1(content), "replaced")
    db.session.flush()
    assert posts.search_by_image_exact(content) is owner
    with pytest.raises(posts.PostAlreadyUploadedError, match=str(owner.post_id)):
        with db.session.begin_nested():
            posts.update_post_content(other, content)
    posts.update_post_content(owner, content)
    assert db.session.get(model.PostRetiredChecksum, util.get_sha1(content)) is None


def test_retired_freed_on_delete(post_factory):
    post = post_factory()
    db.session.add(post)
    db.session.flush()
    posts.retire_checksum(post, "former", "replaced")
    db.session.flush()
    db.session.execute(sa.delete(model.Post).where(model.Post.post_id == post.post_id))
    db.session.expire_all()
    assert db.session.get(model.PostRetiredChecksum, "former") is None
