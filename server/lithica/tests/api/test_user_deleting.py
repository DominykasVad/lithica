import pytest

from lithica import db, errors, model
from lithica.func import users
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "users:delete:self": model.User.RANK_REGULAR,
                "users:delete:any": model.User.RANK_MODERATOR,
            },
        }
    )


def test_deleting_oneself(user_factory, client):
    user = user_factory(name="u", rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.commit()
    result = ok(client.delete("/user/u", user=user, body={"version": 1}))
    assert result == {}
    assert db.session.query(model.User).count() == 0


def test_deleting_someone_else(user_factory, client):
    user1 = user_factory(name="u1", rank=model.User.RANK_REGULAR)
    user2 = user_factory(name="u2", rank=model.User.RANK_MODERATOR)
    db.session.add_all([user1, user2])
    db.session.commit()
    ok(client.delete("/user/u1", user=user2, body={"version": 1}))
    assert db.session.query(model.User).count() == 1


def test_trying_to_delete_someone_else_without_privileges(user_factory, client):
    user1 = user_factory(name="u1", rank=model.User.RANK_REGULAR)
    user2 = user_factory(name="u2", rank=model.User.RANK_REGULAR)
    db.session.add_all([user1, user2])
    db.session.commit()
    assert_error(
        client.delete("/user/u1", user=user2, body={"version": 1}), errors.AuthError
    )
    assert db.session.query(model.User).count() == 2


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete(
            "/user/bad",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"version": 1},
        ),
        users.UserNotFoundError,
    )
