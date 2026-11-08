import pytest
import yaml

from lithica import db, model
from lithica.func import app_token_rights, auth, users


def _dist_privileges() -> dict[str, str]:
    with open("config.yaml.dist") as handle:
        return yaml.safe_load(handle)["privileges"]


def test_every_right_lists_privileges_that_exist():
    privileges = _dist_privileges()
    for right, listed in app_token_rights.RIGHTS.items():
        assert listed, right
        for privilege in listed:
            assert privilege in privileges, (right, privilege)


def test_no_right_reaches_accounts_or_tokens():
    for listed in app_token_rights.RIGHTS.values():
        for privilege in listed:
            assert not privilege.startswith(("users:", "user_tokens:", "app_tokens:"))
            assert not app_token_rights.is_forbidden(privilege)


def test_no_right_lists_what_moderators_do():
    privileges = _dist_privileges()
    ranks = list(auth.RANK_MAP.values())
    for listed in app_token_rights.RIGHTS.values():
        for privilege in listed:
            rank = privileges[privilege]
            assert ranks.index(rank) < ranks.index("moderator"), privilege


def test_unknown_rights_list_nothing():
    assert app_token_rights.privileges_of(["nope"]) == frozenset()
    assert app_token_rights.privileges_of(["read", "nope"]) == frozenset(
        app_token_rights.RIGHTS["read"]
    )


@pytest.fixture
def dist_config(config_injector):
    config_injector({"privileges": _dist_privileges()})


def _user(user_factory, rank: str) -> model.User:
    user = user_factory(rank=rank)
    db.session.add(user)
    db.session.flush()
    return user


def test_without_an_app_token_the_rank_decides(dist_config, user_factory):
    admin = _user(user_factory, model.User.RANK_ADMINISTRATOR)
    with db.session_scope():
        assert app_token_rights.current_rights() is None
        assert auth.has_privilege(admin, "users:delete:any")
        assert auth.has_privilege(admin, "posts:delete")


def test_with_an_app_token_rights_and_rank_decide(dist_config, user_factory):
    regular = _user(user_factory, model.User.RANK_REGULAR)
    with db.session_scope():
        app_token_rights.begin_app_token_request(["read", "write"])
        assert auth.has_privilege(regular, "posts:list")
        assert auth.has_privilege(regular, "posts:edit:tags")
        # in a right, but the rank does not grant it
        assert not auth.has_privilege(regular, "posts:edit:content")
        # granted by the rank, in no right
        assert not auth.has_privilege(regular, "posts:score")
        assert not auth.has_privilege(regular, "uploads:create")
        assert not auth.has_privilege(regular, "users:edit:self:pass")
        assert not auth.has_privilege(regular, "user_tokens:create:self")
        assert not auth.has_privilege(regular, "app_tokens:list:self")


def test_an_unknown_stored_right_grants_nothing(dist_config, user_factory):
    admin = _user(user_factory, model.User.RANK_ADMINISTRATOR)
    with db.session_scope():
        app_token_rights.begin_app_token_request(["everything"])
        for privilege in _dist_privileges():
            assert not auth.has_privilege(admin, privilege), privilege
    with db.session_scope():
        app_token_rights.begin_app_token_request([])
        assert not auth.has_privilege(admin, "posts:list")


def test_rights_end_with_the_request(dist_config, user_factory):
    regular = _user(user_factory, model.User.RANK_REGULAR)
    with db.session_scope():
        app_token_rights.begin_app_token_request(["read"])
        assert not auth.has_privilege(regular, "posts:score")
    with db.session_scope():
        assert auth.has_privilege(regular, "posts:score")


def test_an_app_token_is_not_its_owner_acting_on_the_account(dist_config, user_factory):
    regular = _user(user_factory, model.User.RANK_REGULAR)
    regular.email = "me@example.com"
    with db.session_scope():
        assert auth.is_self(regular, regular)
        assert users.get_email(regular, regular, False) == "me@example.com"
    with db.session_scope():
        app_token_rights.begin_app_token_request(["read"])
        assert not auth.is_self(regular, regular)
        assert users.get_email(regular, regular, False) is False
        assert users.get_liked_post_count(regular, regular) is False


def test_an_app_token_needs_a_request():
    with pytest.raises(RuntimeError):
        app_token_rights.begin_app_token_request(["read"])
