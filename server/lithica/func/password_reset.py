import hashlib
import hmac
import secrets
from datetime import timedelta

import sqlalchemy.orm as sa_orm

from lithica import config, db, errors, model
from lithica.func import util


class InvalidPasswordResetTokenError(errors.ValidationError):
    pass


def _hash_token(token: str) -> str:
    # The token is 256 random bits, so a plain digest is enough: there is
    # nothing to brute-force, and it only has to keep a leaked table useless.
    return hashlib.sha256(token.encode("utf8")).hexdigest()


def _tokens_of(user: model.User) -> sa_orm.Query:
    return db.session.query(model.PasswordResetToken).filter(
        model.PasswordResetToken.user_id == user.user_id
    )


def create_token(user: model.User) -> str:
    """
    Start a password reset for the user and return the token to mail them.
    Any reset the user had pending stops working.
    """
    assert user
    _tokens_of(user).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    now = util.utcnow()
    entry = model.PasswordResetToken()
    entry.user_id = user.user_id
    entry.token_hash = _hash_token(token)
    entry.creation_time = now
    entry.expiration_time = now + timedelta(
        seconds=config.config["password_reset_token_lifetime"]
    )
    db.session.add(entry)
    db.session.flush()
    return token


def consume_token(user: model.User, token: str) -> None:
    """
    Use up the user's password reset token. Raises unless the token is the
    one that was mailed to them, has not expired and was not used before.
    """
    assert user
    token_hash = _hash_token(token)
    now = util.utcnow()
    matching_id = None
    for entry in _tokens_of(user).all():
        if (
            hmac.compare_digest(entry.token_hash, token_hash)
            and entry.expiration_time > now
        ):
            matching_id = entry.password_reset_token_id
    if matching_id is None:
        raise InvalidPasswordResetTokenError("Invalid password reset token.")
    # Deleting by id and counting the rows makes the token single-use even
    # when two requests present it at the same time: only one delete wins.
    deleted = (
        db.session.query(model.PasswordResetToken)
        .filter(model.PasswordResetToken.password_reset_token_id == matching_id)
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise InvalidPasswordResetTokenError("Invalid password reset token.")
    _tokens_of(user).delete(synchronize_session=False)
