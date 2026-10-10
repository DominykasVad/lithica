import logging
import os

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
