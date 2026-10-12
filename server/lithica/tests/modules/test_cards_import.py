"""Cards through `lithica-admin import` (PLAN.md 5.0): as through an upload."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from lithica import db, model
from lithica.tests.api.http import ok
from lithica.tests.modules import cards

ADMIN_PATH = Path(__file__).resolve().parents[3] / "lithica-admin"
SAMPLES = Path(__file__).resolve().parents[4] / "scratch" / "sample-cards"


@pytest.fixture(scope="module")
def admin():
    # lithica-admin is a script without the .py suffix
    loader = SourceFileLoader("lithica_admin", str(ADMIN_PATH))
    spec = spec_from_loader("lithica_admin", loader)
    assert spec
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def library(site, user, tag_category_factory):
    db.session.add(tag_category_factory(name="creator"))
    db.session.commit()
    return site(["cards"])


def _import(admin, folder, user, *options):
    arguments = ["import", str(folder), "--user", user.name, "--safety", "safe"]
    return admin.main([*arguments, *options])


def _tags(post):
    return {tag.first_name: tag.category.name for tag in post.tags}


def test_import_of_cards(admin, library, user, tmp_path, capsys):
    folder = tmp_path / "cards"
    folder.mkdir()
    (folder / "1-v2.png").write_bytes(cards.png_card(cards.v2_card(), shade=1))
    (folder / "2-v3.png").write_bytes(
        cards.png_card(cards.v3_card(creator="Other"), b"ccv3", shade=2)
    )
    (folder / "3.charx").write_bytes(cards.charx(icon=cards.picture(shade=3)))
    (folder / "4-plain.png").write_bytes(cards.picture(shade=4))
    (folder / "5-hostile.charx").write_bytes(cards.charx(**{"../evil.txt": b"evil"}))
    (folder / "6-archive.zip").write_bytes(cards.archive({"readme.txt": b"hello"}))

    assert _import(admin, folder, user, "--dry-run") == 0
    output = capsys.readouterr().out
    assert "4 would be created, 0 skipped, 2 refused, 0 failed" in output
    assert db.session.query(model.Post).count() == 0

    assert _import(admin, folder, user, "--tags", "imported") == 0
    output = capsys.readouterr().out
    assert "import: 6 files: 4 created, 0 skipped, 2 refused, 0 failed" in output
    assert (
        "  refused  5-hostile.charx: CHARX file refused: The archive has an entry "
        "whose name is an absolute path or points outside the archive."
    ) in output
    assert "  refused  6-archive.zip: Unhandled file type" in output

    v2, v3, charx, plain = (
        db.session.query(model.Post).order_by(model.Post.post_id).all()
    )
    # every card with its content and the tags an upload would have given it
    assert [row.kind for row in v2.contents] == ["card_v2"]
    assert [row.kind for row in v3.contents] == ["card_v3"]
    assert [row.kind for row in charx.contents] == ["card_v3"]
    assert plain.contents == []
    assert _tags(v2) == {
        "imported": "default",
        "somebody": "creator",
        "lighthouse": "default",
        "slice_of_life": "default",
    }
    assert _tags(v3)["other"] == "creator"
    assert charx.type == "charx" and _tags(charx)["somebody"] == "creator"
    assert _tags(plain) == {"imported": "default"}
    # and they are found as cards
    found = ok(
        library.get(
            "/posts", user=user, query={"query": "card-spec:v3", "fields": "id"}
        )
    )
    assert sorted(post["id"] for post in found["results"]) == [
        v3.post_id,
        charx.post_id,
    ]

    # a second run creates nothing
    assert _import(admin, folder, user) == 0
    assert "0 created, 4 skipped, 2 refused, 0 failed" in capsys.readouterr().out
    assert db.session.query(model.Post).count() == 4


def test_import_of_the_sample_cards(admin, library, user, capsys):
    """
    The owner's sample cards, kept outside the repository (scratch/ is
    git-ignored). Skipped where they are not there, as in CI.
    """
    samples = (
        sorted(path for path in SAMPLES.iterdir() if path.suffix in (".png", ".charx"))
        if SAMPLES.is_dir()
        else []
    )
    if not samples:
        pytest.skip("no sample cards in %s" % SAMPLES)
    assert _import(admin, SAMPLES, user) == 0
    output = capsys.readouterr().out
    assert "%d created, 0 skipped" % len(samples) in output
    assert "0 failed" in output
    imported = db.session.query(model.Post).all()
    # one post per card, each with its card and at least its creator as a tag
    assert len(imported) == len(samples)
    for post in imported:
        assert [row.kind[:5] for row in post.contents] == ["card_"]
        assert "creator" in _tags(post).values()
