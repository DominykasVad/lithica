from datetime import datetime
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest.mock import patch

import pytest

from lithica import db, model
from lithica.func import files, posts, util

ADMIN_PATH = Path(__file__).resolve().parent.parent.parent / "lithica-admin"


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
def old_posts(tmpdir, config_injector, post_factory, read_asset):
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "secret": "test",
            "allow_broken_uploads": False,
        }
    )
    post_ids = []
    for asset in ["png.png", "jpeg.jpg"]:
        post = post_factory(type=model.Post.TYPE_IMAGE, checksum=asset)
        db.session.add(post)
        db.session.flush()
        files.save(posts.get_post_content_path(post), read_asset(asset))
        post_ids.append(post.post_id)
    db.session.commit()
    return post_ids


def test_backfill_signatures(admin, old_posts, capsys):
    assert admin.main(["backfill", "signatures"]) == 0
    assert db.session.query(model.PostSignature).count() == 2
    assert posts.count_posts_without_md5_checksum() == 2
    output = capsys.readouterr().out
    assert "signatures: 2 posts to process" in output
    assert "signatures: 2 done, 0 failed" in output


def test_backfill_md5(admin, old_posts, read_asset, capsys):
    assert admin.main(["backfill", "md5"]) == 0
    assert db.session.query(model.PostSignature).count() == 0
    post = posts.get_post_by_id(old_posts[0])
    assert post.checksum_md5 == util.get_md5(read_asset("png.png"))
    assert "md5: 2 done, 0 failed" in capsys.readouterr().out


def test_backfill_all(admin, old_posts, capsys):
    assert admin.main(["backfill", "all"]) == 0
    assert posts.count_posts_without_signature() == 0
    assert posts.count_posts_without_md5_checksum() == 0
    capsys.readouterr()
    # a second run finds nothing to do
    assert admin.main(["backfill", "all"]) == 0
    output = capsys.readouterr().out
    assert "signatures: 0 posts to process" in output
    assert "md5: 0 posts to process" in output
    assert "done" not in output


def test_backfill_reports_failures(admin, old_posts, post_factory, capsys):
    db.session.add(post_factory(type=model.Post.TYPE_IMAGE, checksum="lost"))
    db.session.commit()
    assert admin.main(["backfill", "md5"]) == 1
    captured = capsys.readouterr()
    assert "md5: 2 done, 1 failed" in captured.out
    assert "missing or cannot be read" in captured.err


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["backfill"],
        ["backfill", "everything"],
        ["--check-all-audio", "backfill", "md5"],
        ["no-such-command"],
    ],
)
def test_invalid_arguments(admin, args):
    with pytest.raises(SystemExit) as ex:
        admin.main(args)
    assert ex.value.code == 2


def test_old_options_still_parse(admin, capsys):
    with pytest.raises(SystemExit) as ex:
        admin.main(["--help"])
    assert ex.value.code == 0
    output = capsys.readouterr().out
    for option in [
        "--change-password",
        "--check-all-audio",
        "--reset-filenames",
        "--regenerate-thumbnails",
        "backfill",
        "reextract",
    ]:
        assert option in output


PROBE_MODULE = """
    from lithica import registry

    # what the tests change to make the extractor behave differently
    FAIL_ON_SIZES = set()
    GENERATION = 1
    calls = []

    def extract(mime_type, handle):
        size = len(handle.read())
        calls.append(size)
        if size in FAIL_ON_SIZES:
            raise ValueError("cannot read this one")
        yield registry.ExtractedContent(
            "probe_size", {"size": size, "generation": GENERATION}
        )
        yield registry.ExtractedContent("probe_type", {"mimeType": mime_type})

    def auto_tag(contents):
        calls.append("auto_tag")
        return {"meta": ["probed"]}

    module = registry.Module(
        name="probe",
        content_kinds=[
            registry.ContentKind("probe_size", schema_version=2),
            registry.ContentKind("probe_type"),
            registry.ContentKind("probe_never_found"),
        ],
        extractors=[
            registry.Extractor(frozenset({"image/png", "image/jpeg"}), extract)
        ],
        auto_tag=auto_tag,
    )
"""


@pytest.fixture
def probe(module_package, tmpdir, config_injector):
    """A site whose configuration switches on a module that extracts content."""
    module_package("probe", PROBE_MODULE)
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "secret": "test",
            "allow_broken_uploads": False,
            "modules": ["probe"],
        }
    )
    import some_modules.probe  # pyright: ignore[reportMissingImports]  (written by the fixture)

    return some_modules.probe


@pytest.fixture
def stored_post(post_factory, read_asset):
    def store(asset=None, mime_type="image/png", rows=()):
        post = post_factory(checksum=model_checksum())
        post.mime_type = mime_type
        post.contents = [
            model.PostContent(
                kind=kind,
                schema_version=1,
                payload=payload,
                extracted_at=datetime(1999, 1, 1),
            )
            for kind, payload in rows
        ]
        db.session.add(post)
        db.session.flush()
        if asset:
            files.save(posts.get_post_content_path(post), read_asset(asset))
        db.session.commit()
        return post.post_id

    counter = iter(range(1000))

    def model_checksum():
        return "checksum%d" % next(counter)

    return store


def _rows(post_id):
    db.session.expire_all()
    return [(row.kind, row.payload) for row in posts.get_post_by_id(post_id).contents]


def test_reextract_fills_in_existing_posts(
    admin, probe, stored_post, read_asset, capsys
):
    png = stored_post("png.png")
    jpeg = stored_post("jpeg.jpg", "image/jpeg")
    # no extractor reads this type: not looked at
    gif = stored_post("gif.gif", "image/gif")

    assert admin.main(["reextract"]) == 0

    output = capsys.readouterr().out
    assert "reextract: 2 posts to process" in output
    assert "probe_never_found, probe_size, probe_type" in output
    assert "reextract: 2 done, 0 failed" in output
    assert _rows(png) == [
        ("probe_size", {"size": len(read_asset("png.png")), "generation": 1}),
        ("probe_type", {"mimeType": "image/png"}),
    ]
    assert _rows(jpeg) == [
        ("probe_size", {"size": len(read_asset("jpeg.jpg")), "generation": 1}),
        ("probe_type", {"mimeType": "image/jpeg"}),
    ]
    assert _rows(gif) == []
    row = posts.get_post_by_id(png).contents[0]
    assert row.schema_version == 2
    assert row.extracted_at > datetime(2020, 1, 1)


def test_reextract_replaces_what_was_extracted_before(
    admin, probe, stored_post, read_asset, capsys
):
    png = stored_post(
        "png.png",
        rows=[
            ("probe_size", {"size": -1}),
            ("probe_size", {"size": -2}),
            ("probe_never_found", {"stale": True}),
            ("other_module_v1", {"keep": "me"}),
        ],
    )
    # its type is read by no extractor, but it has rows of the module
    gif = stored_post(
        "gif.gif", "image/gif", rows=[("probe_type", {}), ("other_module_v1", {})]
    )

    assert admin.main(["reextract"]) == 0

    assert "reextract: 2 posts to process" in capsys.readouterr().out
    assert _rows(png) == [
        # the module that owns this kind is not loaded: its row is kept
        ("other_module_v1", {"keep": "me"}),
        ("probe_size", {"size": len(read_asset("png.png")), "generation": 1}),
        ("probe_type", {"mimeType": "image/png"}),
    ]
    assert _rows(gif) == [("other_module_v1", {})]


def test_reextract_is_safe_to_repeat(admin, probe, stored_post, capsys):
    png = stored_post("png.png")
    assert admin.main(["reextract"]) == 0
    first = _rows(png)
    probe.GENERATION = 2
    assert admin.main(["reextract"]) == 0
    assert admin.main(["reextract"]) == 0
    assert _rows(png) == [
        (kind, {**payload, "generation": 2} if kind == "probe_size" else payload)
        for kind, payload in first
    ]
    assert db.session.query(model.PostContent).count() == 2


def test_reextract_of_one_kind(admin, probe, stored_post, read_asset, capsys):
    png = stored_post(
        "png.png",
        rows=[
            ("probe_size", {"size": -1}),
            ("probe_type", {"old": True}),
            ("other_module_v1", {}),
        ],
    )
    # has nothing of that kind and no extractor for its type: not looked at
    stored_post("gif.gif", "image/gif", rows=[("probe_type", {})])

    assert admin.main(["reextract", "--kind", "probe_size"]) == 0

    output = capsys.readouterr().out
    assert "reextract: 1 posts to process (kind probe_size)" in output
    assert _rows(png) == [
        ("probe_type", {"old": True}),
        ("other_module_v1", {}),
        ("probe_size", {"size": len(read_asset("png.png")), "generation": 1}),
    ]


def test_reextract_of_an_unknown_kind(admin, probe, stored_post, capsys):
    png = stored_post("png.png", rows=[("other_module_v1", {})])
    assert admin.main(["reextract", "--kind", "other_module_v1"]) == 1
    captured = capsys.readouterr()
    assert "no loaded module has the content kind 'other_module_v1'" in captured.err
    assert "probe_never_found, probe_size, probe_type" in captured.err
    assert _rows(png) == [("other_module_v1", {})]
    assert probe.calls == []


def test_reextract_without_modules(admin, old_posts, capsys):
    assert admin.main(["reextract"]) == 0
    assert "no loaded module extracts content" in capsys.readouterr().out
    assert admin.main(["reextract", "--kind", "anything"]) == 0


def test_reextract_keeps_old_content_where_the_extractor_fails(
    admin, probe, stored_post, read_asset, capsys
):
    png = stored_post(
        "png.png", rows=[("probe_size", {"size": -1}), ("probe_type", {"old": True})]
    )
    jpeg = stored_post("jpeg.jpg", "image/jpeg", rows=[("probe_size", {"size": -1})])
    probe.FAIL_ON_SIZES = {len(read_asset("png.png"))}

    assert admin.main(["reextract"]) == 1

    captured = capsys.readouterr()
    assert "reextract: 1 done, 1 failed" in captured.out
    assert "What had been extracted from them before was kept" in captured.err
    assert _rows(png) == [("probe_size", {"size": -1}), ("probe_type", {"old": True})]
    assert _rows(jpeg)[0] == (
        "probe_size",
        {"size": len(read_asset("jpeg.jpg")), "generation": 1},
    )


def test_reextract_reports_posts_without_a_file(admin, probe, stored_post, capsys):
    lost = stored_post(None, rows=[("probe_size", {"size": -1})])
    found = stored_post("png.png")
    assert admin.main(["reextract"]) == 1
    assert "reextract: 1 done, 1 failed" in capsys.readouterr().out
    assert _rows(lost) == [("probe_size", {"size": -1})]
    assert len(_rows(found)) == 2


def test_reextract_works_in_batches(admin, probe, stored_post, capsys):
    post_ids = [
        stored_post(asset, mime_type)
        for asset, mime_type in [
            ("png.png", "image/png"),
            ("jpeg.jpg", "image/jpeg"),
            ("jpeg-similar.jpg", "image/jpeg"),
        ]
    ]
    with patch.object(posts, "BACKFILL_BATCH_SIZE", 2):
        assert admin.main(["reextract"]) == 0
    assert "reextract: 3 done, 0 failed" in capsys.readouterr().out
    assert len(probe.calls) == 3
    assert all(len(_rows(post_id)) == 2 for post_id in post_ids)


def test_reextract_changes_nothing_but_the_extracted_content(
    admin, probe, stored_post, tag_factory
):
    png = stored_post("png.png")
    post = posts.get_post_by_id(png)
    post.tags = [tag_factory(names=["by_hand"])]
    db.session.commit()
    before = (post.version, post.last_edit_time, post.checksum)

    assert admin.main(["reextract"]) == 0

    db.session.expire_all()
    post = posts.get_post_by_id(png)
    assert (post.version, post.last_edit_time, post.checksum) == before
    assert [tag.first_name for tag in post.tags] == ["by_hand"]
    assert "auto_tag" not in probe.calls
    assert db.session.query(model.Snapshot).count() == 0
