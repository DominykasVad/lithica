from collections.abc import Callable
from typing import Any

import pytz
from pyrfc3339 import parser as rfc3339_parser

from lithica import db, errors, model
from lithica.func import auth, serialization, users, util


class UserTokenNotFoundError(errors.NotFoundError):
    pass


class InvalidExpirationError(errors.ValidationError):
    pass


class InvalidNoteError(errors.ValidationError):
    pass


class UserTokenSerializer(serialization.BaseSerializer):
    """
    A login token. Its value (`token`) is known only to the request that
    created it, which passes it in; everywhere else it is null.
    """

    def __init__(
        self,
        user_token: model.UserToken,
        auth_user: model.User,
        value: str | None = None,
    ) -> None:
        self.user_token = user_token
        self.auth_user = auth_user
        self.value = value

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        return {
            "id": self.serialize_id,
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

    def serialize_id(self) -> Any:
        return self.user_token.user_token_id

    def serialize_user(self) -> Any:
        return users.serialize_micro_user(self.user_token.user, self.auth_user)

    def serialize_creation_time(self) -> Any:
        return self.user_token.creation_time

    def serialize_last_edit_time(self) -> Any:
        return self.user_token.last_edit_time

    def serialize_last_usage_time(self) -> Any:
        return self.user_token.last_usage_time

    def serialize_token(self) -> Any:
        return self.value

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
    value: str | None = None,
) -> serialization.Response | None:
    if options is None:
        options = []
    if not user_token:
        return None
    return UserTokenSerializer(user_token, auth_user, value).serialize(options)


def get_by_user_and_token(user: model.User, token: str) -> model.UserToken | None:
    """
    The token of the user, of any kind, whose value this is. Found by the
    hash of the value: nothing of the value itself is compared.
    """
    return (
        db.session.query(model.UserToken)
        .filter(model.UserToken.user_id == user.user_id)
        .filter(model.UserToken.token_hash == auth.hash_token(token))
        .one_or_none()
    )


def parse_token_id(text: str) -> int | None:
    """A token's id from a path; None for anything that is not one."""
    if not text.isascii() or not text.isdigit() or len(text) > 18:
        return None
    return int(text)


def get_by_user_and_id(
    user: model.User, token_id: int | None, kind: str = model.UserToken.KIND_LOGIN
) -> model.UserToken | None:
    """The user's token of this kind with this id; None for any other."""
    if token_id is None:
        return None
    return (
        db.session.query(model.UserToken)
        .filter(model.UserToken.user_id == user.user_id)
        .filter(model.UserToken.user_token_id == token_id)
        .filter(model.UserToken.kind == kind)
        .one_or_none()
    )


def get_existing_by_user_and_id(
    user: model.User, token_id: int | None
) -> model.UserToken:
    user_token = get_by_user_and_id(user, token_id)
    if user_token is None:
        raise UserTokenNotFoundError("User token not found.")
    return user_token


def get_user_tokens(
    user: model.User, kind: str = model.UserToken.KIND_LOGIN
) -> list[model.UserToken]:
    assert user
    return (
        db.session.query(model.UserToken)
        .filter(model.UserToken.user_id == user.user_id)
        .filter(model.UserToken.kind == kind)
        .order_by(model.UserToken.user_token_id)
        .all()
    )


def new_token(
    user: model.User, enabled: bool, kind: str, value: str
) -> model.UserToken:
    """A token of the user with this value, of which only the hash is kept."""
    assert user
    user_token = model.UserToken()
    user_token.user = user
    user_token.kind = kind
    user_token.token_hash = auth.hash_token(value)
    user_token.enabled = enabled
    user_token.creation_time = util.utcnow()
    user_token.last_usage_time = util.utcnow()
    return user_token


def create_user_token(user: model.User, enabled: bool) -> tuple[model.UserToken, str]:
    """A new login token, and its value: the one time the value is known."""
    value = auth.generate_authorization_token()
    return new_token(user, enabled, model.UserToken.KIND_LOGIN, value), value


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
    stripped_note = note.strip() if note is not None else ""
    new_note = None if len(stripped_note) == 0 else stripped_note
    if util.value_exceeds_column_size(new_note, model.UserToken.note):
        raise InvalidNoteError("Note is too long.")
    user_token.note = new_note
    update_user_token_edit_time(user_token)


def bump_usage_time(user_token: model.UserToken) -> None:
    assert user_token
    user_token.last_usage_time = util.utcnow()
