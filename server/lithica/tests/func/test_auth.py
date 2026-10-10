import re
from datetime import datetime, timedelta

import pytest

from lithica.func import auth


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"secret": "testSecret"})


def test_get_password_hash():
    salt, password = ("testSalt", "pass")
    result, revision = auth.get_password_hash(salt, password)
    assert result
    assert revision == 3
    hash_parts = list(filter(lambda e: e is not None and e != "", result.split("$")))
    assert len(hash_parts) == 5
    assert hash_parts[0] == "argon2id"


def test_get_sha256_legacy_password_hash():
    salt, password = ("testSalt", "pass")
    result, revision = auth.get_sha256_legacy_password_hash(salt, password)
    hash = "2031ac9631353ac9303719a7f808a24f79aa1d71712c98523e4bb4cce579428a"
    assert result == hash
    assert revision == 2


def test_get_sha1_legacy_password_hash():
    salt, password = ("testSalt", "pass")
    result, revision = auth.get_sha1_legacy_password_hash(salt, password)
    assert result == "1eb1f953d9be303a1b54627e903e6124cfb1245b"
    assert revision == 1


def test_is_valid_password_auto_upgrades_user_password_hash(user_factory):
    salt, password = ("testSalt", "pass")
    hash, revision = auth.get_sha256_legacy_password_hash(salt, password)
    user = user_factory(password_salt=salt, password_hash=hash)
    result = auth.is_valid_password(user, password)
    assert result is True
    assert user.password_hash != hash
    assert user.password_revision > revision


def test_is_valid_password_accepts_sha1_legacy_hash(user_factory):
    salt, password = ("testSalt", "pass")
    hash, revision = auth.get_sha1_legacy_password_hash(salt, password)
    user = user_factory(password_salt=salt, password_hash=hash)
    assert auth.is_valid_password(user, password) is True
    assert user.password_revision > revision


@pytest.mark.parametrize("wrong_password", ["pas", "pass ", "Pass", "", "zażółć"])
def test_is_valid_password_rejects_wrong_password_for_legacy_hash(
    user_factory, wrong_password
):
    salt, password = ("testSalt", "pass")
    hash, _revision = auth.get_sha256_legacy_password_hash(salt, password)
    user = user_factory(password_salt=salt, password_hash=hash)
    assert auth.is_valid_password(user, wrong_password) is False
    assert user.password_hash == hash


def test_is_valid_password_rejects_wrong_password(user_factory):
    salt, password = ("testSalt", "pass")
    hash, _revision = auth.get_password_hash(salt, password)
    user = user_factory(password_salt=salt, password_hash=hash)
    assert auth.is_valid_password(user, password) is True
    assert auth.is_valid_password(user, "wrong") is False


def test_create_password():
    passwords = {auth.create_password() for _ in range(20)}
    assert len(passwords) > 1
    for password in passwords:
        # the "consonant" alphabet has always included "i"
        assert re.fullmatch(
            "[b-df-np-tv-z][aeiou][b-df-np-tv-z][aeiou][0-9]{2}"
            "[b-df-np-tv-z][aeiou][b-df-np-tv-z][aeiou]",
            password,
        )


def test_is_valid_token(user_token_factory):
    user_token = user_token_factory()
    assert auth.is_valid_token(user_token)


def test_expired_token_is_invalid(user_token_factory):
    past_expiration = datetime.utcnow() - timedelta(minutes=30)
    user_token = user_token_factory(expiration_time=past_expiration)
    assert not auth.is_valid_token(user_token)


def test_disabled_token_is_invalid(user_token_factory):
    user_token = user_token_factory(enabled=False)
    assert not auth.is_valid_token(user_token)


def test_generate_authorization_token():
    result = auth.generate_authorization_token()
    assert result != auth.generate_authorization_token()
