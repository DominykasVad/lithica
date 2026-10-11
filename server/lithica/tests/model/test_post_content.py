from datetime import datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

from lithica import db, model


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"secret": "secret", "data_dir": "", "delete_source_files": False})


def _content(kind="some_kind", payload=None, schema_version=1):
    return model.PostContent(
        kind=kind,
        schema_version=schema_version,
        payload={"text": "hello"} if payload is None else payload,
        extracted_at=datetime(1997, 1, 1),
    )


def test_saving_post_content(post_factory):
    post = post_factory()
    payload = {
        "text": "zażółć",
        "number": 1.5,
        "nested": {"list": [1, "two", None, True]},
    }
    post.contents = [
        _content("first", payload, schema_version=3),
        # several rows per post, also of one kind
        _content("second", {}),
        _content("second", {"n": 2}),
    ]
    db.session.add(post)
    db.session.commit()
    db.session.expire_all()

    post = db.session.query(model.Post).one()
    assert [content.kind for content in post.contents] == ["first", "second", "second"]
    first = post.contents[0]
    assert first.post_content_id is not None
    assert first.post_id == post.post_id
    assert first.post is post
    assert first.schema_version == 3
    assert first.payload == payload
    assert first.extracted_at == datetime(1997, 1, 1)
    assert post.contents[1].payload == {}


def test_payload_can_be_searched(post_factory):
    # what the search tokens of modules are built on; the same expression
    # works on every database SQLAlchemy has a JSON type for
    post1, post2 = post_factory(), post_factory()
    post1.contents = [_content(payload={"text": "needle"})]
    post2.contents = [_content(payload={"text": "hay"}), _content(payload={})]
    db.session.add_all([post1, post2])
    db.session.commit()

    found = (
        db.session.query(model.PostContent.post_id)
        .filter(model.PostContent.payload["text"].as_string() == "needle")
        .all()
    )
    assert found == [(post1.post_id,)]


def test_replacing_the_contents_of_a_post(post_factory):
    post = post_factory()
    post.contents = [_content("old"), _content("old")]
    db.session.add(post)
    db.session.commit()

    post.contents = [_content("new")]
    db.session.commit()
    db.session.expire_all()

    assert [content.kind for content in db.session.query(model.PostContent)] == ["new"]


def test_deleting_a_post_deletes_its_contents(post_factory):
    post, other_post = post_factory(), post_factory()
    post.contents = [_content(), _content()]
    other_post.contents = [_content("kept")]
    db.session.add_all([post, other_post])
    db.session.commit()

    db.session.delete(post)
    db.session.commit()

    assert [content.kind for content in db.session.query(model.PostContent)] == ["kept"]


def test_database_deletes_the_contents_with_the_post(post_factory):
    # ON DELETE CASCADE: also when the post is deleted behind the session
    post = post_factory()
    post.contents = [_content()]
    db.session.add(post)
    db.session.commit()
    post_id = post.post_id
    db.session.expunge_all()

    db.session.execute(sa.delete(model.Post).where(model.Post.post_id == post_id))
    db.session.commit()

    assert db.session.query(model.PostContent).count() == 0


def test_deleting_content_keeps_the_post(post_factory):
    post = post_factory()
    post.contents = [_content()]
    db.session.add(post)
    db.session.commit()

    db.session.delete(post.contents[0])
    db.session.commit()
    db.session.expire_all()

    assert db.session.query(model.Post).count() == 1
    assert db.session.query(model.Post).one().contents == []


@pytest.mark.parametrize("field", ["kind", "schema_version", "payload", "extracted_at"])
def test_every_column_is_required(post_factory, field):
    post = post_factory()
    content = _content()
    setattr(content, field, None)
    post.contents = [content]
    db.session.add(post)
    # None is a missing payload, not the JSON value null
    with pytest.raises(sa_exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_table_has_the_lookup_index():
    table = model.Base.metadata.tables["post_content"]
    indexes = {
        index.name: [column.name for column in index.columns] for index in table.indexes
    }
    assert indexes == {"ix_post_content_post_id_kind": ["post_id", "kind"]}
