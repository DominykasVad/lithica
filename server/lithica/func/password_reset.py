import hashlib
import hmac
import secrets
from datetime import timedelta

import sqlalchemy as sa
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


def mailed_recently(user: model.User) -> bool:
    """
    Whether the user was sent a reset link less than
    `password_reset_mail_interval` ago. The pending token's creation time
    says when: a new request replaces it, and a used one is gone, so a
    password just reset does not hold the next request back. Locks the
    user's row until the end of the transaction, so that of two requests at
    once only one finds no recent link.
    """
    assert user
    db.session.refresh(user, with_for_update=True)
    since = util.utcnow() - timedelta(
        seconds=config.config["password_reset_mail_interval"]
    )
    recent = _tokens_of(user).filter(model.PasswordResetToken.creation_time > since)
    return db.session.query(recent.exists()).scalar()


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


def consume_token(user_name: str, token: str) -> model.User:
    """
    Use up a password reset token of the account with this name or email,
    and return the account. Raises unless the token is the one that was
    mailed to it, has not expired and was not used before. Whatever fails,
    an unknown account, one with no token pending, a wrong, used or expired
    token, it is the same error, reached the same way: one query for the
    account's tokens, then the comparison, so that the answer does not tell
    whether the account exists.
    """
    name = sa.func.lower(user_name)
    entries = (
        db.session.query(model.PasswordResetToken)
        .join(model.User, model.User.user_id == model.PasswordResetToken.user_id)
        .filter(
            (sa.func.lower(model.User.name) == name)
            | (sa.func.lower(model.User.email) == name)
        )
        .all()
    )
    token_hash = _hash_token(token)
    now = util.utcnow()
    match = None
    for entry in entries:
        if (
            hmac.compare_digest(entry.token_hash, token_hash)
            and entry.expiration_time > now
        ):
            match = entry
    if match is None:
        raise InvalidPasswordResetTokenError("Invalid password reset token.")
    user_id = match.user_id
    # Deleting by id and counting the rows makes the token single-use even
    # when two requests present it at the same time: only one delete wins.
    deleted = (
        db.session.query(model.PasswordResetToken)
        .filter(
            model.PasswordResetToken.password_reset_token_id
            == match.password_reset_token_id
        )
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise InvalidPasswordResetTokenError("Invalid password reset token.")
    user = db.session.get(model.User, user_id)
    assert user
    _tokens_of(user).delete(synchronize_session=False)
    return user
