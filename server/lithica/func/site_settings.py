"""Declared site settings; database overrides live only in the current scope."""

import logging
from dataclasses import dataclass
from typing import Any, Literal, cast

import sqlalchemy as sa

from lithica import config, db, errors, model
from lithica.func import util

logger = logging.getLogger(__name__)
Type = Literal["boolean", "integer", "string", "choice", "list"]
_CACHE = "site_settings.rows"
_CACHE_VERSION = "site_settings.version"
HIDING_TAGS_SCOPE_KEY = "visibility.hiding_tags"
FEATURES = ("pools", "favorites", "scores", "notes", "comments")


@dataclass(frozen=True)
class Setting:
    name: str
    type: Type
    runtime: bool = True
    choices: tuple[str, ...] = ()
    min: int | None = None
    max_length: int | None = None
    blank: bool = True

    def validate(self, value: Any) -> bool:
        # Any: input is untrusted JSON; use exact types so bool is not an integer.
        if self.type == "boolean":
            return type(value) is bool
        if self.type == "integer":
            return type(value) is int and (self.min is None or value >= self.min)
        if self.type == "choice":
            return isinstance(value, str) and value in self.choices
        if self.type == "list":
            return isinstance(value, list) and all(isinstance(v, str) for v in value)
        return (
            isinstance(value, str)
            and (self.blank or bool(value.strip()))
            and (self.max_length is None or len(value) <= self.max_length)
        )


SETTINGS = {
    item.name: item
    for item in (
        Setting("document_versions_kept", "integer", min=0),
        Setting("visibility", "choice", choices=config.VISIBILITIES),
        Setting("nsfw_tag", "string", max_length=128, blank=False),
        Setting("nsfw_hide_names", "boolean"),
        Setting("share_links_nsfw", "boolean"),
        Setting("password_reset_mail_interval", "integer", min=0),
        Setting("name", "string", max_length=100, blank=False),
        Setting("contact_email", "string", max_length=64),
        Setting("default_rank", "choice", choices=("restricted", "regular", "power")),
        *(Setting("features." + name, "boolean") for name in FEATURES),
        Setting("jobs.worker", "boolean", runtime=False),
        Setting("jobs.poll_interval", "integer", runtime=False, min=1),
        Setting("modules", "list", runtime=False),
        Setting("max_upload_size", "integer", runtime=False, min=1),
        Setting("api_docs", "boolean", runtime=False),
        Setting("domain", "string", runtime=False),
        Setting("cors_origins", "list", runtime=False),
        Setting("allow_private_downloads", "boolean", runtime=False),
    )
}


def starting(name: str) -> Any:
    value: Any = config.config
    for part in name.split("."):
        value = value[part]
    return value


def stored() -> dict[str, Any]:
    values = db.scope_values()
    if values is not None and _CACHE in values:
        return values[_CACHE]
    table = cast(sa.Table, model.SiteSetting.__table__)
    # A Connection Core select bypasses do_orm_execute and its visibility hook.
    versions = cast(sa.Table, model.SiteSettingsVersion.__table__)
    result = (
        db.session.connection()
        .execute(
            sa.select(versions.c.version, table.c.name, table.c.value)
            .select_from(versions.outerjoin(table, sa.true()))
            .where(versions.c.id == 1)
        )
        .all()
    )
    rows = {row.name: row.value for row in result if row.name is not None}
    if values is not None:
        values[_CACHE] = rows
        values[_CACHE_VERSION] = result[0].version
    return rows


def get(name: str) -> Any:
    declaration = SETTINGS[name]
    rows = stored() if declaration.runtime else {}
    if name in rows:
        if declaration.validate(rows[name]):
            return rows[name]
        logger.warning("Invalid stored site setting: %s; using config.yaml", name)
    return starting(name)


def version(*, lock: bool = False) -> int:
    table = cast(sa.Table, model.SiteSettingsVersion.__table__)
    stmt = sa.select(table.c.version).where(table.c.id == 1)
    if lock:
        stmt = stmt.with_for_update()
    return db.session.connection().execute(stmt).scalar_one()


def describe() -> dict[str, Any]:
    rows = stored()
    values = db.scope_values()
    snapshot_version = values[_CACHE_VERSION] if values is not None else version()
    return {
        "version": snapshot_version,
        "fileLinksSigned": bool(config.config.get("file_link_secret")),
        "settings": [
            {
                "name": item.name,
                "type": item.type,
                "value": get(item.name),
                "startingValue": starting(item.name),
                "stored": item.name in rows,
                "runtime": item.runtime,
                **({"choices": list(item.choices)} if item.choices else {}),
                **({"min": item.min} if item.min is not None else {}),
            }
            for item in SETTINGS.values()
        ],
    }


def update(expected: int, changes: dict[str, Any], user: model.User | None) -> None:
    for name, value in changes.items():
        item = SETTINGS.get(name)
        if (
            item is None
            or not item.runtime
            or (value is not None and not item.validate(value))
        ):
            raise errors.ValidationError("Invalid site setting: %s" % name)
    current = version(lock=True)
    if expected != current:
        raise errors.IntegrityError("Site settings have changed. Reload them.")
    table = cast(sa.Table, model.SiteSetting.__table__)
    conn = db.session.connection()
    values = db.scope_values()
    # Authentication may have read settings before another writer committed.
    # Reuse a snapshot only when it belongs to the version we locked.
    if values is not None and values.get(_CACHE_VERSION) != current:
        values.pop(_CACHE, None)
    rows = dict(stored())
    changed = False
    for name, value in changes.items():
        if (value is None and name not in rows) or (
            name in rows and type(rows[name]) is type(value) and rows[name] == value
        ):
            continue
        conn.execute(table.delete().where(table.c.name == name))
        rows.pop(name, None)
        if value is not None:
            conn.execute(
                table.insert().values(
                    name=name,
                    value=value,
                    last_edit_time=util.utcnow(),
                    user_id=user.user_id if user else None,
                )
            )
            rows[name] = value
        logger.info(
            "Site setting %s changed by %s", name, user.name if user else "admin CLI"
        )
        changed = True
    if changed:
        table_version = cast(sa.Table, model.SiteSettingsVersion.__table__)
        conn.execute(
            table_version.update()
            .where(table_version.c.id == 1)
            .values(version=current + 1)
        )
    values = db.scope_values()
    if values is not None:
        values[_CACHE] = rows
        values[_CACHE_VERSION] = current + int(changed)
        values.pop(HIDING_TAGS_SCOPE_KEY, None)


def enabled(feature: str) -> bool:
    return get("features." + feature) is True


FEATURE_FIELDS = {
    "post": {
        "scores": {"score", "ownScore"},
        "favorites": {"ownFavorite", "favoriteCount", "favoritedBy"},
        "comments": {"commentCount", "comments"},
        "notes": {"noteCount", "notes"},
        "pools": {"pools"},
    },
    "user": {
        "comments": {"commentCount"},
        "favorites": {"favoritePostCount"},
        "scores": {"likedPostCount", "dislikedPostCount"},
    },
    "comment": {"scores": {"score", "ownScore"}},
}


def active_fields(resource: str, fields: list[str]) -> list[str]:
    hidden = set().union(
        *(
            names
            for feature, names in FEATURE_FIELDS.get(resource, {}).items()
            if not enabled(feature)
        )
    )
    return [name for name in fields if name not in hidden]
