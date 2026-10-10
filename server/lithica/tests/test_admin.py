from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

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
    ]:
        assert option in output
