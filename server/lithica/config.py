import logging
import os
import re

import yaml

from lithica import errors

logger = logging.getLogger(__name__)


def _merge(left: dict, right: dict) -> dict:
    for key in right:
        if key in left:
            if isinstance(left[key], dict) and isinstance(right[key], dict):
                _merge(left[key], right[key])
            elif left[key] != right[key]:
                left[key] = right[key]
        else:
            left[key] = right[key]
    return left


def _container_config() -> dict:
    if "TEST_ENVIRONMENT" not in os.environ:
        for key in ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST"]:
            if key not in os.environ:
                raise errors.ConfigError(f'Environment variable "{key}" not set')
    return {
        "debug": True,
        "show_sql": int(os.getenv("LOG_SQL", 0)),
        "data_url": os.getenv("DATA_URL", "data/"),
        "data_dir": "/data/",
        "database": "postgresql://%(user)s:%(pass)s@%(host)s:%(port)d/%(db)s"
        % {
            "user": os.getenv("POSTGRES_USER"),
            "pass": os.getenv("POSTGRES_PASSWORD"),
            "host": os.getenv("POSTGRES_HOST"),
            "port": int(os.getenv("POSTGRES_PORT", 5432)),
            "db": os.getenv("POSTGRES_DB", os.getenv("POSTGRES_USER")),
        },
    }


def _file_config(filename: str) -> dict:
    with open(filename) as handle:
        return yaml.load(handle.read(), Loader=yaml.SafeLoader) or {}


def _running_inside_container() -> bool:
    env = os.environ.keys()
    return (
        os.path.exists("/.dockerenv")
        or "KUBERNETES_SERVICE_HOST" in env
        or "container" in env  # set by lxc/podman
    )


def default_secret() -> str:
    """Return the placeholder secret that ships in config.yaml.dist."""
    return _file_config("config.yaml.dist")["secret"]


def validate_secret() -> None:
    """
    Refuse a missing secret and the placeholder one. The secret salts the
    password hashes and signs the content URLs, and the placeholder is public.
    """
    secret = config.get("secret")
    if not isinstance(secret, str) or not secret.strip():
        raise errors.ConfigError(
            "'secret' is not set. Set it to a long random string in config.yaml."
        )
    if secret == default_secret():
        raise errors.ConfigError(
            "'secret' still has the default value from config.yaml.dist. "
            "Set it to a long random string in config.yaml."
        )


def validate_mail_domain() -> None:
    """
    Refuse to send mail without knowing our own address. Password reset
    mails carry a link to this site, and "domain" is the only trustworthy
    source for it.
    """
    if config["smtp"]["host"] and not config.get("domain"):
        raise errors.ConfigError(
            "'domain' is not set, but SMTP is configured. Set 'domain' to the "
            "public address of this site (for example https://booru.example.com); "
            "password reset mails link to it."
        )


def validate() -> None:
    """
    Check whether config doesn't contain errors that might prove
    lethal at runtime.
    """
    from lithica.func.auth import RANK_MAP

    validate_secret()

    for privilege, rank in config["privileges"].items():
        if rank not in RANK_MAP.values():
            raise errors.ConfigError(
                "Rank %r for privilege %r is missing" % (rank, privilege)
            )
    if config["default_rank"] not in RANK_MAP.values():
        raise errors.ConfigError(
            "Default rank %r is not on the list of known ranks"
            % (config["default_rank"])
        )

    for key in ["data_url", "data_dir"]:
        if not config[key]:
            raise errors.ConfigError("Service is not configured: %r is missing" % key)

    if not os.path.isabs(config["data_dir"]):
        raise errors.ConfigError("data_dir must be an absolute path")

    if not config["database"]:
        raise errors.ConfigError("Database is not configured")

    if config["webhooks"] and not isinstance(config["webhooks"], list):
        raise errors.ConfigError("Webhooks must be provided as a list of URLs")

    cors_origins = config["cors_origins"] or []
    if not isinstance(cors_origins, list) or not all(
        isinstance(origin, str) for origin in cors_origins
    ):
        raise errors.ConfigError("cors_origins must be a list of origins")
    for origin in cors_origins:
        if origin == "*":
            raise errors.ConfigError(
                "cors_origins does not accept '*'. List each allowed origin."
            )
        if not re.fullmatch(r"https?://[^/\s]+", origin):
            raise errors.ConfigError(
                "cors_origins entry %r is not an origin. Use the form "
                "'https://example.com', with no path or trailing slash." % origin
            )

    max_upload_size = config["max_upload_size"]
    if (
        isinstance(max_upload_size, bool)
        or not isinstance(max_upload_size, int)
        or max_upload_size <= 0
    ):
        raise errors.ConfigError("max_upload_size must be a positive number of bytes")

    lifetime = config["password_reset_token_lifetime"]
    if isinstance(lifetime, bool) or not isinstance(lifetime, int) or lifetime <= 0:
        raise errors.ConfigError(
            "password_reset_token_lifetime must be a positive number of seconds"
        )

    validate_mail_domain()

    if config["smtp"]["host"]:
        if not config["smtp"]["port"]:
            raise errors.ConfigError("SMTP host is set but port is not set")
        if not config["smtp"]["user"]:
            raise errors.ConfigError("SMTP host is set but username is not set")
        if not config["smtp"]["pass"]:
            raise errors.ConfigError("SMTP host is set but password is not set")
        if not config["smtp"]["from"]:
            raise errors.ConfigError(
                "From address must be set to use mail-based password reset"
            )


def _read_config() -> dict:
    ret = _file_config("config.yaml.dist")
    if os.path.isfile("config.yaml"):
        ret = _merge(ret, _file_config("config.yaml"))
    elif os.path.isdir("config.yaml"):
        logger.warning("'config.yaml' should be a file, not a directory, skipping")
    if _running_inside_container():
        ret = _merge(ret, _container_config())
    return ret


config = _read_config()
