"""
App tokens: named tokens a user makes for another application, each with a
set of rights (lithica.func.app_token_rights). They are rows of the token
table of kind `app`, stored hashed like login tokens, and authenticate with
the same Token scheme.
"""

from collections.abc import Callable
from typing import Any

from lithica import db, errors, model
from lithica.func import app_token_rights, auth, serialization, user_tokens, users

NAME_MAX_LENGTH = 128


class AppTokenNotFoundError(errors.NotFoundError):
    pass


class InvalidAppTokenNameError(errors.ValidationError):
    pass


class InvalidAppTokenRightsError(errors.ValidationError):
    pass


class AppTokenSerializer(serialization.BaseSerializer):
    """
    An app token. Its value (`token`) is known only to the request that
    created it, which passes it in; everywhere else it is null.
    """

    def __init__(
        self,
        app_token: model.UserToken,
        auth_user: model.User,
        value: str | None = None,
    ) -> None:
        self.app_token = app_token
        self.auth_user = auth_user
        self.value = value

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        return {
            "id": lambda: self.app_token.user_token_id,
            "user": lambda: users.serialize_micro_user(
                self.app_token.user, self.auth_user
            ),
            "name": lambda: self.app_token.note,
            "rights": lambda: list(self.app_token.rights or []),
            "token": lambda: self.value,
            "enabled": lambda: self.app_token.enabled,
            "expirationTime": lambda: self.app_token.expiration_time,
            "creationTime": lambda: self.app_token.creation_time,
            "lastEditTime": lambda: self.app_token.last_edit_time,
            "lastUsageTime": lambda: self.app_token.last_usage_time,
            "version": lambda: self.app_token.version,
        }


def serialize_app_token(
    app_token: model.UserToken,
    auth_user: model.User,
    options: list[str] | None = None,
    value: str | None = None,
) -> serialization.Response:
    return AppTokenSerializer(app_token, auth_user, value).serialize(options or [])


def get_app_tokens(user: model.User) -> list[model.UserToken]:
    return user_tokens.get_user_tokens(user, model.UserToken.KIND_APP)


def get_existing_by_user_and_id(
    user: model.User, token_id: int | None
) -> model.UserToken:
    app_token = user_tokens.get_by_user_and_id(user, token_id, model.UserToken.KIND_APP)
    if app_token is None:
        raise AppTokenNotFoundError("App token not found.")
    return app_token


def _check_name(name: Any) -> str:
    stripped = name.strip() if isinstance(name, str) else ""
    if not stripped:
        raise InvalidAppTokenNameError("An app token needs a name.")
    if len(stripped) > NAME_MAX_LENGTH:
        raise InvalidAppTokenNameError(
            "The name of an app token is at most %d characters." % NAME_MAX_LENGTH
        )
    return stripped


def _check_rights(owner: model.User, rights: Any) -> list[str]:
    if not isinstance(rights, list) or not rights:
        raise InvalidAppTokenRightsError("An app token needs at least one right.")
    checked: list[str] = []
    for right in rights:  # pyright: ignore[reportUnknownVariableType] - checked here
        if not isinstance(right, str) or right not in app_token_rights.RIGHTS:
            raise InvalidAppTokenRightsError("Unknown right: %r." % (right,))
        # a right of which the owner holds nothing would be dead weight now
        # and a grant later, when the owner is promoted: refused
        if not any(
            auth.rank_grants(owner, privilege)
            for privilege in app_token_rights.RIGHTS[right]
        ):
            raise InvalidAppTokenRightsError(
                "The user holds none of the privileges of the right %r." % right
            )
        if right not in checked:
            checked.append(right)
    return checked


def create_app_token(
    owner: model.User, name: Any, rights: Any, enabled: bool
) -> tuple[model.UserToken, str]:
    """A new app token of the owner, and its value: the one time it is known."""
    checked_name = _check_name(name)
    checked_rights = _check_rights(owner, rights)
    value = auth.generate_app_token()
    app_token = user_tokens.new_token(owner, enabled, model.UserToken.KIND_APP, value)
    app_token.note = checked_name
    app_token.rights = checked_rights
    # in use once it is used, not when it is made
    app_token.last_usage_time = None
    return app_token, value


def update_app_token_name(app_token: model.UserToken, name: Any) -> None:
    app_token.note = _check_name(name)
    user_tokens.update_user_token_edit_time(app_token)


def delete_app_token(app_token: model.UserToken) -> None:
    db.session.delete(app_token)
