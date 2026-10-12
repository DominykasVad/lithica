"""The cards module: tags, search and API (PLAN.md 4.6)."""

import os
import re

import pytest
import sqlalchemy as sa
import sqlalchemy.event as sa_event

from lithica import config, db, errors, model, registry
from lithica.func import posts, tag_categories
from lithica.modules.cards import api, filename
from lithica.modules.cards import card as card_format
from lithica.tests.api.http import assert_error, assert_fits, ok
from lithica.tests.modules import cards


def _upload(client, user, content, tags=()):
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": list(tags)},
            files={"content": content},
        )
    )


def _tags(post):
    return {tag["names"][0]: tag["category"] for tag in post["tags"]}


def _search(client, user, query):
    found = ok(client.get("/posts", user=user, query={"query": query, "fields": "id"}))
    return sorted(post["id"] for post in found["results"])


@pytest.fixture
def creator_category(tag_category_factory):
    db.session.add(tag_category_factory(name="creator"))
    db.session.flush()


# tags


def test_tags_of_a_card(site, user, creator_category):
    client = site(["cards"])
    card = cards.v2_card(
        creator="Some  Body", tags=["lighthouse", "Slice of Life", " Sea\tStories "]
    )
    created = _upload(client, user, cards.png_card(card), tags=["by_hand"])
    assert _tags(created) == {
        "by_hand": "default",
        # the creator, in the category for creators
        "some_body": "creator",
        # the card's own tags, in the default category: lower case, and
        # whitespace as an underscore
        "lighthouse": "default",
        "slice_of_life": "default",
        "sea_stories": "default",
    }


def test_tags_of_a_charx_file(site, user, creator_category):
    client = site(["cards"])
    created = _upload(client, user, cards.charx())
    assert _tags(created) == {
        "somebody": "creator",
        "lighthouse": "default",
        "slice_of_life": "default",
    }


def test_creator_goes_to_the_default_category_where_there_is_no_other(
    site, user, caplog
):
    # the administrator has not made the `creator` category: the engine's
    # rule for a missing category applies
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    assert _tags(created)["somebody"] == "default"
    assert "No tag category 'creator'" in caplog.text


def test_tag_that_exists_keeps_its_category(site, user, creator_category, tag_factory):
    category = db.session.query(model.TagCategory).filter_by(name="default").one()
    db.session.add(tag_factory(names=["somebody"], category=category))
    db.session.flush()
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    assert _tags(created)["somebody"] == "default"


def test_names_the_site_does_not_take_are_left_out(site, user, creator_category):
    client = site(["cards"])
    config.config["tag_name_regex"] = r"^[a-z_]+$"
    card = cards.v2_card(creator="C++ fan", tags=["fine", "not/fine", "x" * 300, "ok"])
    created = _upload(client, user, cards.png_card(card))
    assert _tags(created) == {"fine": "default", "ok": "default"}


def test_tags_are_named_once(site, user, creator_category):
    client = site(["cards"])
    card = cards.v2_card(
        creator="Ada", tags=["Sea", "sea", " SEA ", "ada", "storm", "", "   "]
    )
    created = _upload(client, user, cards.png_card(card))
    # the creator came first; a tag of the same name is the same tag
    assert _tags(created) == {"ada": "creator", "sea": "default", "storm": "default"}


def test_v1_card_has_no_tags_to_give(site, user, creator_category):
    client = site(["cards"])
    assert _upload(client, user, cards.png_card(cards.V1_CARD))["tags"] == []


@pytest.mark.parametrize(
    "creator,tags",
    [
        (None, None),
        (42, "sea"),
        (["a"], {"a": 1}),
        ("", [None, 3, ["nested"], {"x": 1}]),
    ],
)
def test_creator_and_tags_that_are_not_texts_are_ignored(
    site, user, creator_category, creator, tags
):
    client = site(["cards"])
    card = cards.v2_card(creator=creator, tags=tags)
    created = _upload(client, user, cards.png_card(card))
    assert created["contentKinds"] == ["card_v2"]
    assert created["tags"] == []


def test_card_with_more_tags_than_a_post_gets(site, user, creator_category):
    client = site(["cards"])
    card = cards.v2_card(tags=["tag %d" % number for number in range(150)])
    created = _upload(client, user, cards.png_card(card))
    names = _tags(created)
    # the creator and the first ninety-nine: what the engine takes of one module
    assert len(names) == 100
    assert names["somebody"] == "creator"
    assert "tag_98" in names and "tag_99" not in names


def test_automatic_tags_need_no_privilege_to_create_tags(site, user, creator_category):
    client = site(["cards"])
    config.config["privileges"]["tags:create"] = model.User.RANK_ADMINISTRATOR
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    assert "lighthouse" in _tags(created)


def test_normalising_a_name():
    assert card_format.tag_name("Slice of Life") == "slice_of_life"
    assert card_format.tag_name("  A \t\n B  ") == "a_b"
    assert card_format.tag_name("ÉCOLE Été") == "école_été"
    assert card_format.tag_name("") == "" and card_format.tag_name(" \n ") == ""


def test_module_says_how_tags_work():
    import lithica.modules.cards as module

    assert module.__doc__ is not None
    for word in ["`creator`", "default category", "administrator", "lower case"]:
        assert word in module.__doc__


# search


@pytest.fixture
def library(site, user):
    """Posts of every sort, and their ids by a name."""
    client = site(["cards"])
    plenty = ["Hello.", "Hi.", "Hey.", "Yo."]
    uploads = {
        "v1": cards.png_card(cards.V1_CARD, shade=1),
        "v2": cards.png_card(cards.v2_card(creator="Somebody"), shade=2),
        "v3": cards.png_card(
            cards.v3_card(
                creator="other_person",
                character_book=None,
                first_mes="",
                alternate_greetings=[],
            ),
            b"ccv3",
            shade=3,
        ),
        "charx": cards.charx(
            cards.charx_card(None, creator="somebody else", alternate_greetings=plenty)
        ),
        "plain": cards.picture(shade=9),
    }
    ids = {name: _upload(client, user, data)["id"] for name, data in uploads.items()}

    def found(query):
        hits = _search(client, user, query)
        return sorted(name for name, post_id in ids.items() if post_id in hits)

    return found


def test_search_by_creator(library):
    assert library("card-creator:somebody") == ["v2"]
    # as the card has it, whatever the case, and with wildcards
    assert library("card-creator:SOMEBODY") == ["v2"]
    assert library("card-creator:some*") == ["charx", "v2"]
    assert library("card-creator:*person") == ["v3"]
    assert library("card-creator:other_person") == ["v3"]
    assert library("card-creator:somebody,other_person") == ["v2", "v3"]
    assert library("card-creator:nobody") == []
    # a card without a creator has the empty one; a picture has none at all
    assert library("-card-creator:some*") == ["plain", "v1", "v3"]
    assert library("-card-creator:*") == ["plain"]


def test_search_by_spec(library):
    assert library("card-spec:v1") == ["v1"]
    assert library("card-spec:v2") == ["v2"]
    assert library("card-spec:v3") == ["charx", "v3"]
    assert library("card-spec:V3") == ["charx", "v3"]
    assert library("card-spec:v1,v2") == ["v1", "v2"]
    assert library("-card-spec:v3") == ["plain", "v1", "v2"]
    assert library("-card-spec:v1,v2,v3") == ["plain"]


def test_search_by_format(library):
    assert library("card-format:png") == ["v1", "v2", "v3"]
    assert library("card-format:charx") == ["charx"]
    assert library("-card-format:png") == ["charx", "plain"]
    assert library("card-format:png,charx") == ["charx", "v1", "v2", "v3"]


def test_search_by_lorebook(library):
    assert library("card-lorebook:yes") == ["charx", "v2"]
    assert library("card-lorebook:no") == ["v1", "v3"]
    assert library("card-lorebook:YES") == ["charx", "v2"]
    # not "yes" is everything else, pictures too
    assert library("-card-lorebook:yes") == ["plain", "v1", "v3"]
    assert library("-card-lorebook:no") == ["charx", "plain", "v2"]


def test_search_by_greetings(library):
    # v1: its first message; v2: that and two more; v3: none; charx: 1 + 4
    assert library("card-greetings:1") == ["v1"]
    assert library("card-greetings:3") == ["v2"]
    assert library("card-greetings:0") == ["v3"]
    assert library("card-greetings:5") == ["charx"]
    assert library("card-greetings:2..5") == ["charx", "v2"]
    assert library("card-greetings:..1") == ["v1", "v3"]
    assert library("card-greetings:3..") == ["charx", "v2"]
    assert library("card-greetings:0,5") == ["charx", "v3"]
    assert library("-card-greetings:1..") == ["plain", "v3"]
    assert library("card-greetings:7") == []


def test_tokens_work_together_and_with_the_engine_s(library):
    assert library("card-spec:v3 card-format:png") == ["v3"]
    assert library("card-lorebook:yes -card-greetings:..3") == ["charx"]
    assert library("type:charx card-creator:some*") == ["charx"]
    assert library("type:image -card-spec:v1,v2,v3") == ["plain"]


@pytest.mark.parametrize(
    "query",
    [
        "card-spec:v4",
        "card-spec:card_v2",
        "card-format:jpeg",
        "card-lorebook:maybe",
        "card-lorebook:yes,no",
        "card-lorebook:1..2",
        "card-greetings:many",
    ],
)
def test_value_a_token_does_not_know(site, user, query):
    client = site(["cards"])
    assert_error(
        client.get("/posts", user=user, query={"query": query}), errors.SearchError
    )


def test_tokens_are_unknown_without_the_module(site, user):
    client = site([])
    for token in [
        "card-creator:x",
        "card-spec:v2",
        "card-format:png",
        "card-lorebook:yes",
        "card-greetings:1",
    ]:
        assert_error(
            client.get("/posts", user=user, query={"query": token}), errors.SearchError
        )


def test_token_names_keep_clear_of_the_engine():
    registry.load(["cards"])
    assert sorted(registry.post_search_filters()) == [
        "card-creator",
        "card-format",
        "card-greetings",
        "card-lorebook",
        "card-spec",
    ]


# the post field


def test_post_field(site, user):
    client = site(["cards"])
    card = _upload(client, user, cards.png_card(cards.v2_card(), shade=1))
    file = _upload(client, user, cards.charx())
    plain = _upload(client, user, cards.picture(shade=2))
    # not there unless it is asked for
    assert "card" not in card
    assert "card" not in ok(client.get("/post/%d" % card["id"], user=user))
    assert "card" not in ok(client.get("/posts", user=user))["results"][0]

    listed = ok(client.get("/posts", user=user, query={"fields": "id,card"}))
    assert {post["id"]: post["card"] for post in listed["results"]} == {
        card["id"]: {
            "name": "Ada",
            "creator": "somebody",
            "spec": "v2",
            "format": "png",
            "greetingCount": 3,
            "lorebookEntryCount": 2,
        },
        file["id"]: {
            "name": "Ada",
            "creator": "somebody",
            "spec": "v3",
            "format": "charx",
            "greetingCount": 3,
            "lorebookEntryCount": 2,
        },
        plain["id"]: None,
    }
    one = ok(client.get("/post/%d" % card["id"], user=user, query={"fields": "card"}))
    assert list(one) == ["card"] and one["card"]["spec"] == "v2"


def test_post_field_is_small_whatever_the_card(site, user):
    client = site(["cards"])
    card = cards.v2_card(name="N" * 5000, creator="C" * 5000, description="D" * 200000)
    created = _upload(client, user, cards.png_card(card))
    field = ok(
        client.get("/post/%d" % created["id"], user=user, query={"fields": "card"})
    )["card"]
    assert field["name"] == "N" * 200 and field["creator"] == "C" * 200


def test_post_field_does_not_read_the_card(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    db.session.commit()
    db.session.expire_all()
    post = posts.get_post_by_id(created["id"])
    field = api.card_field(post, user)
    assert field is not None and field["name"] == "Ada"
    # the post's rows of extracted content, and with them the card, were
    # not loaded for it
    assert "contents" in sa.inspect(post).unloaded


def test_post_field_of_a_card_stored_before_there_were_summaries(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    row = db.session.query(model.PostContent).one()
    row.payload = {key: value for key, value in row.payload.items() if key != "summary"}
    row.schema_version = 1
    db.session.flush()
    field = ok(
        client.get("/post/%d" % created["id"], user=user, query={"fields": "card"})
    )["card"]
    assert field == {
        "name": None,
        "creator": None,
        "spec": "v2",
        "format": "png",
        "greetingCount": None,
        "lorebookEntryCount": None,
    }


def test_post_field_is_unknown_without_the_module(site, user):
    client = site([])
    _upload(client, user, cards.picture())
    assert_error(
        client.get("/posts", user=user, query={"fields": "card"}),
        errors.ValidationError,
    )


# the card, read for a viewer


def _card(client, user, post_id):
    return ok(client.get("/modules/cards/post/%d" % post_id, user=user))


def test_card_of_a_v2_picture(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    card = _card(client, user, created["id"])
    assert_fits(api.Card, card)
    assert card == {
        "postId": created["id"],
        "spec": "v2",
        "format": "png",
        "name": "Ada",
        "description": "A lighthouse keeper who talks to the sea.",
        "personality": "patient, dry",
        "scenario": "A storm is coming in.",
        "firstMessage": "You made it up the stairs. Tea?",
        "alternateGreetings": ["The door was open.", "Back again?"],
        "exampleMessages": "<START>\n{{user}}: hi\n{{char}}: Mind the lamp.",
        "creatorNotes": "Works best with a long context.",
        "systemPrompt": "",
        "postHistoryInstructions": "",
        "tags": ["lighthouse", "Slice of Life"],
        "creator": "somebody",
        "characterVersion": "1.2",
        "lorebook": {
            "name": "The coast",
            "description": "",
            "scanDepth": None,
            "tokenBudget": None,
            "recursiveScanning": None,
            "extensions": {},
            "entries": [
                {
                    "keys": ["lamp", "light"],
                    "secondaryKeys": [],
                    "content": "The lamp was lit in 1871 and has never gone out.",
                    "enabled": True,
                    "order": 10,
                    "name": "",
                    "comment": "",
                    "constant": None,
                    "selective": None,
                    "caseSensitive": None,
                    "useRegex": None,
                    "position": None,
                    "priority": None,
                    "id": None,
                    "extensions": {},
                },
                {
                    "keys": ["storm"],
                    "secondaryKeys": [],
                    "content": "Storms come from the north-west.",
                    "enabled": False,
                    "order": 20,
                    "name": "",
                    "comment": "",
                    "constant": False,
                    "selective": None,
                    "caseSensitive": None,
                    "useRegex": None,
                    "position": None,
                    "priority": None,
                    "id": None,
                    "extensions": {},
                },
            ],
        },
    }
    # with a trailing slash too, as every JSON route
    assert ok(client.get("/modules/cards/post/%d/" % created["id"], user=user)) == card


def test_every_version_and_format_has_the_same_shape(site, user):
    client = site(["cards"])
    uploads = {
        ("v1", "png"): cards.png_card(cards.V1_CARD, shade=1),
        ("v2", "png"): cards.png_card(cards.v2_card(), shade=2),
        ("v3", "png"): cards.png_card(cards.v3_card(), b"ccv3", shade=3),
        ("v3", "charx"): cards.charx(),
    }
    shown = {}
    for (spec, file_format), data in uploads.items():
        card = _card(client, user, _upload(client, user, data)["id"])
        assert_fits(api.Card, card)
        assert (card["spec"], card["format"]) == (spec, file_format)
        shown[spec, file_format] = card
    keys = {tuple(card) for card in shown.values()}
    assert len(keys) == 1
    # the fields every version has are read from wherever it keeps them
    for card in shown.values():
        assert card["name"] == "Ada"
        assert card["firstMessage"] == "You made it up the stairs. Tea?"
        assert card["exampleMessages"].startswith("<START>")
    # what V1 does not have is empty, not absent
    v1 = shown["v1", "png"]
    assert v1["alternateGreetings"] == [] and v1["tags"] == []
    assert v1["creator"] == "" and v1["creatorNotes"] == ""
    assert v1["lorebook"] is None
    # V2 and V3, picture and archive, read alike
    for name in ["alternateGreetings", "tags", "creator", "lorebook", "creatorNotes"]:
        values = [shown[key][name] for key in shown if key != ("v1", "png")]
        assert values[0] == values[1] == values[2], name


def test_every_field_of_a_lorebook_entry(site, user):
    client = site(["cards"])
    book = {
        "name": "Book",
        "description": "About the coast.",
        "scan_depth": 4,
        "token_budget": 512,
        "recursive_scanning": True,
        "extensions": {"app": {"x": 1}},
        "entries": [
            {
                "keys": ["a", "b"],
                "secondary_keys": ["c"],
                "content": "Content.",
                "extensions": {"app": [1, 2]},
                "enabled": True,
                "insertion_order": 7,
                "case_sensitive": True,
                "use_regex": False,
                "constant": True,
                "name": "Entry",
                "priority": 3,
                "id": "entry-1",
                "comment": "A comment.",
                "selective": True,
                "position": "after_char",
            }
        ],
    }
    card = cards.v3_card(character_book=book)
    created = _upload(client, user, cards.png_card(card, b"ccv3"))
    lorebook = _card(client, user, created["id"])["lorebook"]
    assert lorebook == {
        "name": "Book",
        "description": "About the coast.",
        "scanDepth": 4,
        "tokenBudget": 512,
        "recursiveScanning": True,
        "extensions": {"app": {"x": 1}},
        "entries": [
            {
                "keys": ["a", "b"],
                "secondaryKeys": ["c"],
                "content": "Content.",
                "enabled": True,
                "order": 7,
                "name": "Entry",
                "comment": "A comment.",
                "constant": True,
                "selective": True,
                "caseSensitive": True,
                "useRegex": False,
                "position": "after_char",
                "priority": 3,
                "id": "entry-1",
                "extensions": {"app": [1, 2]},
            }
        ],
    }


def test_card_that_got_its_types_wrong_is_still_shown(site, user):
    client = site(["cards"])
    card = {
        "spec": "chara_card_v2",
        "data": {
            "name": "Odd",
            "description": 42,
            "personality": None,
            "first_mes": ["a", "list"],
            "alternate_greetings": "not a list",
            "tags": ["fine", 3, None, {"x": 1}],
            "creator": {"name": "x"},
            "character_book": {
                "name": 5,
                "scan_depth": "deep",
                "recursive_scanning": "yes",
                "extensions": "none",
                "entries": [
                    "not an entry",
                    {
                        "keys": "lamp",
                        "content": None,
                        "enabled": "true",
                        "insertion_order": True,
                        "id": [1],
                        "extensions": 3,
                    },
                ],
            },
        },
    }
    created = _upload(client, user, cards.png_card(card))
    shown = _card(client, user, created["id"])
    assert_fits(api.Card, shown)
    assert shown["name"] == "Odd"
    assert shown["description"] == "" and shown["personality"] == ""
    assert shown["firstMessage"] == "" and shown["alternateGreetings"] == []
    assert shown["tags"] == ["fine"] and shown["creator"] == ""
    assert shown["lorebook"]["name"] == ""
    assert shown["lorebook"]["scanDepth"] is None
    assert shown["lorebook"]["recursiveScanning"] is None
    assert shown["lorebook"]["extensions"] == {}
    (entry,) = shown["lorebook"]["entries"]
    assert entry["keys"] == [] and entry["content"] == ""
    assert entry["enabled"] is None and entry["order"] is None
    assert entry["id"] is None and entry["extensions"] == {}


def test_raw_card_stays_available(site, user):
    client = site(["cards"])
    card = cards.v2_card(extensions={"some_app": {"depth": 4}})
    created = _upload(client, user, cards.png_card(card))
    assert "extensions" not in _card(client, user, created["id"])
    raw = ok(client.get("/post/%d/content" % created["id"], user=user))["results"][0]
    assert raw["content"]["card"] == card
    # nothing of a card is private by default
    assert all(
        kind.private_fields == frozenset() for kind in registry.content_kinds().values()
    )


def test_card_of_a_post_without_one(site, user):
    client = site(["cards"])
    plain = _upload(client, user, cards.picture())
    refused = assert_error(
        client.get("/modules/cards/post/%d" % plain["id"], user=user),
        api.CardNotFoundError,
    )
    assert refused["description"] == "Post %d has no character card." % plain["id"]
    assert_error(
        client.get("/modules/cards/post/%d/download" % plain["id"], user=user),
        api.CardNotFoundError,
    )


@pytest.mark.parametrize("suffix", ["", "/download"])
def test_card_of_a_post_that_is_not_there(site, user, suffix):
    client = site(["cards"])
    assert_error(
        client.get("/modules/cards/post/999" + suffix, user=user),
        posts.PostNotFoundError,
    )
    assert_error(
        client.get("/modules/cards/post/nine" + suffix, user=user),
        posts.InvalidPostIdError,
    )


@pytest.mark.parametrize("suffix", ["", "/download"])
def test_card_routes_need_the_privilege_to_view_posts(site, user, user_factory, suffix):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    path = "/modules/cards/post/%d%s" % (created["id"], suffix)
    assert_error(client.get(path, user=anonymous), errors.AuthError)
    config.config["privileges"]["posts:view"] = model.User.RANK_ANONYMOUS
    assert client.get(path, user=anonymous).status_code == 200


@pytest.mark.parametrize("suffix", ["", "/download"])
def test_card_routes_are_not_there_without_the_module(site, user, suffix):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    client = site([])
    path = "/modules/cards/post/%d%s" % (created["id"], suffix)
    assert client.get(path, user=user).status_code == 404


# the download


def _download(client, user, post_id, **kwargs):
    return client.get("/modules/cards/post/%d/download" % post_id, user=user, **kwargs)


def test_download_of_a_picture(site, user):
    client = site(["cards"])
    uploaded = cards.png_card(cards.v2_card())
    created = _upload(client, user, uploaded)
    response = _download(client, user, created["id"])
    assert response.status_code == 200
    # the stored file, unchanged
    assert response.content == uploaded
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == 'attachment; filename="Ada.png"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-length"] == str(len(uploaded))


def test_download_of_a_charx_file(site, user):
    client = site(["cards"])
    uploaded = cards.charx(icon=cards.picture())
    created = _upload(client, user, uploaded)
    response = _download(client, user, created["id"])
    assert response.content == uploaded
    assert response.headers["content-type"] == "application/x-charx"
    assert response.headers["content-disposition"] == 'attachment; filename="Ada.charx"'


def test_download_does_not_ask_for_json(site, user):
    # a browser following a link does not say it accepts JSON
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    response = _download(client, user, created["id"], headers={"Accept": "*/*"})
    assert response.status_code == 200
    # the card itself is JSON and says so
    refused = client.get(
        "/modules/cards/post/%d" % created["id"], user=user, headers={"Accept": "*/*"}
    )
    assert refused.status_code == 406
    # and the errors of the download are the API's errors
    missing = _download(client, user, 999, headers={"Accept": "*/*"})
    assert missing.status_code == 404
    assert missing.json()["name"] == "PostNotFoundError"


def test_download_does_not_read_the_card(site, user, monkeypatch):
    client = site(["cards"])
    uploaded = cards.png_card(cards.v2_card(description="D" * 100000))
    created = _upload(client, user, uploaded)
    db.session.commit()
    db.session.expire_all()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the card was read for a download")

    # neither the card's row nor the view of the card is made for it
    monkeypatch.setattr(api, "_card_row", forbidden)
    monkeypatch.setattr(api.view, "normalised", forbidden)
    statements = []

    def record(_connection, _cursor, statement, *_rest):
        statements.append(" ".join(statement.split()))

    sa_event.listen(sa.engine.Engine, "before_cursor_execute", record)
    try:
        response = _download(client, user, created["id"])
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", record)
    assert response.content == uploaded
    assert response.headers["content-disposition"] == 'attachment; filename="Ada.png"'
    # The database was asked for values inside the payload, and never for
    # the payload itself.
    asked = [statement for statement in statements if "post_content" in statement]
    assert asked
    for statement in asked:
        selected = statement[: statement.index(" FROM ")]
        # every mention of the column goes on into the payload (`#>>` is how
        # PostgreSQL writes "the value at this path")
        assert not re.search(r"post_content\.payload(?! #>| ->)", selected), selected


def test_download_of_a_card_stored_before_there_were_summaries(site, user):
    client = site(["cards"])
    ids = {}
    for name, data in [
        ("Old Two", cards.png_card(cards.v2_card(name="Old Two"), shade=1)),
        ("Old One", cards.png_card({**cards.V1_CARD, "name": "Old One"}, shade=2)),
    ]:
        ids[name] = _upload(client, user, data)["id"]
    for row in db.session.query(model.PostContent).all():
        row.payload = {k: v for k, v in row.payload.items() if k != "summary"}
        row.schema_version = 1
    db.session.flush()
    # the name is found where the version of the card keeps it
    for name, post_id in ids.items():
        header = _download(client, user, post_id).headers["content-disposition"]
        assert header == 'attachment; filename="%s.png"' % name


def test_download_named_after_a_character_with_another_alphabet(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card(name="アダ Zoë")))
    header = _download(client, user, created["id"]).headers["content-disposition"]
    assert header == (
        'attachment; filename="__ Zo_.png"; '
        "filename*=UTF-8''%E3%82%A2%E3%83%80%20Zo%C3%AB.png"
    )


def test_download_of_a_card_whose_name_cannot_be_a_file_name(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card(name="???")))
    header = _download(client, user, created["id"]).headers["content-disposition"]
    assert header == 'attachment; filename="card-%d.png"' % created["id"]


def test_download_whose_file_is_gone(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    post = posts.get_post_by_id(created["id"])
    os.remove(
        os.path.join(config.config["data_dir"], posts.get_post_content_path(post))
    )
    assert_error(_download(client, user, created["id"]), api.CardNotFoundError)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Ada", "Ada"),
        ("Ada Lovelace", "Ada Lovelace"),
        ("  Ada \t\n Lovelace  ", "Ada Lovelace"),
        # no path
        ("../../etc/passwd", "_.._etc_passwd"),
        ("/etc/passwd", "_etc_passwd"),
        ("..\\..\\windows\\system32", "_.._windows_system32"),
        ("C:\\Users\\x", "C__Users_x"),
        # nothing a file system refuses
        ('a<b>c:d"e|f?g*h', "a_b_c_d_e_f_g_h"),
        (".hidden", "hidden"),
        ("trailing. . .", "trailing"),
        # no control characters, and nothing that breaks out of a header
        ("A\x00d\x07a", "Ada"),
        ("x\r\nSet-Cookie: a=b", "x Set-Cookie_ a=b"),
        ("evil\u202egnp.exe", "evilgnp.exe"),
        ("zero\u200bwidth", "zerowidth"),
        # names Windows keeps for devices
        ("CON", "_CON"),
        ("con", "_con"),
        ("nul.txt", "_nul.txt"),
        ("COM1", "_COM1"),
        ("LPT9.tar.gz", "_LPT9.tar.gz"),
        ("CONSOLE", "CONSOLE"),
        ("COM10", "COM10"),
        # other alphabets are names too
        ("アダ", "アダ"),
        ("Zoë", "Zoë"),
        ("e\u0301", "é"),
        # nothing usable
        ("", ""),
        ("   ", ""),
        ("...", ""),
        ("???", ""),
        ("/\\/", ""),
        ("\x00\x01", ""),
    ],
)
def test_sanitising_a_name(name, expected):
    assert filename.sanitised(name) == expected
    for character in filename.sanitised(name):
        assert character not in '/\\<>:"|?*' and character.isprintable()


def test_long_name_is_cut():
    assert filename.sanitised("a" * 300) == "a" * 100
    assert filename.sanitised("a" * 99 + ". b") == "a" * 99


@pytest.mark.parametrize(
    "name,header",
    [
        ("Ada", 'attachment; filename="Ada.png"'),
        ("", 'attachment; filename="card-7.png"'),
        ("CON", 'attachment; filename="_CON.png"'),
        ('"quoted"', 'attachment; filename="_quoted_.png"'),
        (
            "Zoë",
            "attachment; filename=\"Zo_.png\"; filename*=UTF-8''Zo%C3%AB.png",
        ),
        (
            "アダ",
            'attachment; filename="card-7.png"; '
            "filename*=UTF-8''%E3%82%A2%E3%83%80.png",
        ),
        (
            "50% off; a'b",
            'attachment; filename="50% off; a\'b.png"',
        ),
    ],
)
def test_content_disposition(name, header):
    assert filename.content_disposition(name, 7, "png") == header
    # one line, whatever the name
    assert "\r" not in header and "\n" not in header


def test_default_category_is_asked_of_the_site(site, user, creator_category):
    client = site(["cards"])
    category = tag_categories.get_default_category()
    category.name = "general"
    db.session.flush()
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    assert _tags(created) == {
        "somebody": "creator",
        "lighthouse": "general",
        "slice_of_life": "general",
    }
