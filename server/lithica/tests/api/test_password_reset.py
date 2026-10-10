import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from lithica import api, db, errors, model
from lithica.func import auth, mailer

URL_PREFIX = "http://example.com/password-reset/u1:"


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "secret": "x",
            "domain": "http://example.com",
            "name": "Test instance",
            "password_reset_token_lifetime": 3600,
            "smtp": {
                "from": "noreply@example.com",
            },
        }
    )


@pytest.fixture
def user(user_factory):
    user = user_factory(
        name="u1", rank=model.User.RANK_REGULAR, email="user@example.com"
    )
    db.session.add(user)
    db.session.flush()
    return user


@pytest.fixture
def request_token(context_factory):
    """Request a reset the way a client does; return the token from the mail."""

    def request(user_name="u1"):
        with patch("lithica.func.mailer.send_mail"):
            assert (
                api.password_reset_api.start_password_reset(
                    context_factory(), {"user_name": user_name}
                )
                == {}
            )
            body = mailer.send_mail.call_args[0][3]
        match = re.search(r"/password-reset/[^:\s]+:(\S+)", body)
        assert match
        return match.group(1)

    return request


def _confirm(context_factory, token, user_name="u1"):
    return api.password_reset_api.finish_password_reset(
        context_factory(params={"token": token}), {"user_name": user_name}
    )


def test_reset_sending_email(context_factory, user):
    for initiating_user in ["u1", "user@example.com"]:
        with patch("lithica.func.mailer.send_mail"):
            assert (
                api.password_reset_api.start_password_reset(
                    context_factory(), {"user_name": initiating_user}
                )
                == {}
            )
            mailer.send_mail.assert_called_once()
            sender, recipient, subject, body = mailer.send_mail.call_args[0]
        assert sender == "noreply@example.com"
        assert recipient == "user@example.com"
        assert subject == "Password reset for Test instance"
        prefix = (
            "You (or someone else) requested to reset your password "
            "on Test instance.\nIf you wish to proceed, click this link: " + URL_PREFIX
        )
        suffix = "\nOtherwise, please ignore this email."
        assert body.startswith(prefix)
        assert body.endswith(suffix)
        token = body[len(prefix) : -len(suffix)]
        # the legacy client splits the link on ":" and the token is a URL part
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)


def test_tokens_are_random(user, request_token):
    assert request_token() != request_token()


def test_token_is_stored_hashed(user, request_token):
    token = request_token()
    entry = db.session.query(model.PasswordResetToken).one()
    assert entry.user_id == user.user_id
    assert entry.token_hash != token
    assert token not in entry.token_hash
    assert len(entry.token_hash) == 64


def test_token_lifetime_comes_from_config(user, request_token, fake_datetime):
    with fake_datetime("1997-01-01 12:00:00"):
        request_token()
    entry = db.session.query(model.PasswordResetToken).one()
    assert entry.creation_time == datetime(1997, 1, 1, 12, 0, 0)
    assert entry.expiration_time == datetime(1997, 1, 1, 13, 0, 0)


def test_trying_to_reset_non_existing(context_factory):
    with pytest.raises(errors.NotFoundError):
        api.password_reset_api.start_password_reset(
            context_factory(), {"user_name": "u1"}
        )


def test_trying_to_reset_without_email(context_factory, user_factory):
    db.session.add(user_factory(name="u1", rank=model.User.RANK_REGULAR, email=None))
    db.session.flush()
    with pytest.raises(errors.ValidationError):
        api.password_reset_api.start_password_reset(
            context_factory(), {"user_name": "u1"}
        )


def test_confirming_with_good_token(context_factory, user, request_token):
    old_hash = user.password_hash
    result = _confirm(context_factory, request_token())
    assert user.password_hash != old_hash
    assert auth.is_valid_password(user, result["password"]) is True
    assert db.session.query(model.PasswordResetToken).count() == 0


def test_confirming_by_email(context_factory, user, request_token):
    result = _confirm(context_factory, request_token(), "user@example.com")
    assert auth.is_valid_password(user, result["password"]) is True


def test_token_works_only_once(context_factory, user, request_token):
    token = request_token()
    result = _confirm(context_factory, token)
    with pytest.raises(errors.ValidationError):
        _confirm(context_factory, token)
    assert auth.is_valid_password(user, result["password"]) is True


def test_new_request_replaces_the_previous_token(context_factory, user, request_token):
    old_token = request_token()
    new_token = request_token()
    assert db.session.query(model.PasswordResetToken).count() == 1
    with pytest.raises(errors.ValidationError):
        _confirm(context_factory, old_token)
    _confirm(context_factory, new_token)


def test_token_expires(context_factory, user, request_token, fake_datetime):
    old_hash = user.password_hash
    with fake_datetime("1997-01-01 12:00:00"):
        token = request_token()
    with fake_datetime("1997-01-01 13:00:00"):
        with pytest.raises(errors.ValidationError):
            _confirm(context_factory, token)
    assert user.password_hash == old_hash


def test_token_valid_until_expiry(context_factory, user, request_token, fake_datetime):
    with fake_datetime("1997-01-01 12:00:00"):
        token = request_token()
    with fake_datetime(datetime(1997, 1, 1, 13, 0, 0) - timedelta(seconds=1)):
        _confirm(context_factory, token)


def test_token_of_another_user(context_factory, user, user_factory, request_token):
    other = user_factory(
        name="u2", rank=model.User.RANK_REGULAR, email="other@example.com"
    )
    db.session.add(other)
    db.session.flush()
    old_hash = other.password_hash
    token = request_token("u1")
    with pytest.raises(errors.ValidationError):
        _confirm(context_factory, token, "u2")
    assert other.password_hash == old_hash
    # the failed attempt did not use up the token of its owner
    _confirm(context_factory, token, "u1")


def test_token_does_not_depend_on_secret(
    context_factory, user, request_token, config_injector
):
    # the scheme this replaced derived the token from the secret and the salt
    assert request_token() != "4ac0be176fb364f13ee6b634c43220e2"
    with pytest.raises(errors.ValidationError):
        _confirm(context_factory, "4ac0be176fb364f13ee6b634c43220e2")


def test_tokens_are_deleted_with_the_user(user, request_token):
    request_token()
    db.session.delete(user)
    db.session.commit()
    assert db.session.query(model.PasswordResetToken).count() == 0


def test_trying_to_confirm_non_existing(context_factory):
    with pytest.raises(errors.NotFoundError):
        api.password_reset_api.finish_password_reset(
            context_factory(), {"user_name": "u1"}
        )


def test_trying_to_confirm_without_token(context_factory, user):
    with pytest.raises(errors.ValidationError):
        api.password_reset_api.finish_password_reset(
            context_factory(params={}), {"user_name": "u1"}
        )


def test_trying_to_confirm_with_bad_token(context_factory, user, request_token):
    request_token()
    with pytest.raises(errors.ValidationError):
        api.password_reset_api.finish_password_reset(
            context_factory(params={"token": "bad"}), {"user_name": "u1"}
        )


def test_trying_to_confirm_without_requesting(context_factory, user):
    with pytest.raises(errors.ValidationError):
        api.password_reset_api.finish_password_reset(
            context_factory(params={"token": "bad"}), {"user_name": "u1"}
        )
