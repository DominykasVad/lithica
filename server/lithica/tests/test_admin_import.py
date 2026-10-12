"""`lithica-admin import`: a post per file of a folder (PLAN.md 5.0)."""

import os
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from lithica import config, db, model, registry
from lithica.func import post_import, posts

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
def site(config_injector, tmpdir, tag_category_factory, user_factory):
    config_injector(
        {
            "modules": [],
            "data_dir": str(tmpdir.mkdir("data")),
            "data_url": "http://example.com/data/",
            "secret": "test",
            "allow_broken_uploads": False,
            "delete_source_files": True,
            "thumbnails": {
                "post_width": 300,
                "post_height": 300,
                "avatar_width": 30,
                "avatar_height": 30,
            },
            "convert": {"gif": {"to_mp4": False, "to_webm": False}},
            "tag_name_regex": r"^\S+$",
            "webhooks": [],
            "privileges": {},
        }
    )
    db.session.add_all(
        [
            tag_category_factory(name="default", default=True),
            user_factory(name="importer", rank=model.User.RANK_REGULAR),
        ]
    )
    db.session.commit()


@pytest.fixture
def collection(tmp_path, read_asset):
    """A folder as somebody's collection is: pictures, and what is not one."""
    folder = tmp_path / "collection"
    (folder / "sub" / "deeper").mkdir(parents=True)
    (folder / ".hidden").mkdir()
    files = {
        "b.png": read_asset("png.png"),
        "a-copy-of-b.png": read_asset("png.png"),
        "sub/c.jpg": read_asset("jpeg.jpg"),
        "sub/deeper/notes.txt": b"not a picture",
        "sub/empty.png": b"",
        ".DS_Store": b"what a file manager leaves",
        ".hidden/d.gif": read_asset("gif.gif"),
    }
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def _run(admin, folder, *options):
    arguments = ["import", str(folder), "--user", "importer", "--safety", "sketchy"]
    return admin.main([*arguments, *options])


def _posts():
    return db.session.query(model.Post).order_by(model.Post.post_id).all()


def _stored_files():
    found = []
    for _folder, _folders, names in os.walk(config.config["data_dir"]):
        found += names
    return found


def test_files_are_found_in_order_without_the_hidden_ones(collection):
    assert post_import.find_files(str(collection)) == [
        "a-copy-of-b.png",
        "b.png",
        os.path.join("sub", "c.jpg"),
        os.path.join("sub", "deeper", "notes.txt"),
        os.path.join("sub", "empty.png"),
    ]


def test_import(admin, site, collection, read_asset, capsys):
    assert _run(admin, collection, "--tags", "imported, from_disk,,") == 0
    created = _posts()
    # a post per file that is a picture and is not one already, in the order
    # of the names
    assert [post.checksum for post in created] == [
        posts.util.get_sha1(read_asset("png.png")),
        posts.util.get_sha1(read_asset("jpeg.jpg")),
    ]
    for post in created:
        assert post.user.name == "importer"
        assert post.safety == model.Post.SAFETY_SKETCHY
        assert sorted(tag.first_name for tag in post.tags) == ["from_disk", "imported"]
        assert post.type == model.Post.TYPE_IMAGE
        assert post.canvas_width and post.signature is not None
    # stored and with a thumbnail, as an upload is
    assert len(_stored_files()) == 4
    # and in the history, as the user's doing
    snapshots = db.session.query(model.Snapshot).all()
    assert len([s for s in snapshots if s.resource_type == "post"]) == 2
    assert len([s for s in snapshots if s.resource_type == "tag"]) == 2
    assert {snapshot.user.name for snapshot in snapshots} == {"importer"}
    # the folder is as it was
    assert (collection / "b.png").read_bytes() == read_asset("png.png")
    assert len(post_import.find_files(str(collection))) == 5

    output = capsys.readouterr().out
    assert "import: 5 files: 2 created, 1 skipped, 2 refused, 0 failed" in output
    assert "import: problems:" in output
    notes = os.path.join("sub", "deeper", "notes.txt")
    assert (
        "  refused  %s: Unhandled file type: 'application/octet-stream'" % notes
        in output
    )
    assert (
        "  refused  %s: Post content missing." % os.path.join("sub", "empty.png")
        in output
    )
    # a duplicate is not a problem
    assert "b.png" not in output.split("import: problems:")[1]


def test_second_run_creates_nothing(admin, site, collection, capsys):
    assert _run(admin, collection) == 0
    before = [(post.post_id, post.version) for post in _posts()]
    files_before = sorted(_stored_files())
    capsys.readouterr()

    assert _run(admin, collection) == 0
    assert [(post.post_id, post.version) for post in _posts()] == before
    assert sorted(_stored_files()) == files_before
    output = capsys.readouterr().out
    assert "import: 5 files: 0 created, 3 skipped, 2 refused, 0 failed" in output


def test_dry_run(admin, site, collection, capsys):
    assert _run(admin, collection, "--dry-run", "--tags", "imported") == 0
    # nothing was made of it: no post, no tag, no file
    assert _posts() == []
    assert db.session.query(model.Tag).count() == 0
    assert db.session.query(model.Snapshot).count() == 0
    assert _stored_files() == []
    output = capsys.readouterr().out
    assert (
        "import: 5 files (dry run, nothing was created): 2 would be created, "
        "1 skipped, 2 refused, 0 failed"
    ) in output
    assert "Unhandled file type" in output and "Post content missing." in output

    # the import then does what the dry run said
    assert _run(admin, collection) == 0
    assert "2 created, 1 skipped, 2 refused, 0 failed" in capsys.readouterr().out
    # and a dry run afterwards sees that there is nothing left to do
    assert _run(admin, collection, "--dry-run") == 0
    assert "0 would be created, 3 skipped, 2 refused" in capsys.readouterr().out


def test_every_file_is_named_as_it_is_done(admin, site, collection, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="lithica.func.post_import"):
        assert _run(admin, collection, "--dry-run") == 0
    assert "would create a post from a-copy-of-b.png" in caplog.messages
    assert "skipped b.png: The same file as a-copy-of-b.png" in caplog.messages
    assert not [line for line in caplog.messages if line.startswith("created")]
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="lithica.func.post_import"):
        assert _run(admin, collection) == 0
    first = _posts()[0].post_id
    assert "created post %d from a-copy-of-b.png" % first in caplog.messages
    assert "skipped b.png: Post already uploaded (%d)" % first in caplog.messages
    assert any(line.startswith("refused sub") for line in caplog.messages)


def test_dry_run_tells_a_duplicate_in_the_folder_from_one_in_the_site(site, collection):
    result = post_import.import_folder(str(collection), "importer", "safe", [], True)
    by_path = {outcome.path: outcome for outcome in result.outcomes}
    assert by_path["a-copy-of-b.png"].status == post_import.CREATED
    assert by_path["b.png"].status == post_import.SKIPPED
    assert by_path["b.png"].detail == "The same file as a-copy-of-b.png"

    post_import.import_folder(str(collection), "importer", "safe", [])
    result = post_import.import_folder(str(collection), "importer", "safe", [], True)
    post_id = _posts()[0].post_id
    assert result.outcomes[0].detail == "Post already uploaded (%d)" % post_id


def test_file_that_fails_costs_that_file_only(
    admin, site, collection, capsys, monkeypatch
):
    real = posts.create_post

    def failing(content, tag_names, user):
        if content.path.endswith("b.png") and "copy" not in content.path:
            raise RuntimeError("the disk is full")
        return real(content, tag_names, user)

    monkeypatch.setattr(posts, "create_post", failing)
    # the copy is imported first; put the failure on a file that is new
    (collection / "a-copy-of-b.png").unlink()
    assert _run(admin, collection) == 1
    assert len(_posts()) == 1
    output = capsys.readouterr().out
    assert "import: 4 files: 1 created, 0 skipped, 2 refused, 1 failed" in output
    assert "  failed  b.png: RuntimeError: the disk is full" in output

    # once the cause is gone, a second run brings in what is missing
    monkeypatch.setattr(posts, "create_post", real)
    assert _run(admin, collection) == 0
    assert len(_posts()) == 2
    assert "1 created, 1 skipped, 2 refused, 0 failed" in capsys.readouterr().out


def test_broken_picture_is_refused(admin, site, tmp_path, read_asset, capsys):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "cut.png").write_bytes(read_asset("png.png")[:200])
    (folder / "whole.png").write_bytes(read_asset("png.png"))
    assert _run(admin, folder) == 0
    assert len(_posts()) == 1
    output = capsys.readouterr().out
    assert "import: 2 files: 1 created, 0 skipped, 1 refused, 0 failed" in output
    assert "  refused  cut.png: " in output


def test_empty_folder(admin, site, tmp_path, capsys):
    folder = tmp_path / "empty"
    folder.mkdir()
    assert _run(admin, folder) == 0
    output = capsys.readouterr().out
    assert "import: 0 files: 0 created, 0 skipped, 0 refused, 0 failed" in output
    assert "problems" not in output


def test_import_that_cannot_start(admin, site, collection, tmp_path, capsys):
    assert (
        admin.main(["import", str(collection), "--user", "nobody", "--safety", "safe"])
        == 1
    )
    assert "import: User 'nobody' not found." in capsys.readouterr().err

    assert _run(admin, tmp_path / "no-such-folder") == 1
    assert "is not a folder" in capsys.readouterr().err
    assert _run(admin, collection / "b.png") == 1
    assert "is not a folder" in capsys.readouterr().err

    config.config["tag_name_regex"] = r"^[a-z]+$"
    assert _run(admin, collection, "--tags", "fine,Not Fine") == 1
    assert "'Not Fine' is not a valid tag name." in capsys.readouterr().err
    assert _posts() == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["import"],
        ["import", "folder"],
        ["import", "folder", "--user", "importer"],
        ["import", "folder", "--safety", "safe"],
        ["import", "folder", "--user", "importer", "--safety", "maybe"],
    ],
)
def test_user_and_safety_must_be_given(admin, site, arguments):
    with pytest.raises(SystemExit) as stopped:
        admin.main(arguments)
    assert stopped.value.code == 2
    assert _posts() == []


def test_existing_tags_are_used(admin, site, collection, tag_factory):
    category = db.session.query(model.TagCategory).one()
    db.session.add(tag_factory(names=["imported", "alias"], category=category))
    db.session.commit()
    assert _run(admin, collection, "--tags", "alias,new") == 0
    assert db.session.query(model.Tag).count() == 2
    for post in _posts():
        assert sorted(tag.first_name for tag in post.tags) == ["imported", "new"]


def test_modules_work_on_imported_files_as_on_uploads(
    admin, site, tmp_path, monkeypatch, tag_category_factory, capsys
):
    from lithica.tests.fixtures.modules import dummy
    from lithica.tests.test_dummy_module import CAT, _png

    db.session.add(tag_category_factory(name="meta"))
    db.session.commit()
    monkeypatch.setattr(registry, "MODULE_PACKAGE", "lithica.tests.fixtures.modules")
    config.config["modules"] = ["dummy"]
    folder = tmp_path / "with-module"
    folder.mkdir()
    (folder / "1-text.png").write_bytes(_png(CAT, shade=1))
    (folder / "2-file.dummy").write_bytes(dummy.FILE_MAGIC + _png(shade=2))
    (folder / "3-forbidden.dummy").write_bytes(dummy.FILE_MAGIC + b"FORBIDDEN")

    assert _run(admin, folder, "--dry-run") == 0
    output = capsys.readouterr().out
    assert "2 would be created, 0 skipped, 1 refused, 0 failed" in output
    assert "3-forbidden.dummy: A dummy file must not start with FORBIDDEN." in output

    assert _run(admin, folder) == 0
    output = capsys.readouterr().out
    assert "import: 3 files: 2 created, 0 skipped, 1 refused, 0 failed" in output
    assert (
        "  refused  3-forbidden.dummy: A dummy file must not start with FORBIDDEN."
        in output
    )
    text, file = _posts()
    # extracted and tagged as an upload is
    assert [row.kind for row in text.contents] == ["dummy_v1"] * 3
    assert {tag.first_name: tag.category.name for tag in text.tags} == {
        "dummy_text": "meta",
        "from_file": "meta",
    }
    # and a file type of a module is a post of that type
    assert file.type == "dummyfile" and file.mime_type == "application/x-lithica-dummy"


def test_a_module_cannot_take_the_command():
    module = registry.Module(
        name="a",
        admin_commands=[registry.AdminCommand("import", "mine", lambda arguments: 0)],
    )
    with pytest.raises(Exception, match="adds the command 'import' twice"):
        registry.use([module])
