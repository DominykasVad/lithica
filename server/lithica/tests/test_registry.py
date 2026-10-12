"""The module registry: loading modules and what the engine does with them."""

import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from lithica import db, errors, model, openapi, registry
from lithica.api.routing import ApiRouter
from lithica.app import create_app
from lithica.search.configs import util as search_util
from lithica.tests.api.http import assert_error, ok
from lithica.tests.conftest import ApiClient

ADMIN_PATH = Path(__file__).resolve().parent.parent.parent / "lithica-admin"


@pytest.fixture
def inject_config(config_injector):
    def inject(modules=None):
        config_injector(
            {
                "modules": modules,
                "secret": "test",
                "data_dir": "",
                "data_url": "http://example.com/",
                "privileges": {"posts:list": model.User.RANK_REGULAR},
                "thumbnails": {"post_width": 300, "post_height": 300},
            }
        )

    inject()
    return inject


def test_nothing_is_loaded_by_default(inject_config):
    registry.load_configured()
    assert registry.modules() == ()
    assert registry.post_search_filters() == {}
    assert registry.post_fields() == {}
    assert registry.admin_commands() == []


def test_shipped_configuration_lists_no_module():
    from lithica import config

    assert config._file_config("config.yaml.dist")["modules"] == []


def test_loading_modules_in_the_configured_order(inject_config, module_package):
    for name in ["alpha", "beta"]:
        module_package(
            name,
            """
            from lithica import registry
            module = registry.Module(name=%r)
            """
            % name,
        )
    inject_config(["beta", "alpha"])
    registry.load_configured()
    assert [module.name for module in registry.modules()] == ["beta", "alpha"]


def test_unknown_module_is_refused(inject_config, module_package):
    inject_config(["missing"])
    with pytest.raises(errors.ConfigError, match="Unknown module 'missing'"):
        registry.load_configured()
    assert registry.modules() == ()


def test_unknown_module_in_the_real_package_is_refused():
    with pytest.raises(errors.ConfigError, match="Unknown module 'no_such_module'"):
        registry.load(["no_such_module"])


def test_modules_variable_names_the_modules_to_load(
    inject_config, module_package, monkeypatch
):
    from lithica import config

    for name in ["alpha", "beta"]:
        module_package(
            name,
            """
            from lithica import registry
            module = registry.Module(name=%r)
            """
            % name,
        )
    monkeypatch.setenv("MODULES", " beta, ,alpha ")
    inject_config(config._environment_overrides()["modules"])
    registry.load_configured()
    assert [module.name for module in registry.modules()] == ["beta", "alpha"]


def test_unknown_module_in_the_variable_is_refused(
    inject_config, module_package, monkeypatch
):
    from lithica import config

    monkeypatch.setenv("MODULES", "missing")
    inject_config(config._environment_overrides()["modules"])
    with pytest.raises(errors.ConfigError, match="Unknown module 'missing'"):
        registry.load_configured()


@pytest.mark.parametrize("value,loads", [("no_such_module", False), (" , ", True)])
def test_server_start_with_the_modules_variable(value, loads):
    # the whole way, as a server process goes it: environment, configuration,
    # registry. Importing the application is what loads the modules.
    server_dir = Path(__file__).resolve().parent.parent.parent
    started = subprocess.run(
        [sys.executable, "-c", "import lithica.app"],
        cwd=server_dir,
        env={**os.environ, "MODULES": value},
        capture_output=True,
        timeout=120,
    )
    if loads:
        assert started.returncode == 0, started.stderr.decode()
    else:
        assert started.returncode != 0
        assert "Unknown module 'no_such_module'" in started.stderr.decode()


@pytest.mark.parametrize(
    "setting",
    ["alpha", {"alpha": True}, [1], ["Alpha"], ["al.pha"], ["../alpha"], [""]],
)
def test_malformed_setting_is_refused(inject_config, module_package, setting):
    module_package("alpha", "from lithica import registry\n")
    inject_config(setting)
    with pytest.raises(errors.ConfigError):
        registry.load_configured()


def test_package_without_a_description_is_refused(inject_config, module_package):
    module_package("alpha", "module = 'not a Module'\n")
    inject_config(["alpha"])
    with pytest.raises(errors.ConfigError, match="no 'module' object"):
        registry.load_configured()


def test_module_under_another_name_is_refused(inject_config, module_package):
    module_package(
        "alpha",
        """
        from lithica import registry
        module = registry.Module(name="beta")
        """,
    )
    inject_config(["alpha"])
    with pytest.raises(errors.ConfigError, match="calls itself 'beta'"):
        registry.load_configured()


def test_broken_module_is_not_reported_as_unknown(inject_config, module_package):
    module_package("alpha", "import a_package_nobody_has\n")
    inject_config(["alpha"])
    with pytest.raises(ModuleNotFoundError, match="a_package_nobody_has"):
        registry.load_configured()


def test_failed_load_keeps_what_was_loaded(inject_config, module_package):
    registry.use([registry.Module(name="kept")])
    inject_config(["missing"])
    with pytest.raises(errors.ConfigError):
        registry.load_configured()
    assert [module.name for module in registry.modules()] == ["kept"]


def _noop_filter(query, _criterion, _negated):
    return query


@pytest.mark.parametrize(
    "modules,problem",
    [
        ([registry.Module(name="Bad-Name")], "invalid name"),
        ([registry.Module(name="a"), registry.Module(name="a")], "listed twice"),
        (
            [registry.Module(name="a", search_filters={"tag-count": _noop_filter})],
            "search token 'tag-count' twice",
        ),
        (
            [
                registry.Module(name="a", search_filters={"mine": _noop_filter}),
                registry.Module(name="b", search_filters={"mine": _noop_filter}),
            ],
            "search token 'mine' twice",
        ),
        (
            [registry.Module(name="a", post_fields={"tags": lambda post, user: 1})],
            "post field 'tags' twice",
        ),
        (
            [
                registry.Module(name="a", post_fields={"mine": lambda post, user: 1}),
                registry.Module(name="b", post_fields={"mine": lambda post, user: 1}),
            ],
            "post field 'mine' twice",
        ),
        (
            [
                registry.Module(
                    name="a",
                    admin_commands=[
                        registry.AdminCommand("backfill", "", lambda arguments: 0)
                    ],
                )
            ],
            "command 'backfill' twice",
        ),
        (
            [
                registry.Module(name="a", content_kinds=[registry.ContentKind("k")]),
                registry.Module(name="b", content_kinds=[registry.ContentKind("k")]),
            ],
            "content kind 'k' a second time",
        ),
        (
            [registry.Module(name="a", content_kinds=[registry.ContentKind("K 1")])],
            "invalid content kind",
        ),
        (
            [
                registry.Module(
                    name="a",
                    extractors=[
                        registry.Extractor(frozenset({"image/png"}), lambda m, f: [])
                    ],
                )
            ],
            "declares no content kind",
        ),
    ],
)
def test_clashing_modules_are_refused(modules, problem):
    with pytest.raises(errors.ConfigError, match=problem):
        registry.use(modules)
    assert registry.modules() == ()


def _greeting_module() -> registry.Module:
    router = ApiRouter(tags=["Greeting"])

    @router.get("/hello")
    def hello() -> dict[str, str]:
        return {"greeting": "hello"}

    return registry.Module(name="greeting", router=router)


def test_routes_are_served_under_the_modules_path(session):
    application = create_app(modules=[_greeting_module()])
    client = ApiClient(application)
    assert ok(client.get("/modules/greeting/hello")) == {"greeting": "hello"}
    # as the engine's routes: also with a trailing slash, and JSON only
    assert ok(client.get("/modules/greeting/hello/")) == {"greeting": "hello"}
    assert client.get("/hello").status_code == 404
    refused = client.get("/modules/greeting/hello", headers={"Accept": "text/html"})
    assert refused.status_code == 406


def test_application_serves_the_loaded_modules(session):
    registry.use([_greeting_module()])
    client = ApiClient(create_app())
    assert ok(client.get("/modules/greeting/hello")) == {"greeting": "hello"}


def test_application_without_modules_has_no_module_route(client):
    assert client.get("/modules/greeting/hello").status_code == 404


def test_contract_leaves_module_routes_out():
    registry.use([_greeting_module()])
    assert not [path for path in openapi.build()["paths"] if "modules" in path]
    served = create_app().openapi()
    assert "/modules/greeting/hello" in served["paths"]


def test_search_token_of_a_module(inject_config, client, post_factory, user_factory):
    posts = [post_factory(), post_factory(), post_factory()]
    db.session.add_all(posts)
    db.session.flush()
    registry.use(
        [
            registry.Module(
                name="a",
                search_filters={
                    "number": search_util.create_num_filter(model.Post.post_id)
                },
            )
        ]
    )
    user = user_factory(rank=model.User.RANK_REGULAR)
    found = ok(
        client.get(
            "/posts",
            user=user,
            query={"query": "number:%d" % posts[1].post_id, "fields": "id"},
        )
    )
    assert [post["id"] for post in found["results"]] == [posts[1].post_id]
    # the engine's tokens are still there, and work together with it
    found = ok(
        client.get(
            "/posts",
            user=user,
            query={
                "query": "-number:%d sort:id,asc" % posts[1].post_id,
                "fields": "id",
            },
        )
    )
    assert [post["id"] for post in found["results"]] == [
        posts[0].post_id,
        posts[2].post_id,
    ]


def test_search_token_is_unknown_without_the_module(
    inject_config, client, user_factory
):
    response = client.get(
        "/posts",
        user=user_factory(rank=model.User.RANK_REGULAR),
        query={"query": "number:1"},
    )
    assert_error(response, errors.SearchError)


def test_post_field_of_a_module(
    inject_config, client, post_factory, user_factory, tag_category_factory
):
    post = post_factory()
    db.session.add_all([post, tag_category_factory(default=True)])
    db.session.flush()
    registry.use(
        [
            registry.Module(
                name="a",
                post_fields={
                    "shout": lambda post, user: "%d for %s" % (post.post_id, user.name)
                },
            )
        ]
    )
    user = user_factory(name="reader", rank=model.User.RANK_REGULAR)
    expected = "%d for reader" % post.post_id

    chosen = ok(client.get("/posts", user=user, query={"fields": "id,shout"}))
    assert chosen["results"] == [{"id": post.post_id, "shout": expected}]
    # without a choice of fields a post has all of them, the module's too
    everything = ok(client.get("/posts", user=user))["results"][0]
    assert everything["shout"] == expected
    assert everything["id"] == post.post_id


def test_post_field_is_unknown_without_the_module(
    inject_config, client, post_factory, user_factory, tag_category_factory
):
    db.session.add_all([post_factory(), tag_category_factory(default=True)])
    db.session.flush()
    user = user_factory(rank=model.User.RANK_REGULAR)
    assert_error(
        client.get("/posts", user=user, query={"fields": "shout"}),
        errors.ValidationError,
    )
    assert "shout" not in ok(client.get("/posts", user=user))["results"][0]


@pytest.fixture(scope="module")
def admin():
    # lithica-admin is a script without the .py suffix
    loader = SourceFileLoader("lithica_admin", str(ADMIN_PATH))
    spec = spec_from_loader("lithica_admin", loader)
    assert spec
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


ADMIN_MODULE = """
    from lithica import db, model, registry

    def configure(parser):
        parser.add_argument("--times", type=int, default=1)

    def run(arguments):
        # run inside the command's database session scope
        count = db.session.query(model.Post).count()
        print("posts: %d" % count * arguments.times)
        return 4

    module = registry.Module(
        name="alpha",
        admin_commands=[
            registry.AdminCommand("count-posts", "count the posts", run, configure)
        ],
    )
"""


def test_admin_command_of_a_module(
    inject_config, module_package, admin, post_factory, capsys
):
    module_package("alpha", ADMIN_MODULE)
    inject_config(["alpha"])
    db.session.add(post_factory())
    db.session.flush()
    assert admin.main(["count-posts", "--times", "2"]) == 4
    assert capsys.readouterr().out == "posts: 1posts: 1\n"

    with pytest.raises(SystemExit):
        admin.main(["--help"])
    assert "count the posts" in capsys.readouterr().out


def test_admin_command_is_unknown_without_the_module(inject_config, admin):
    with pytest.raises(SystemExit) as ex:
        admin.main(["count-posts"])
    assert ex.value.code == 2


def test_admin_refuses_an_unknown_module(inject_config, module_package, admin, capsys):
    inject_config(["missing"])
    assert admin.main(["backfill", "all"]) == 1
    assert "Unknown module 'missing'" in capsys.readouterr().err


def test_admin_commands_a_module_may_not_take(inject_config, admin, capsys):
    # the registry's list of the CLI's own commands must be the real one
    with pytest.raises(SystemExit):
        admin.main(["--help"])
    listed = capsys.readouterr().out
    for command in registry.ENGINE_ADMIN_COMMANDS:
        assert command in listed
