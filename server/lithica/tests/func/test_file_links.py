"""Signed addresses of post files and thumbnails (file_link_secret)."""

import logging
import shutil
import subprocess
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from lithica import config, errors, model
from lithica.func import file_links, posts, users

SECRET = "test-secret-of-signed-file-links-0123456789"


def _moment(seconds: int) -> datetime:
    """Seconds since the epoch as the naive UTC the server stores."""
    return datetime(1970, 1, 1) + timedelta(seconds=seconds)


@pytest.fixture
def post():
    post = model.Post()
    post.post_id = 5
    post.mime_type = "image/png"
    return post


def test_without_a_secret_the_addresses_are_as_they_always_were(config_injector, post):
    config_injector({"data_url": "http://example.com/data/", "secret": "test"})
    hash_ = posts.get_post_security_hash(5)
    assert posts.get_post_content_url(post) == (
        "http://example.com/data/posts/5_%s.png" % hash_
    )
    assert posts.get_post_thumbnail_url(post) == (
        "http://example.com/data/generated-thumbnails/5_%s.jpg" % hash_
    )


def test_with_a_secret_the_addresses_are_signed(config_injector, post, fake_datetime):
    config_injector({"data_url": "data/", "secret": "test", "file_link_secret": SECRET})
    with fake_datetime("2026-10-27 15:04:05"):
        url = posts.get_post_content_url(post)
        thumbnail = posts.get_post_thumbnail_url(post)
    hash_ = posts.get_post_security_hash(5)
    # the start of the day after tomorrow, UTC
    expires = 1793232000
    assert _moment(expires) == datetime(2026, 10, 29)
    assert url == "data/posts/5_%s.png?e=%d&s=%s" % (
        hash_,
        expires,
        file_links.signature("/posts/5_%s.png" % hash_, expires, SECRET),
    )
    query = parse_qs(urlsplit(thumbnail).query)
    assert query["e"] == [str(expires)]
    assert query["s"] == [
        file_links.signature("/generated-thumbnails/5_%s.jpg" % hash_, expires, SECRET)
    ]


def test_an_avatar_is_not_signed(config_injector, user_factory):
    config_injector(
        {
            "data_url": "data/",
            "secret": "test",
            "file_link_secret": SECRET,
            "thumbnails": {"avatar_width": 30, "avatar_height": 30},
        }
    )
    user = user_factory(name="someone")
    user.avatar_style = model.User.AVATAR_MANUAL
    assert "?" not in users.get_avatar_url(user)


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-10-27 00:00:00", datetime(2026, 10, 29)),
        ("2026-10-27 12:00:00", datetime(2026, 10, 29)),
        ("2026-10-27 23:59:59", datetime(2026, 10, 29)),
        ("2026-10-28 00:00:00", datetime(2026, 10, 30)),
        # across a month and a year
        ("2026-12-31 08:00:00", datetime(2027, 1, 2)),
        ("2028-02-28 08:00:00", datetime(2028, 3, 1)),
    ],
)
def test_the_expiry_is_the_same_for_a_day_and_24_to_48_hours_away(now, expected):
    stamp = datetime.fromisoformat(now)
    expires = file_links.expiry(stamp)
    assert _moment(expires) == expected
    left = expires - (stamp - datetime(1970, 1, 1)).total_seconds()
    assert 24 * 3600 < left <= 48 * 3600


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")
def test_the_signature_is_nginxs_secure_link_md5():
    # the formula as nginx's documentation of secure_link works it out,
    # with openssl rather than with Python
    path, expires = "/posts/5_0123456789abcdef.png", 1793232000
    text = ("%d%s %s" % (expires, path, SECRET)).encode()
    digest = subprocess.run(
        ["openssl", "md5", "-binary"], input=text, check=True, capture_output=True
    ).stdout
    encoded = subprocess.run(
        ["openssl", "base64"], input=digest, check=True, capture_output=True
    ).stdout.decode()
    # tr '+/' '-_' | tr -d '=', as nginx's documentation does it
    openssl = encoded.strip().replace("+", "-").replace("/", "_").replace("=", "")
    assert file_links.signature(path, expires, SECRET) == openssl


@pytest.mark.parametrize(
    "secret",
    ["short", "x" * 31, "with space " + "x" * 32, 'quote"' + "x" * 32, "$" + "x" * 32],
)
def test_a_secret_nginx_could_misread_is_refused(config_injector, secret):
    config_injector({"file_link_secret": secret})
    with pytest.raises(errors.ConfigError):
        config.validate_file_link_secret()


def test_a_good_secret_and_none_are_taken(config_injector):
    config_injector({"file_link_secret": SECRET})
    config.validate_file_link_secret()
    config_injector({"file_link_secret": None})
    config.validate_file_link_secret()


@pytest.mark.parametrize("visibility", ["nsfw-login", "login"])
def test_a_closed_site_without_a_secret_is_warned_of(
    config_injector, caplog, visibility
):
    config_injector({"visibility": visibility, "file_link_secret": None})
    with caplog.at_level(logging.WARNING, logger="lithica.config"):
        config.validate_file_link_secret()
    assert len(caplog.records) == 1
    assert "reachable by anyone with an address" in caplog.records[0].getMessage()


@pytest.mark.parametrize(
    "settings",
    [
        {"visibility": "open", "file_link_secret": None},
        {"file_link_secret": None},
        {"visibility": "nsfw-login", "file_link_secret": SECRET},
        {"visibility": "login", "file_link_secret": SECRET},
    ],
)
def test_an_open_site_or_signed_links_are_not_warned_of(
    config_injector, caplog, settings
):
    config_injector(settings)
    with caplog.at_level(logging.WARNING, logger="lithica.config"):
        config.validate_file_link_secret()
    assert caplog.records == []
