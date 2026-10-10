from unittest.mock import patch

import pytest

from lithica import db
from lithica.func import auth, user_tokens, users
from lithica.middleware import authenticator
from lithica.rest import errors


def test_process_request_no_header(context_factory):
    ctx = context_factory()
    authenticator.process_request(ctx)
    assert ctx.user.name is None


def test_process_request_bump_login(context_factory, user_factory):
    user = user_factory()
    db.session.add(user)
    db.session.flush()
    ctx = context_factory(
        headers={"Authorization": "Basic dGVzdFVzZXI6dGVzdFRva2Vu"},
        params={"bump-login": "true"},
    )
    with patch("lithica.func.auth.is_valid_password"), patch(
        "lithica.func.users.get_user_by_name"
    ):
        users.get_user_by_name.return_value = user
        auth.is_valid_password.return_value = True
        authenticator.process_request(ctx)
        assert user.last_login_time is not None


def test_process_request_bump_login_with_token(
    context_factory, user_token_factory
):
    user_token = user_token_factory()
    db.session.add(user_token)
    db.session.flush()
    ctx = context_factory(
        headers={"Authorization": "Token dGVzdFVzZXI6dGVzdFRva2Vu"},
        params={"bump-login": "true"},
    )
    with patch("lithica.func.auth.is_valid_token"), patch(
        "lithica.func.users.get_user_by_name"
    ), patch("lithica.func.user_tokens.get_by_user_and_token"):
        users.get_user_by_name.return_value = user_token.user
        user_tokens.get_by_user_and_token.return_value = user_token
        auth.is_valid_token.return_value = True
        authenticator.process_request(ctx)
        assert user_token.user.last_login_time is not None
        assert user_token.last_usage_time is not None


def test_process_request_basic_auth_valid(context_factory, user_factory):
    user = user_factory()
    ctx = context_factory(
        headers={"Authorization": "Basic dGVzdFVzZXI6dGVzdFBhc3N3b3Jk"}
    )
    with patch("lithica.func.auth.is_valid_password"), patch(
        "lithica.func.users.get_user_by_name"
    ):
        users.get_user_by_name.return_value = user
        auth.is_valid_password.return_value = True
        authenticator.process_request(ctx)
        assert ctx.user == user


def test_process_request_token_auth_valid(context_factory, user_token_factory):
    user_token = user_token_factory()
    ctx = context_factory(
        headers={"Authorization": "Token dGVzdFVzZXI6dGVzdFRva2Vu"}
    )
    with patch("lithica.func.auth.is_valid_token"), patch(
        "lithica.func.users.get_user_by_name"
    ), patch("lithica.func.user_tokens.get_by_user_and_token"):
        users.get_user_by_name.return_value = user_token.user
        user_tokens.get_by_user_and_token.return_value = user_token
        auth.is_valid_token.return_value = True
        authenticator.process_request(ctx)
        assert ctx.user == user_token.user


def test_process_request_bad_header(context_factory):
    ctx = context_factory(headers={"Authorization": "Secret SuperSecretValue"})
    with pytest.raises(errors.HttpBadRequest):
        authenticator.process_request(ctx)
