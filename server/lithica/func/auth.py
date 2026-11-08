import hashlib
import hmac
import secrets
from collections import OrderedDict

from nacl import pwhash
from nacl.exceptions import InvalidkeyError

from lithica import config, db, errors, model
from lithica.func import app_token_rights, util

RANK_MAP: OrderedDict[str, str] = OrderedDict(
    [
        (model.User.RANK_ANONYMOUS, "anonymous"),
        (model.User.RANK_RESTRICTED, "restricted"),
        (model.User.RANK_REGULAR, "regular"),
        (model.User.RANK_POWER, "power"),
        (model.User.RANK_MODERATOR, "moderator"),
        (model.User.RANK_ADMINISTRATOR, "administrator"),
        (model.User.RANK_NOBODY, "nobody"),
    ]
)


def get_password_hash(salt: str, password: str) -> tuple[str, int]:
    """Retrieve argon2id password hash."""
    return (
        pwhash.argon2id.str(
            (config.config["secret"] + salt + password).encode("utf8")
        ).decode("utf8"),
        3,
    )


def get_sha256_legacy_password_hash(salt: str, password: str) -> tuple[str, int]:
    """Retrieve old-style sha256 password hash."""
    digest = hashlib.sha256()
    digest.update(config.config["secret"].encode("utf8"))
    digest.update(salt.encode("utf8"))
    digest.update(password.encode("utf8"))
    return digest.hexdigest(), 2


def get_sha1_legacy_password_hash(salt: str, password: str) -> tuple[str, int]:
    """Retrieve old-style sha1 password hash."""
    digest = hashlib.sha1()
    digest.update(b"1A2/$_4xVa")
    digest.update(salt.encode("utf8"))
    digest.update(password.encode("utf8"))
    return digest.hexdigest(), 1


def create_password() -> str:
    alphabet = {
        "c": list("bcdfghijklmnpqrstvwxyz"),
        "v": list("aeiou"),
        "n": list("0123456789"),
    }
    pattern = "cvcvnncvcv"
    return "".join(secrets.choice(alphabet[type]) for type in list(pattern))


def is_valid_password(user: model.User, password: str) -> bool:
    assert user
    salt, valid_hash = user.password_salt, user.password_hash
    if salt is None:
        # no salt was ever stored, so no password can match
        return False

    try:
        return pwhash.verify(
            user.password_hash.encode("utf8"),
            (config.config["secret"] + salt + password).encode("utf8"),
        )
    except InvalidkeyError:
        possible_hashes = [
            get_sha256_legacy_password_hash(salt, password)[0],
            get_sha1_legacy_password_hash(salt, password)[0],
        ]
        # no early exit: every candidate is compared, in constant time
        matches = [
            hmac.compare_digest(valid_hash.encode("utf8"), possible_hash.encode("utf8"))
            for possible_hash in possible_hashes
        ]
        if any(matches):
            # Convert the user password hash to the new hash
            new_hash, revision = get_password_hash(salt, password)
            user.password_hash = new_hash
            user.password_revision = revision
            db.session.commit()
            return True

    return False


def is_valid_token(user_token: model.UserToken | None) -> bool:
    """
    Token must be enabled and if it has an expiration, it must be
    greater than now.
    """
    if user_token is None:
        return False
    if not user_token.enabled:
        return False
    if (
        user_token.expiration_time is not None
        and user_token.expiration_time < util.utcnow()
    ):
        return False
    return True


def rank_grants(user: model.User, privilege_name: str) -> bool:
    """Whether the user's rank grants the privilege, whatever the request."""
    assert user
    all_ranks = list(RANK_MAP.keys())
    assert privilege_name in config.config["privileges"]
    # a site that is for its users only: without logging in, nothing at all
    if (
        config.config.get("visibility") == "login"
        and user.rank == model.User.RANK_ANONYMOUS
    ):
        return False
    assert user.rank in all_ranks
    minimal_rank = util.flip(RANK_MAP)[config.config["privileges"][privilege_name]]
    good_ranks = all_ranks[all_ranks.index(minimal_rank) :]
    return user.rank in good_ranks


def has_privilege(user: model.User, privilege_name: str) -> bool:
    """
    Whether the request may do this as the user. With an app token, only
    what one of its rights lists and the user's rank grants, and never
    anything about accounts or tokens (lithica.func.app_token_rights).
    """
    rights = app_token_rights.current_rights()
    if rights is not None:
        assert privilege_name in config.config["privileges"]
        if app_token_rights.is_forbidden(privilege_name):
            return False
        if privilege_name not in app_token_rights.privileges_of(rights):
            return False
    granted = rank_grants(user, privilege_name)
    if granted and rights is not None:
        app_token_rights.note_granted()
    return granted


def verify_privilege(user: model.User, privilege_name: str) -> None:
    assert user
    if not has_privilege(user, privilege_name):
        raise errors.AuthError("Insufficient privileges to do this.")


def is_self(auth_user: model.User, user: model.User) -> bool:
    """
    Whether the request is the user acting on their own account, for what
    one may see or do of one's own account without a privilege. A request
    made with an app token never is: it reaches nothing of the account.
    """
    return (
        auth_user.user_id == user.user_id and app_token_rights.current_rights() is None
    )


def verify_app_token_changed_something() -> None:
    """
    An edit that names nothing to change still bumps the resource's version
    (and a post's edit time and snapshot) without asking any privilege. With
    an app token, such an edit is refused: the token may change only what a
    privilege it was granted allows.
    """
    if (
        app_token_rights.current_rights() is not None
        and not app_token_rights.granted_anything()
    ):
        raise errors.AuthError("Insufficient privileges to do this.")


def hash_token(value: str) -> str:
    """What is stored of a token: SHA-256 of its value, in hex."""
    return hashlib.sha256(value.encode("utf8")).hexdigest()


APP_TOKEN_PREFIX = "lithica_app_"


def generate_authorization_token() -> str:
    """The value of a new login token."""
    return secrets.token_urlsafe(32)


def generate_app_token() -> str:
    """The value of a new app token: recognisable by its prefix."""
    return APP_TOKEN_PREFIX + secrets.token_urlsafe(32)
