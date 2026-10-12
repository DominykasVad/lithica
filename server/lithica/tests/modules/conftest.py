import pytest

from lithica import config, db, model, registry
from lithica.app import create_app
from lithica.tests.conftest import ApiClient


@pytest.fixture
def site(config_injector, tmpdir, tag_category_factory):
    """
    A site whose modules the test names: returns a function that loads
    them from lithica/modules and starts the application, as a restart
    with another `modules` setting would.
    """
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
            "privileges": {
                "posts:create:identified": model.User.RANK_REGULAR,
                "posts:list": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
                "posts:view:content:private": model.User.RANK_MODERATOR,
                "posts:edit:content": model.User.RANK_REGULAR,
                "posts:delete": model.User.RANK_REGULAR,
                "uploads:use_downloader": model.User.RANK_POWER,
                "tags:create": model.User.RANK_REGULAR,
                "users:edit:any:email": model.User.RANK_MODERATOR,
            },
        }
    )
    db.session.add(tag_category_factory(name="default", default=True))
    db.session.flush()

    def start(modules):
        # through the setting, which the admin CLI reads as well
        config.config["modules"] = modules
        registry.load_configured()
        return ApiClient(create_app())

    return start


@pytest.fixture
def user(user_factory):
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    return user
