from datetime import datetime
from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import posts
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "posts:list": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
            },
        }
    )


def test_retrieving_multiple(user_factory, post_factory, client):
    post1 = post_factory(id=1)
    post2 = post_factory(id=2)
    db.session.add_all([post1, post2])
    db.session.flush()
    with patch("lithica.func.posts.serialize_post"):
        posts.serialize_post.return_value = "serialized post"
        result = ok(
            client.get(
                "/posts",
                user=user_factory(rank=model.User.RANK_REGULAR),
                query={"query": "", "offset": 0},
            )
        )
        assert result == {
            "query": "",
            "offset": 0,
            "limit": 100,
            "total": 2,
            "results": ["serialized post", "serialized post"],
        }


def test_using_special_tokens(user_factory, post_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post1 = post_factory(id=1)
    post2 = post_factory(id=2)
    post1.favorited_by = [model.PostFavorite(user=auth_user, time=datetime.utcnow())]
    db.session.add_all([post1, post2, auth_user])
    db.session.flush()
    with patch("lithica.func.posts.serialize_post"):
        posts.serialize_post.side_effect = lambda post, *_args, **_kwargs: (
            "serialized post %d" % post.post_id
        )
        result = ok(
            client.get(
                "/posts", user=auth_user, query={"query": "special:fav", "offset": 0}
            )
        )
        assert result == {
            "query": "special:fav",
            "offset": 0,
            "limit": 100,
            "total": 1,
            "results": ["serialized post 1"],
        }


def test_trying_to_use_special_tokens_without_logging_in(
    user_factory, client, config_injector
):
    config_injector(
        {
            "privileges": {"posts:list": "anonymous"},
        }
    )
    assert_error(
        client.get(
            "/posts",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "special:fav", "offset": 0},
        ),
        errors.SearchError,
    )


def test_trying_to_retrieve_multiple_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/posts",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "", "offset": 0},
        ),
        errors.AuthError,
    )


def test_retrieving_single(user_factory, post_factory, client):
    db.session.add(post_factory(id=1))
    db.session.flush()
    with patch("lithica.func.posts.serialize_post"):
        posts.serialize_post.return_value = "serialized post"
        result = ok(
            client.get("/post/1", user=user_factory(rank=model.User.RANK_REGULAR))
        )
        assert result == "serialized post"


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    assert_error(
        client.get("/post/999", user=user_factory(rank=model.User.RANK_REGULAR)),
        posts.PostNotFoundError,
    )


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    assert_error(
        client.get("/post/999", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )


@pytest.fixture
def real_post(config_injector, tmpdir, post_factory, user_factory, tag_factory):
    """A post with everything a serialized post can hold, and its uploader."""
    config_injector(
        {
            "secret": "test",
            "data_dir": str(tmpdir),
            "data_url": "http://example.com/data/",
            "thumbnails": {
                "avatar_width": 30,
                "avatar_height": 30,
                "post_width": 300,
                "post_height": 300,
            },
            "privileges": {
                "posts:list": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
                "posts:view:featured": model.User.RANK_REGULAR,
                "users:edit:any:email": model.User.RANK_MODERATOR,
            },
        }
    )
    user = user_factory(name="uploader", rank=model.User.RANK_REGULAR)
    category = model.TagCategory("meta")
    category.default = True
    related = post_factory(id=2)
    post = post_factory(id=1)
    post.user = user
    post.source = "http://example.com/source"
    post.canvas_width = 100
    post.canvas_height = 50
    post.file_size = 1234
    post.checksum_md5 = "0" * 32
    post.flags = ["loop"]
    post.tags = [tag_factory(names=["tag"], category=category)]
    note = model.PostNote()
    note.polygon = [[0, 0], [0, 1], [1, 1]]
    note.text = "a note"
    post.notes = [note]
    comment = model.Comment()
    comment.user = user
    comment.text = "a comment"
    comment.creation_time = datetime(1997, 1, 1)
    post.comments = [comment]
    pool = model.Pool()
    pool.names = [model.PoolName("pool", 0)]
    pool.category = model.PoolCategory("series")
    pool.creation_time = datetime(1997, 1, 1)
    db.session.add_all([user, category, related, post, pool])
    db.session.flush()
    post.relations = [related]
    post.favorited_by = [model.PostFavorite(user=user, time=datetime(1997, 1, 1))]
    post.scores = [model.PostScore(user=user, score=1, time=datetime(1997, 1, 1))]
    pool.posts.append(post)
    db.session.flush()
    db.session.refresh(post)
    return post


def test_post_fits_its_response_model(client, real_post):
    from lithica.api import resources
    from lithica.tests.api.http import assert_fits

    user = real_post.user
    single = ok(client.get("/post/1", user=user))
    assert single["user"] == {
        "name": "uploader",
        "avatarUrl": single["user"]["avatarUrl"],
    }
    assert single["tags"] == [{"names": ["tag"], "category": "meta", "usages": 1}]
    assert single["notes"] == [{"polygon": [[0, 0], [0, 1], [1, 1]], "text": "a note"}]
    assert [comment["text"] for comment in single["comments"]] == ["a comment"]
    assert [pool["names"] for pool in single["pools"]] == [["pool"]]
    assert [relation["id"] for relation in single["relations"]] == [2]
    assert single["ownFavorite"] is True and single["ownScore"] == 1
    assert single["creationTime"] == "1996-01-01T00:00:00Z"
    assert single["checksumMD5"] == "0" * 32
    assert_fits(resources.Post, single)

    # the bare post has nulls where the full one has values
    assert_fits(resources.Post, ok(client.get("/post/2", user=user)))

    listed = ok(client.get("/posts", user=user))
    assert listed["total"] == 2
    assert_fits(resources.Paged[resources.Post], listed)

    around = ok(client.get("/post/1/around", user=user))
    assert around["prev"]["id"] == 2 and around["next"] is None
    assert_fits(resources.PostsAround, around)

    assert ok(client.get("/featured-post", user=user)) is None

    some_fields = ok(client.get("/post/1", user=user, query={"fields": "id,tags"}))
    assert list(some_fields) == ["id", "tags"]
    assert_fits(resources.Post, some_fields, complete=False)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/post/abc"),
        ("GET", "/post/abc/around"),
        ("PUT", "/post/abc"),
        ("DELETE", "/post/abc/score"),
        ("POST", "/post/abc/favorite"),
    ],
)
def test_post_id_that_is_not_a_number(
    client, user_factory, config_injector, method, path
):
    config_injector(
        {
            "privileges": {
                "posts:list": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
                "posts:score": model.User.RANK_REGULAR,
                "posts:favorite": model.User.RANK_REGULAR,
            }
        }
    )
    assert_error(
        client.request(method, path, user=user_factory(rank=model.User.RANK_REGULAR)),
        posts.InvalidPostIdError,
        "Invalid post ID: 'abc'.",
    )
