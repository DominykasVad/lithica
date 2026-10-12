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
    # as lithica.openapi does it: importing the application builds a database
    # engine, which connects to nothing but needs the setting to be there, and
    # CI and a fresh checkout have none
    program = (
        "from lithica import config\n"
        "if not config.config.get('database'):\n"
        "    config.config['database'] = 'postgresql://unused@localhost/unused'\n"
        "import lithica.app\n"
    )
    started = subprocess.run(
        [sys.executable, "-c", program],
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


@pytest.mark.parametrize(
    "size", [0, -1, registry.PAYLOAD_SIZE_CAP + 1, 1024 * 1024 * 1024]
)
def test_payload_limit_beyond_the_cap_is_refused(size):
    kind = registry.ContentKind("alpha_v1", max_payload_size=size)
    with pytest.raises(errors.ConfigError, match="the most a kind may ask for is"):
        registry.use([registry.Module(name="alpha", content_kinds=[kind])])
    assert registry.modules() == ()


def test_payload_limit_up_to_the_cap_is_accepted():
    assert registry.PAYLOAD_SIZE_CAP == 32 * 1024 * 1024
    kinds = [
        registry.ContentKind("alpha_v1", max_payload_size=registry.PAYLOAD_SIZE_CAP),
        registry.ContentKind("alpha_v2", max_payload_size=1),
        registry.ContentKind("alpha_v3"),
    ]
    registry.use([registry.Module(name="alpha", content_kinds=kinds)])
    assert [kind.max_payload_size for kind in registry.content_kinds().values()] == [
        32 * 1024 * 1024,
        1,
        1024 * 1024,
    ]


def _file_type(**changes):
    values = {
        "post_type": "probefile",
        "mime_type": "application/x-probe",
        "extension": "probe",
        "detect": lambda head, handle: False,
    }
    values.update(changes)
    return registry.FileType(**values)


def test_file_types_of_the_loaded_modules():
    first, second = _file_type(), _file_type(post_type="b", mime_type="b/b")
    modules = [
        registry.Module(name="a", file_types=[first]),
        registry.Module(name="b", file_types=[second]),
    ]
    registry.use(modules)
    assert registry.file_types() == [(modules[0], first), (modules[1], second)]
    assert registry.file_type_for("b/b") is second
    assert registry.file_type_for("image/png") is None
    registry.use([])
    assert registry.file_types() == []
    assert registry.file_type_for("b/b") is None


@pytest.mark.parametrize(
    "changes,problem",
    [
        # the engine's post types, and the other names the search has for them
        ({"post_type": "image"}, "registers the post type 'image' a second time"),
        ({"post_type": "animation"}, "registers the post type 'animation' a second"),
        ({"post_type": "video"}, "registers the post type 'video' a second time"),
        ({"post_type": "flash"}, "registers the post type 'flash' a second time"),
        ({"post_type": "gif"}, "registers the post type 'gif' a second time"),
        ({"post_type": "webm"}, "registers the post type 'webm' a second time"),
        ({"post_type": "Probe"}, "has an invalid post type 'Probe'"),
        ({"post_type": "probe file"}, "has an invalid post type"),
        ({"post_type": ""}, "has an invalid post type"),
        ({"post_type": "p" * 33}, "has an invalid post type"),
        # the engine's MIME types
        ({"mime_type": "image/png"}, "registers the MIME type 'image/png' a second"),
        ({"mime_type": "video/mp4"}, "registers the MIME type 'video/mp4' a second"),
        ({"mime_type": "application/ogg"}, "registers the MIME type"),
        ({"mime_type": "application/octet-stream"}, "registers the MIME type"),
        # the column holds 32 characters
        ({"mime_type": "application/x-" + "p" * 19}, "has an invalid MIME type"),
        ({"mime_type": "Application/X-Probe"}, "has an invalid MIME type"),
        ({"mime_type": "probe"}, "has an invalid MIME type"),
        ({"mime_type": ""}, "has an invalid MIME type"),
        ({"extension": ".probe"}, "has an invalid file extension '.probe'"),
        ({"extension": "PROBE"}, "has an invalid file extension"),
        ({"extension": "../x"}, "has an invalid file extension"),
        ({"extension": ""}, "has an invalid file extension"),
        ({"extension": "p" * 17}, "has an invalid file extension"),
    ],
)
def test_file_type_that_cannot_work_is_refused(changes, problem):
    with pytest.raises(errors.ConfigError, match=problem):
        registry.use([registry.Module(name="a", file_types=[_file_type(**changes)])])
    assert registry.modules() == ()


def test_file_type_at_the_limits_is_accepted():
    file_type = _file_type(
        post_type="p" * 32,
        mime_type="application/x-" + "p" * 18,
        extension="p" * 16,
    )
    assert len(file_type.mime_type) == 32
    registry.use([registry.Module(name="a", file_types=[file_type])])
    assert registry.file_type_for(file_type.mime_type) is file_type


@pytest.mark.parametrize(
    "second,problem",
    [
        ({"mime_type": "application/x-other"}, "registers the post type 'probefile'"),
        ({"post_type": "otherfile"}, "registers the MIME type 'application/x-probe'"),
    ],
)
def test_file_types_of_two_modules_must_not_clash(second, problem):
    modules = [
        registry.Module(name="a", file_types=[_file_type()]),
        registry.Module(name="b", file_types=[_file_type(**second)]),
    ]
    with pytest.raises(errors.ConfigError, match="Module 'b' " + problem):
        registry.use(modules)
    # nor within one module
    with pytest.raises(errors.ConfigError, match="Module 'a' " + problem):
        registry.use(
            [registry.Module(name="a", file_types=[_file_type(), _file_type(**second)])]
        )
    assert registry.modules() == ()


def _greeting_module() -> registry.Module:
    router = ApiRouter()

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


ROUTE_MODULE = """
    from lithica import registry
    from lithica.api.routing import ApiRouter

    router = ApiRouter()

    @router.get("/hello", summary="Say hello")
    def %(name)s_hello() -> dict[str, str]:
        "Returns a greeting, which is all this route is for."
        return {"greeting": "hello"}

    module = registry.Module(name="%(name)s", router=router)
"""


def test_available_modules_are_all_there_are(inject_config, module_package):
    assert registry.available() == []
    module_package("beta", ROUTE_MODULE % {"name": "beta"})
    module_package("alpha", ROUTE_MODULE % {"name": "alpha"})
    inject_config(["beta"])
    registry.load_configured()
    # by name, whatever is switched on, and without switching anything on
    assert [module.name for module in registry.available()] == ["alpha", "beta"]
    assert [module.name for module in registry.modules()] == ["beta"]


def test_real_package_has_only_modules_that_load():
    # what the committed contract is generated from
    for module in registry.available():
        assert isinstance(module, registry.Module)


def test_package_that_is_not_a_module_is_refused(module_package):
    module_package("alpha", "")
    with pytest.raises(errors.ConfigError, match="has no 'module' object"):
        registry.available()


def test_contract_has_the_routes_of_every_module(inject_config, module_package):
    engine_paths = set(openapi.build()["paths"])
    module_package("beta", ROUTE_MODULE % {"name": "beta"})
    module_package("alpha", ROUTE_MODULE % {"name": "alpha"})
    module_package(
        "quiet",
        "from lithica import registry\nmodule = registry.Module(name='quiet')\n",
    )
    # none is switched on: the contract does not depend on the settings
    inject_config([])
    registry.load_configured()

    document = openapi.build()
    assert set(document["paths"]) - engine_paths == {
        "/modules/alpha/hello",
        "/modules/beta/hello",
    }
    for name in ["alpha", "beta"]:
        operation = document["paths"]["/modules/%s/hello" % name]["get"]
        assert operation["tags"] == [name]
        assert operation["operationId"] == "%s_hello" % name
    # a tag per module with routes, after the engine's, by name
    tags = [tag["name"] for tag in document["tags"]]
    assert tags == [tag["name"] for tag in openapi.TAGS] + ["alpha", "beta"]
    assert all(tag["description"] for tag in document["tags"])
    assert registry.modules() == ()


def test_contract_is_the_same_whatever_is_switched_on(inject_config, module_package):
    module_package("alpha", ROUTE_MODULE % {"name": "alpha"})
    without = openapi.dump()
    inject_config(["alpha"])
    registry.load_configured()
    assert openapi.dump() == without


def test_served_document_has_the_modules_of_the_site(inject_config, module_package):
    module_package("beta", ROUTE_MODULE % {"name": "beta"})
    module_package("alpha", ROUTE_MODULE % {"name": "alpha"})
    inject_config(["beta"])
    registry.load_configured()
    served = create_app().openapi()
    assert "/modules/beta/hello" in served["paths"]
    assert "/modules/alpha/hello" not in served["paths"]
    assert [tag["name"] for tag in served["tags"]][-1] == "beta"
    assert served["paths"]["/modules/beta/hello"]["get"]["tags"] == ["beta"]


def test_module_that_tags_its_routes_is_refused():
    router = ApiRouter(tags=["Mine"])

    @router.get("/hello")
    def hello() -> dict[str, str]:
        return {"greeting": "hello"}

    with pytest.raises(errors.ConfigError, match="tags its route '/hello'"):
        registry.use([registry.Module(name="greeting", router=router)])
    assert registry.modules() == ()


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
