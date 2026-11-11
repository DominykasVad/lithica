"""
The rights an app token can carry, and the rights of the request at hand.

A right is a name for a fixed list of privileges. A request made with an
app token is granted a privilege only when one of the token's rights lists
it *and* its owner's rank grants it (lithica.func.auth.has_privilege); the
rank is read at request time, so the tokens of a demoted owner shrink with the rank.
Whatever is about accounts or tokens (`users:`, `user_tokens:`,
`app_tokens:` and `site_settings:`) is never granted to an app token,
whatever its rights.

The rights are defined here and nowhere else, not in the configuration.
Later work adds privileges to these lists; a right means its current list.
A stored right name that is not here grants nothing.

What the request carries is kept with the request's unit of work, as the
viewer is (lithica.func.visibility): never on the user object, never on a
thread. Work outside a request (the admin command, background jobs) has no
token and is unaffected.
"""

from collections.abc import Iterable, Sequence

from lithica import db

RIGHTS: dict[str, tuple[str, ...]] = {
    "read": (
        "posts:list",
        "posts:view",
        "posts:view:featured",
        "posts:reverse_search",
        "tags:list",
        "tags:view",
        "tag_categories:list",
        "tag_categories:view",
        "pools:list",
        "pools:view",
        "pool_categories:list",
        "pool_categories:view",
    ),
    "write": (
        "posts:create:identified",
        "posts:edit:tags",
        "posts:edit:safety",
        "posts:edit:listed",
        "posts:edit:source",
        "posts:edit:content",
        "posts:edit:document",
        "posts:edit:relations",
        "posts:edit:typed_relations",
        "posts:edit:external_ids",
        "posts:edit:flags",
        "posts:edit:notes",
        "posts:edit:thumbnail",
        "tags:create",
    ),
    "upload": ("uploads:create",),
}

# never granted to an app token
FORBIDDEN_PREFIXES = (
    "users:",
    "user_tokens:",
    "app_tokens:",
    "site_settings:",
    "jobs:",
)

_RIGHTS_KEY = "app_token_rights.rights"
_GRANTED_KEY = "app_token_rights.granted"


def privileges_of(rights: Iterable[str]) -> frozenset[str]:
    """The privileges these rights list; an unknown right lists none."""
    found: set[str] = set()
    for right in rights:
        found.update(RIGHTS.get(right, ()))
    return frozenset(found)


def is_forbidden(privilege: str) -> bool:
    return privilege.startswith(FORBIDDEN_PREFIXES)


def begin_app_token_request(rights: Sequence[str] | None) -> None:
    """The request was authenticated with an app token that carries these rights."""
    values = db.scope_values()
    if values is None:
        # An app token is only ever read in a request, which has a scope.
        # Without one its rights could not be kept, so it may not be used.
        raise RuntimeError("An app token is used outside a request.")
    values[_RIGHTS_KEY] = tuple(rights or ())
    values.pop(_GRANTED_KEY, None)


def current_rights() -> tuple[str, ...] | None:
    """The rights of the request's app token; None when it has none."""
    values = db.scope_values()
    if values is None:
        return None
    return values.get(_RIGHTS_KEY)


def note_granted() -> None:
    """A privilege was granted to the request's app token."""
    values = db.scope_values()
    if values is not None:
        values[_GRANTED_KEY] = True


def granted_anything() -> bool:
    values = db.scope_values()
    return bool(values is not None and values.get(_GRANTED_KEY))
