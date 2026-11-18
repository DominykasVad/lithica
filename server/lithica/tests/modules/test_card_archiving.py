import logging
from collections.abc import Callable
from time import sleep
from unittest.mock import patch

import pytest

from lithica import config, db, model
from lithica.func import documents, jobs, net, posts
from lithica.modules.cards import archiving
from lithica.modules.cards.model import ArchivedLink, Card
from lithica.tests.api.http import assert_error, ok
from lithica.tests.conftest import ApiClient
from lithica.tests.func.test_net_download_guard import (
    PUBLIC_IP,
)
from lithica.tests.func.test_net_download_guard import (
    network as network,
)
from lithica.tests.func.test_net_download_guard import (
    web as web,
)
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_data_creation import create, external
from lithica.tests.modules.test_card_file_replace import replace as replace_file
from lithica.tests.modules.test_card_upload_documents import upload


@pytest.fixture
def client(site: Callable[[list[str]], ApiClient]) -> ApiClient:
    config.config["privileges"].update(
        {
            "posts:view": "anonymous",
            "posts:edit:document": "regular",
            "posts:edit:external_ids": "regular",
            "posts:edit:typed_relations": "regular",
            "uploads:create": "regular",
        }
    )
    return site(["cards"])


def _path(post_id: int) -> str:
    return f"/modules/cards/post/{post_id}"


def _card(client: ApiClient, user: model.User, *urls: str, **options: object) -> int:
    raw = cards.v3_card(first_mes=" ".join(f"![private-alt]({url})" for url in urls))
    return ok(create(client, user, raw, **options))["post"]["id"]


def _queue(client: ApiClient, user: model.User, post_id: int, **options: bool) -> bool:
    return ok(client.post(f"{_path(post_id)}/archive", user=user, body=options))[
        "queued"
    ]


def _answer(client: ApiClient, user: model.User | None, post_id: int) -> dict:
    return ok(client.get(_path(post_id), user=user))


def test_archive_downloads_inherits_and_reuses(client, user, web, monkeypatch) -> None:
    monkeypatch.setitem(config.config, "allow_private_downloads", True)
    monkeypatch.setitem(config.config, "max_dl_filesize", 8192)
    monkeypatch.setattr(net, "DOWNLOAD_TIMEOUT", 0.3)
    base = f"http://127.0.0.1:{web.port}"
    png = cards.picture(70)
    web.routes.update(
        {
            "/ok": (200, {}, png),
            "/too-large": (200, {}, b"x" * 8193),
            "/not-media": (200, {}, b"hello"),
            "/missing": (404, {}, b"missing"),
        }
    )
    first = _card(
        client,
        user,
        *(base + suffix for suffix in web.routes),
        safety="unsafe",
        tags=["nsfw"],
    )
    original_hash = db.session.get(Card, first).data_hash
    assert _queue(client, user, first)
    assert not _queue(client, user, first)
    assert _answer(client, user, first)["archiveQueued"] is True
    assert jobs.work_once()
    answer = _answer(client, user, first)
    assert answer["archiveQueued"] is False
    assert [link["status"] for link in answer["links"]] == [
        "archived",
        "failed",
        "failed",
        "failed",
    ]
    assert [link["reason"] for link in answer["links"]] == [
        None,
        "too-large",
        "not-media",
        "failed",
    ]
    assert all(
        link["attempts"] == 1 and link["lastAttemptTime"] for link in answer["links"]
    )
    picture = posts.get_post_by_id(answer["links"][0]["post"]["id"])
    assert (picture.kind, picture.listed, picture.safety, picture.source) == (
        "media",
        False,
        "unsafe",
        base + "/ok",
    )
    assert [tag.first_name for tag in picture.tags] == ["nsfw"]
    assert db.session.get(Card, first).data_hash == original_hash
    assert documents.get(posts.get_post_by_id(first)).version == 0
    assert all(link["post"] is None for link in answer["links"][1:])

    second = _card(client, user, base + "/ok", base + "/another")
    web.routes["/another"] = (200, {}, png)
    web.requests.clear()
    assert _queue(client, user, second)
    assert jobs.work_once()
    assert [path for _, path in web.requests] == ["/another"]
    assert all(
        link["post"]["id"] == picture.post_id
        for link in _answer(client, user, second)["links"]
    )
    assert {
        (relation.to_post_id, relation.type)
        for relation in db.session.query(model.PostTypedRelation).filter_by(
            from_post_id=picture.post_id
        )
    } == {(first, "archived-from"), (second, "archived-from")}


def test_job_failure_diagnostics_do_not_expose_card_text(
    client, user, web, network, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(net, "DOWNLOAD_TIMEOUT", 0.1)
    network.hosts.update(
        {
            "private-card.test": ["10.0.0.37"],
            "public-card.test": [PUBLIC_IP],
            "refused-card.test": [PUBLIC_IP],
        }
    )

    def timeout() -> tuple[int, dict[str, str], bytes]:
        sleep(0.4)
        return 200, {}, b""

    web.routes["/secret-timeout"] = timeout
    web.routes["/secret-redirect"] = (
        302,
        {"Location": "http://private-card.test/secret"},
        b"",
    )
    refused = "http://private-card.test/secret"
    post_id = _card(
        client,
        user,
        refused,
        "http://public-card.test/secret-redirect",
        "http://public-card.test/secret-timeout",
    )
    with caplog.at_level(logging.INFO, logger=archiving.__name__):
        assert _queue(client, user, post_id)
        assert jobs.work_once()
    assert network.connections == [PUBLIC_IP, PUBLIC_IP]
    assert [link["reason"] for link in _answer(client, user, post_id)["links"]] == [
        "failed",
        "failed",
        "failed",
    ]
    assert "found=3 archived=0 reused=0 failed=3" in caplog.text

    other = _card(client, user, "http://refused-card.test/secret-connection")
    with (
        caplog.at_level(logging.INFO, logger=archiving.__name__),
        patch.object(
            net.socket,
            "create_connection",
            side_effect=ConnectionRefusedError("10.0.0.38"),
        ),
    ):
        assert _queue(client, user, other)
        assert jobs.work_once()
    assert _answer(client, user, other)["links"][0]["reason"] == "failed"
    for value in ("private-alt", "card.test", "/secret", "10.0.0.37", "10.0.0.38"):
        assert value not in caplog.text

    caplog.clear()
    assert_error(
        client.post("/uploads", user=user, body={"contentUrl": refused}),
        net.DownloadError,
        net.GENERIC_DOWNLOAD_ERROR,
    )
    assert "Download from host 'private-card.test' failed" in caplog.text
    assert "10.0.0.37" in caplog.text


@pytest.mark.parametrize("privilege", ["uploads:create", "posts:edit:typed_relations"])
def test_archive_requires_both_privileges(client, user, privilege) -> None:
    post_id = _card(client, user, "https://unused.test/a")
    config.config["privileges"][privilege] = "moderator"
    assert (
        client.post(f"{_path(post_id)}/archive", user=user, body={}).status_code == 403
    )
    assert db.session.query(model.Job).filter_by(type=archiving.JOB).count() == 0


def test_batches_and_only_retries_failures_on_request(
    client, user, web, monkeypatch
) -> None:
    monkeypatch.setitem(config.config, "allow_private_downloads", True)
    urls = [f"http://127.0.0.1:{web.port}/{i}" for i in range(12)]
    post_id = _card(client, user, *urls)
    assert _queue(client, user, post_id)
    assert jobs.work_once()
    assert len(web.requests) == 10
    assert _answer(client, user, post_id)["archiveQueued"]
    assert jobs.work_once()
    assert len(web.requests) == 12
    assert not _answer(client, user, post_id)["archiveQueued"]
    assert _queue(client, user, post_id, retryFailed=False)
    assert jobs.work_once()
    assert len(web.requests) == 12
    assert _queue(client, user, post_id)  # true by default
    assert jobs.work_once() and jobs.work_once()
    assert len(web.requests) == 24
    assert not jobs.work_once()
    assert {row.attempts for row in db.session.query(ArchivedLink)} == {2}


@pytest.mark.parametrize("changed", ["checksum", "deleted"])
def test_stale_job_leaves_changed_or_deleted_card_alone(
    client, user, web, changed
) -> None:
    url = f"http://127.0.0.1:{web.port}/unused"
    post_id = upload(client, user, cards.v3_card(first_mes=f"![unused]({url})"))
    assert _queue(client, user, post_id)
    if changed == "deleted":
        db.session.delete(posts.get_post_by_id(post_id))
        db.session.commit()
    else:
        raw = cards.v3_card(name="Changed", first_mes=f"![unused]({url})")
        ok(replace_file(client, user, post_id, cards.png_card(raw)))
    assert jobs.work_once()
    assert not web.requests
    assert db.session.query(ArchivedLink).count() == 0
    if changed == "checksum":
        assert not db.session.get(Card, post_id).archive_queued


def test_hidden_duplicate_is_unavailable_and_visible_posts_are_filtered(
    client, user, web, monkeypatch
) -> None:
    monkeypatch.setitem(config.config, "visibility", "nsfw-login")
    monkeypatch.setitem(config.config, "allow_private_downloads", True)
    web.routes["/image"] = (200, {}, cards.picture(72))
    url = f"http://127.0.0.1:{web.port}/image"
    source = _card(client, user, url, tags=["nsfw"])
    assert _queue(client, user, source) and jobs.work_once()
    hidden = _answer(client, user, source)["links"][0]["post"]["id"]
    public = _card(client, user, url, f"lithica:post/{hidden}")
    assert _queue(client, user, public) and jobs.work_once()
    guest = _answer(client, None, public)
    assert guest["links"][0]["status"] == "archived"
    assert guest["links"][0]["post"] is None
    assert guest["references"] == [{"id": hidden, "post": None}]
    assert _answer(client, user, public)["references"][0]["post"]["id"] == hidden

    orphan = _card(client, user, url, f"lithica:post/{hidden + 999}")
    posts.get_post_by_id(orphan).user = None
    db.session.commit()
    assert _queue(client, user, orphan) and jobs.work_once()
    failed = _answer(client, user, orphan)["links"][0]
    assert (failed["status"], failed["reason"], failed["post"]) == (
        "failed",
        "unavailable",
        None,
    )
    assert [path for _, path in web.requests] == ["/image", "/image"]

    db.session.delete(posts.get_post_by_id(hidden))
    db.session.commit()
    assert _answer(client, user, public)["links"][0]["status"] == "new"


def test_automatic_rules_and_document_write_triggers(
    client, user, web, monkeypatch
) -> None:
    monkeypatch.setitem(config.config, "allow_private_downloads", True)
    settings = config.config["cards"]
    settings["archive_mode"] = "automatic"
    url = f"http://127.0.0.1:{web.port}/missing"
    no_rule = _card(client, user, url)
    assert not _answer(client, user, no_rule)["archiveQueued"]
    settings["archive_creators"] = ["  SOMEBODY "]
    settings["archive_tags"] = ["ARCHIVE_TAG"]

    raw = cards.v3_card(first_mes=f"![image]({url})")
    upload_id = upload(client, user, raw)
    assert _answer(client, user, upload_id)["archiveQueued"]
    assert jobs.work_once()
    assert _answer(client, user, upload_id)["links"][0]["attempts"] == 1

    next_raw = cards.v3_card(
        name="Replacement", first_mes=f"![image]({url}) ![x]({url}/x)"
    )
    ok(replace_file(client, user, upload_id, cards.png_card(next_raw)))
    assert _answer(client, user, upload_id)["archiveQueued"]
    assert jobs.work_once()
    assert [link["attempts"] for link in _answer(client, user, upload_id)["links"]] == [
        1,
        1,
    ]

    tag_raw = cards.v3_card(
        name="Tagged data", creator="unmatched", first_mes=f"![a]({url})"
    )
    post_id = ok(
        create(client, user, tag_raw, tags=["archive_tag"], externalIds=external(7))
    )["post"]["id"]
    assert _answer(client, user, post_id)["archiveQueued"]
    assert jobs.work_once()
    tag_raw["data"]["first_mes"] = "No links"
    ok(create(client, user, tag_raw, externalIds=external(7), onExisting="update"))
    assert _answer(client, user, post_id)["archiveQueued"]
    assert jobs.work_once()
    assert not _answer(client, user, post_id)["links"]

    ok(
        client.post(
            f"/post/{post_id}/document-version/0/restore",
            user=user,
            body={"version": 1},
        )
    )
    assert _answer(client, user, post_id)["archiveQueued"]
    assert jobs.work_once()
    assert _answer(client, user, post_id)["links"][0]["attempts"] == 1
    assert len(web.requests) == 3


def test_identical_document_file_replace_can_trigger_automatic_archiving(
    client, user, web, monkeypatch
) -> None:
    monkeypatch.setitem(config.config, "allow_private_downloads", True)
    settings = config.config["cards"]
    settings["archive_mode"] = "automatic"
    settings["archive_tags"] = ["archive_tag"]
    url = f"http://127.0.0.1:{web.port}/missing"
    raw = cards.v3_card(first_mes=f"![image]({url})")
    post_id = upload(client, user, raw)
    post = posts.get_post_by_id(post_id)
    posts.update_post_tags(post, ["archive_tag"])
    db.session.commit()
    assert not _answer(client, user, post_id)["archiveQueued"]

    carrier = cards.png_with(cards.compressed_text_chunk(b"chara", cards.encoded(raw)))
    ok(replace_file(client, user, post_id, carrier))
    assert documents.get(post).version == 0
    assert _answer(client, user, post_id)["archiveQueued"]
    assert jobs.work_once()
    assert len(web.requests) == 1
