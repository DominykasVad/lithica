import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import auth, mailer
from lithica.tests.api.http import assert_error, ok

URL_PREFIX = "http://example.com/password-reset/u1:"


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "secret": "x",
            "domain": "http://example.com",
            "name": "Test instance",
            "password_reset_token_lifetime": 3600,
            # a site that sends mail (the tests catch the mail itself)
            "smtp": {
                "host": "mail.example.com",
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
def request_token(client):
    """Request a reset the way a client does; return the token from the mail."""

    def request(user_name="u1"):
        with patch("lithica.func.mailer.send_mail"):
            assert ok(client.get("/password-reset/%s" % user_name)) == {}
            body = mailer.send_mail.call_args[0][3]
        match = re.search(r"/password-reset/[^:\s]+:(\S+)", body)
        assert match
        return match.group(1)

    return request


def _confirm(client, token, user_name="u1"):
    return client.post("/password-reset/%s" % user_name, body={"token": token})


def test_reset_sending_email(client, user):
    for initiating_user in ["u1", "user@example.com"]:
        with patch("lithica.func.mailer.send_mail"):
            assert ok(client.get("/password-reset/%s" % initiating_user)) == {}
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


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example.net"},
        {"Referer": "https://evil.example.net/page"},
        {"Host": "evil.example.net"},
        {
            "Origin": "https://evil.example.net",
            "Referer": "https://evil.example.net/",
            "Host": "evil.example.net",
            "X-Forwarded-Host": "evil.example.net",
        },
    ],
)
def test_reset_link_ignores_request_headers(client, user, headers):
    with patch("lithica.func.mailer.send_mail"):
        ok(client.get("/password-reset/u1", headers=headers))
        body = mailer.send_mail.call_args[0][3]
    assert URL_PREFIX in body
    assert "evil.example.net" not in body


def test_reset_link_tolerates_trailing_slash_in_domain(client, user, config_injector):
    config_injector(
        {
            "domain": "http://example.com/",
            "name": "Test instance",
            "password_reset_token_lifetime": 3600,
            "smtp": {"host": "mail.example.com", "from": "noreply@example.com"},
        }
    )
    with patch("lithica.func.mailer.send_mail"):
        ok(client.get("/password-reset/u1"))
        body = mailer.send_mail.call_args[0][3]
    assert URL_PREFIX in body


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


def test_trying_to_reset_non_existing(client):
    assert_error(client.get("/password-reset/u1"), errors.NotFoundError)


def test_trying_to_reset_on_a_site_that_cannot_send_mail(client, user, config_injector):
    config_injector(
        {
            "secret": "x",
            "domain": "http://example.com",
            "name": "Test instance",
            "smtp": {"host": None, "from": "noreply@example.com"},
        }
    )
    # no mail server, and nothing patched: the reset says so
    response = client.get("/password-reset/u1")
    body = assert_error(response, mailer.MailNotConfiguredError)
    assert response.status_code == 500
    assert body["title"] == "Server configuration error"
    assert "cannot send mail" in body["description"]
    # refused before a token was made
    assert db.session.query(model.PasswordResetToken).count() == 0
    # what GET /info says as canSendMails
    assert mailer.can_send_mail() is False


def test_trying_to_reset_without_email(client, user_factory):
    db.session.add(user_factory(name="u1", rank=model.User.RANK_REGULAR, email=None))
    db.session.flush()
    assert_error(client.get("/password-reset/u1"), errors.ValidationError)


def test_confirming_with_good_token(client, user, request_token):
    old_hash = user.password_hash
    result = ok(_confirm(client, request_token()))
    assert result is not None
    assert user.password_hash != old_hash
    assert auth.is_valid_password(user, result["password"]) is True
    assert db.session.query(model.PasswordResetToken).count() == 0


def test_confirming_by_email(client, user, request_token):
    result = ok(_confirm(client, request_token(), "user@example.com"))
    assert result is not None
    assert auth.is_valid_password(user, result["password"]) is True


def test_token_works_only_once(client, user, request_token):
    token = request_token()
    result = ok(_confirm(client, token))
    assert result is not None
    assert_error(_confirm(client, token), errors.ValidationError)
    assert auth.is_valid_password(user, result["password"]) is True


def test_new_request_replaces_the_previous_token(client, user, request_token):
    old_token = request_token()
    new_token = request_token()
    assert db.session.query(model.PasswordResetToken).count() == 1
    assert_error(_confirm(client, old_token), errors.ValidationError)
    ok(_confirm(client, new_token))


def test_token_expires(client, user, request_token, fake_datetime):
    old_hash = user.password_hash
    with fake_datetime("1997-01-01 12:00:00"):
        token = request_token()
    with fake_datetime("1997-01-01 13:00:00"):
        assert_error(_confirm(client, token), errors.ValidationError)
    assert user.password_hash == old_hash


def test_token_valid_until_expiry(client, user, request_token, fake_datetime):
    with fake_datetime("1997-01-01 12:00:00"):
        token = request_token()
    with fake_datetime(datetime(1997, 1, 1, 13, 0, 0) - timedelta(seconds=1)):
        ok(_confirm(client, token))


def test_token_of_another_user(client, user, user_factory, request_token):
    other = user_factory(
        name="u2", rank=model.User.RANK_REGULAR, email="other@example.com"
    )
    db.session.add(other)
    db.session.flush()
    old_hash = other.password_hash
    token = request_token("u1")
    assert_error(_confirm(client, token, "u2"), errors.ValidationError)
    assert other.password_hash == old_hash
    # the failed attempt did not use up the token of its owner
    ok(_confirm(client, token, "u1"))


def test_token_does_not_depend_on_secret(client, user, request_token, config_injector):
    # the scheme this replaced derived the token from the secret and the salt
    assert request_token() != "4ac0be176fb364f13ee6b634c43220e2"
    assert_error(
        _confirm(client, "4ac0be176fb364f13ee6b634c43220e2"), errors.ValidationError
    )


def test_tokens_are_deleted_with_the_user(user, request_token):
    request_token()
    db.session.delete(user)
    db.session.commit()
    assert db.session.query(model.PasswordResetToken).count() == 0


def test_trying_to_confirm_non_existing(client):
    assert_error(client.post("/password-reset/u1"), errors.NotFoundError)


def test_trying_to_confirm_without_token(client, user):
    assert_error(client.post("/password-reset/u1", body={}), errors.ValidationError)


def test_trying_to_confirm_with_bad_token(client, user, request_token):
    request_token()
    assert_error(
        client.post("/password-reset/u1", body={"token": "bad"}), errors.ValidationError
    )


def test_trying_to_confirm_without_requesting(client, user):
    assert_error(
        client.post("/password-reset/u1", body={"token": "bad"}), errors.ValidationError
    )


def test_reset_requires_json_and_valid_credentials(client, user):
    # nobody has to be logged in to reset a password, but credentials that
    # are sent are still checked, as on every route
    with patch("lithica.func.mailer.send_mail"):
        response = client.get(
            "/password-reset/u1", headers={"Authorization": "Basic dTE6d3Jvbmc="}
        )
        mailer.send_mail.assert_not_called()
    assert_error(response, errors.AuthError)


def test_confirmation_fits_its_response_model(client, user, request_token):
    from lithica.api import resources
    from lithica.tests.api.http import assert_fits

    assert_fits(resources.PasswordResetResult, ok(_confirm(client, request_token())))
