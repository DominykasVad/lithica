import json
import os
import subprocess
import sys

import pytest

from lithica import openapi
from lithica.version import get_version

COMMITTED = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, "doc", "openapi.json"
)

# requests that take no body
NO_BODY = {
    "set_tag_category_as_default",
    "set_pool_category_as_default",
    "add_post_to_favorites",
}


@pytest.fixture(scope="module")
def document():
    return openapi.build()


def _operations(document):
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            yield method, path, operation


def test_committed_document_is_the_generated_one():
    if not os.path.exists(COMMITTED):
        pytest.skip("doc/openapi.json is not part of this checkout (server image)")
    with open(COMMITTED, encoding="utf-8") as handle:
        committed = handle.read()
    assert committed == openapi.dump(), (
        "doc/openapi.json is out of date. Regenerate it from server/ with: "
        "uv run python -m lithica.openapi > ../doc/openapi.json"
    )


def test_document_is_the_same_every_time():
    assert openapi.dump() == openapi.dump()


def test_module_prints_the_document_without_a_configured_database(tmpdir):
    # as in CI and in a fresh checkout: no config.yaml, no database
    server_dir = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
    environment = {key: value for key, value in os.environ.items() if key != "API_DOCS"}
    printed = subprocess.run(
        [sys.executable, "-m", "lithica.openapi"],
        cwd=server_dir,
        env=environment,
        capture_output=True,
        timeout=120,
    )
    assert printed.returncode == 0, printed.stderr.decode()
    assert json.loads(printed.stdout)["info"]["title"] == "Lithica"
    assert printed.stdout.endswith(b"}\n")


def test_document_describes_the_whole_api(document):
    assert document["info"]["version"] == get_version()
    assert document["info"]["license"]["identifier"] == "GPL-3.0-only"
    operations = list(_operations(document))
    assert len(operations) == 60
    assert len(document["paths"]) == 34
    # the documentation routes themselves are not part of the API
    assert "/docs" not in document["paths"]
    assert "/openapi.json" not in document["paths"]
    # nor are the trailing-slash twins of the routes
    assert not any(path.endswith("/") for path in document["paths"])


def test_operation_ids_are_the_handler_names(document):
    ids = [operation["operationId"] for _m, _p, operation in _operations(document)]
    assert len(set(ids)) == len(ids)
    assert "create_post" in ids and "get_tag_siblings" in ids
    assert all(id.isidentifier() for id in ids)


def test_every_operation_is_documented(document):
    known_tags = {tag["name"] for tag in document["tags"]}
    for method, path, operation in _operations(document):
        where = "%s %s" % (method.upper(), path)
        assert operation.get("summary"), where
        assert len(operation.get("description", "")) > 20, where
        assert operation["tags"] and set(operation["tags"]) <= known_tags, where
        # the result is described by a model, the errors by the error body
        success = operation["responses"]["200"]["content"]["application/json"]
        assert success["schema"], where
        assert "4XX" in operation["responses"], where


def test_every_operation_with_input_describes_its_body(document):
    for method, path, operation in _operations(document):
        where = "%s %s" % (method.upper(), path)
        needs_body = method in ("post", "put") or (
            method == "delete" and operation["operationId"].startswith("delete_")
        )
        if operation["operationId"] in NO_BODY or operation["operationId"] in (
            "delete_user_token",
            "delete_post_score",
            "delete_comment_score",
            "delete_post_from_favorites",
        ):
            needs_body = False
        assert ("requestBody" in operation) == needs_body, where
        if needs_body:
            assert "application/json" in operation["requestBody"]["content"], where


def test_uploads_are_described_as_multipart(document):
    for path, method, files in [
        ("/posts", "post", {"content", "thumbnail"}),
        ("/post/{post_id}", "put", {"content", "thumbnail"}),
        ("/users", "post", {"avatar"}),
        ("/user/{user_name}", "put", {"avatar"}),
        ("/uploads", "post", {"content"}),
        ("/posts/reverse-search", "post", {"content"}),
    ]:
        content = document["paths"][path][method]["requestBody"]["content"]
        parts = content["multipart/form-data"]["schema"]["properties"]
        assert set(parts) == files | {"metadata"}, path
        for name in files:
            assert parts[name] == {"type": "string", "format": "binary"}
        assert parts["metadata"] == content["application/json"]["schema"]


def test_request_bodies_list_their_required_fields(document):
    def required(path, method):
        operation = document["paths"][path][method]
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        return set(schema.get("required", []))

    assert required("/tags", "post") == {"names", "category"}
    assert required("/tag/{tag_name}", "put") == {"version"}
    assert required("/tag/{tag_name}", "delete") == {"version"}
    assert required("/post-merge", "post") == {
        "remove",
        "mergeTo",
        "removeVersion",
        "mergeToVersion",
        "replaceContent",
    }
    assert required("/posts", "post") == {"safety"}
    assert required("/user-token/{user_name}", "post") == set()


def test_credentials_are_optional_and_of_two_kinds(document):
    schemes = document["components"]["securitySchemes"]
    assert set(schemes) == {"basicAuth", "tokenAuth"}
    for _method, _path, operation in _operations(document):
        assert operation["security"] == [{"basicAuth": []}, {"tokenAuth": []}, {}]


def test_common_parameters_are_described(document):
    def names(path, method):
        return {p["name"] for p in document["paths"][path][method]["parameters"]}

    assert names("/posts", "get") == {
        "bump-login",
        "fields",
        "query",
        "offset",
        "limit",
    }
    assert names("/post/{post_id}", "get") == {"post_id", "bump-login", "fields"}
    assert names("/post/{post_id}/around", "get") == {
        "post_id",
        "bump-login",
        "fields",
        "query",
    }
    limit = next(
        p
        for p in document["paths"]["/posts"]["get"]["parameters"]
        if p["name"] == "limit"
    )
    assert limit["schema"]["minimum"] == 1 and limit["schema"]["maximum"] == 100


def test_no_response_field_is_required(document):
    for name, schema in document["components"]["schemas"].items():
        if name != "ErrorResponse":
            assert "required" not in schema, name


def test_server_is_relative_to_the_document(document):
    assert document["servers"] == [{"url": "./", "description": "This server."}]
