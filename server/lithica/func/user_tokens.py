import hmac
from collections.abc import Callable
from typing import Any

import pytz
from pyrfc3339 import parser as rfc3339_parser

from lithica import db, errors, model, rest
from lithica.func import auth, serialization, users, util


class InvalidExpirationError(errors.ValidationError):
    pass


class InvalidNoteError(errors.ValidationError):
    pass


class UserTokenSerializer(serialization.BaseSerializer):
    def __init__(self, user_token: model.UserToken, auth_user: model.User) -> None:
        self.user_token = user_token
        self.auth_user = auth_user

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        return {
            "user": self.serialize_user,
            "token": self.serialize_token,
            "note": self.serialize_note,
            "enabled": self.serialize_enabled,
            "expirationTime": self.serialize_expiration_time,
            "creationTime": self.serialize_creation_time,
            "lastEditTime": self.serialize_last_edit_time,
            "lastUsageTime": self.serialize_last_usage_time,
            "version": self.serialize_version,
        }

    def serialize_user(self) -> Any:
        return users.serialize_micro_user(self.user_token.user, self.auth_user)

    def serialize_creation_time(self) -> Any:
        return self.user_token.creation_time

    def serialize_last_edit_time(self) -> Any:
        return self.user_token.last_edit_time

    def serialize_last_usage_time(self) -> Any:
        return self.user_token.last_usage_time

    def serialize_token(self) -> Any:
        return self.user_token.token

    def serialize_note(self) -> Any:
        return self.user_token.note

    def serialize_enabled(self) -> Any:
        return self.user_token.enabled

    def serialize_expiration_time(self) -> Any:
        return self.user_token.expiration_time

    def serialize_version(self) -> Any:
        return self.user_token.version


def serialize_user_token(
    user_token: model.UserToken | None,
    auth_user: model.User,
    options: list[str] | None = None,
) -> rest.Response | None:
    if options is None:
        options = []
    if not user_token:
        return None
    return UserTokenSerializer(user_token, auth_user).serialize(options)


def get_by_user_and_token(user: model.User, token: str) -> model.UserToken | None:
    # The tokens are compared here rather than in the query, so that the
    # comparison takes the same time wherever the first difference is.
    candidate = token.encode("utf8")
    found = None
    for user_token in get_user_tokens(user):
        if hmac.compare_digest(user_token.token.encode("utf8"), candidate):
            found = user_token
    return found


def get_user_tokens(user: model.User) -> list[model.UserToken]:
    assert user
    return (
        db.session.query(model.UserToken)
        .filter(model.UserToken.user_id == user.user_id)
        .all()
    )


def create_user_token(user: model.User, enabled: bool) -> model.UserToken:
    assert user
    user_token = model.UserToken()
    user_token.user = user
    user_token.token = auth.generate_authorization_token()
    user_token.enabled = enabled
    user_token.creation_time = util.utcnow()
    user_token.last_usage_time = util.utcnow()
    return user_token


def update_user_token_enabled(user_token: model.UserToken, enabled: bool) -> None:
    assert user_token
    user_token.enabled = enabled
    update_user_token_edit_time(user_token)


def update_user_token_edit_time(user_token: model.UserToken) -> None:
    assert user_token
    user_token.last_edit_time = util.utcnow()


def update_user_token_expiration_time(
    user_token: model.UserToken, expiration_time_str: str
) -> None:
    assert user_token
    try:
        expiration_time = rfc3339_parser.parse(expiration_time_str, utc=True)
        expiration_time = expiration_time.astimezone(pytz.UTC)
        if expiration_time < util.utcnow().replace(tzinfo=pytz.UTC):
            raise InvalidExpirationError("Expiration cannot happen in the past")
        user_token.expiration_time = expiration_time
        update_user_token_edit_time(user_token)
    except ValueError as ex:
        raise InvalidExpirationError(
            f"Expiration is in an invalid format {expiration_time_str}"
        ) from ex


def update_user_token_note(user_token: model.UserToken, note: str) -> None:
    assert user_token
    note = note.strip() if note is not None else ""
    note = None if len(note) == 0 else note
    if util.value_exceeds_column_size(note, model.UserToken.note):
        raise InvalidNoteError("Note is too long.")
    user_token.note = note
    update_user_token_edit_time(user_token)


def bump_usage_time(user_token: model.UserToken) -> None:
    assert user_token
    user_token.last_usage_time = util.utcnow()
