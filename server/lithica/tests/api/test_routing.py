import json
from typing import Annotated, Any
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from lithica import errors, search
from lithica.api import dependencies, error_handlers
from lithica.api.dependencies import (
    Fields,
    PageParams,
    RequestDataParam,
    body,
)
from lithica.api.routing import ApiRouter
from lithica.api.schemas import Int, RequestModel, ResponseModel, Str, request_body
from lithica.func import file_uploads, net

BOUNDARY = "----lithicatestboundary"

# (field name, file name or None, content type or None, payload)
Part = tuple[str, str | None, str | None, bytes]


def _multipart(parts: list[Part]) -> dict[str, Any]:
    content = b""
    for name, file_name, content_type, payload in parts:
        disposition = 'form-data; name="%s"' % name
        if file_name is not None:
            disposition += '; filename="%s"' % file_name
        content += ("--%s\r\n" % BOUNDARY).encode()
        content += ("Content-Disposition: %s\r\n" % disposition).encode()
        if content_type is not None:
            content += ("Content-Type: %s\r\n" % content_type).encode()
        content += b"\r\n" + payload + b"\r\n"
    content += ("--%s--\r\n" % BOUNDARY).encode()
    return {
        "content": content,
        "headers": {"Content-Type": "multipart/form-data; boundary=%s" % BOUNDARY},
    }


class _Thing(ResponseModel):
    id: int


class _ThingParams(RequestModel):
    safety: Str = ""
    source: Str = ""
    number: Int = 0


@pytest.fixture
def client():
    router = ApiRouter()

    @router.get("/things", response_model=_Thing)
    def get_things(fields: Fields, page: PageParams) -> dict[str, Any]:
        return {"fields": fields, "page": [page.query, page.offset, page.limit]}

    @router.get("/thing/{name:path}")
    def get_thing(name: str) -> dict[str, Any]:
        return {"name": name}

    @router.get("/item/{name}")
    def get_item(name: str) -> dict[str, Any]:
        return {"name": name}

    @router.post("/things", openapi_extra=request_body(_ThingParams, "content"))
    def create_thing(
        data: RequestDataParam,
        params: Annotated[_ThingParams, Depends(body(_ThingParams))],
    ) -> dict[str, Any]:
        return {
            "params": data.params,
            "model": [params.safety, params.source, params.number],
            "files": {name: len(content) for name, content in data.files.items()},
            "hasContent": data.has_file("content"),
        }

    @router.post("/echo/{name}")
    def echo_file(name: str, data: RequestDataParam) -> dict[str, Any]:
        return {"hex": data.get_file(name).hex()}

    app = FastAPI()
    error_handlers.install(app)
    app.include_router(router)
    return TestClient(app, headers={"Accept": "application/json"})


def test_response_is_written_like_the_old_framework(client):
    response = client.get("/things")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.text.startswith('{\n  "fields": [],\n  "page": [')


def test_response_model_is_documentation_only(client):
    # the endpoint's data does not fit _Thing and is sent as it is
    assert "fields" in client.get("/things").json()
    schema = client.app.openapi()
    operation = schema["paths"]["/things"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/_Thing"
    }
    assert "4XX" in operation["responses"]


@pytest.mark.parametrize("path", ["/things", "/things/", "/item/a", "/item/a/"])
def test_trailing_slash_is_served_without_a_redirect(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200


def test_trailing_slash_variant_is_not_in_the_schema(client):
    assert set(client.app.openapi()["paths"]) == {
        "/things",
        "/thing/{name}",
        "/item/{name}",
        "/echo/{name}",
    }


@pytest.mark.parametrize(
    "path,name",
    [
        ("/thing/simple", "simple"),
        ("/thing/with/slashes", "with/slashes"),
        # in a :path parameter the trailing slash belongs to the value
        ("/thing/trailing/", "trailing/"),
        ("/thing/sp%20ace", "sp ace"),
        ("/thing/za%C5%BC%C3%B3%C5%82%C4%87", "zażółć"),
        ("/item/sp%20ace", "sp ace"),
    ],
)
def test_path_parameters(client, path, name):
    assert client.get(path).json() == {"name": name}


@pytest.mark.parametrize("accept", [None, "text/html", "*/*", "application/xml"])
def test_request_must_accept_json(client, accept):
    headers = {} if accept is None else {"Accept": accept}
    client.headers.pop("Accept")
    response = client.get("/things", headers=headers)
    assert response.status_code == 406
    assert response.json() == {
        "name": "ValidationError",
        "title": "Not Acceptable",
        "description": "This API only supports JSON responses.",
    }


@pytest.mark.parametrize(
    "accept", ["application/json", "application/json, text/plain, */*"]
)
def test_request_that_accepts_json(client, accept):
    assert client.get("/things", headers={"Accept": accept}).status_code == 200


@pytest.mark.parametrize(
    "query,fields",
    [
        ("", []),
        ("?fields=", []),
        ("?fields=id", ["id"]),
        ("?fields=id,name", ["id", "name"]),
        ("?fields=id%2Cname", ["id", "name"]),
    ],
)
def test_fields(client, query, fields):
    assert client.get("/things" + query).json()["fields"] == fields


@pytest.mark.parametrize(
    "query,page",
    [
        ("", ["", 0, 100]),
        ("?query=tag%20other&offset=20&limit=5", ["tag other", 20, 5]),
        ("?limit=1", ["", 0, 1]),
        ("?limit=100", ["", 0, 100]),
    ],
)
def test_page(client, query, page):
    assert client.get("/things" + query).json()["page"] == page


@pytest.mark.parametrize(
    "query,description",
    [
        ("?offset=-1", "Parameter 'offset' must be at least 0."),
        ("?offset=x", "Parameter 'offset' must be an integer value."),
        ("?limit=0", "Parameter 'limit' must be at least 1."),
        ("?limit=101", "Parameter 'limit' may not exceed 100."),
        ("?limit=many", "Parameter 'limit' must be an integer value."),
    ],
)
def test_invalid_page(client, query, description):
    response = client.get("/things" + query)
    assert response.status_code == 400
    assert response.json() == {
        "name": "InvalidParameterError",
        "title": "Validation error",
        "description": description,
    }


def test_search_builds_the_paged_response():
    executor = search.Executor(search.configs.TagSearchConfig())
    page = dependencies.Page("query text", 20, 5)
    with patch.object(executor, "execute", return_value=(7, ["a", "b"])) as execute:
        result = dependencies.search(executor, page, str.upper)
        execute.assert_called_once_with("query text", 20, 5)
    assert result == {
        "query": "query text",
        "offset": 20,
        "limit": 5,
        "total": 7,
        "results": ["A", "B"],
    }


def test_json_body(client):
    response = client.post("/things", json={"tags": ["a", "b"], "safety": "safe"})
    assert response.json()["params"] == {"tags": ["a", "b"], "safety": "safe"}
    assert response.json()["model"] == ["safe", "", 0]
    assert response.json()["hasContent"] is False


def test_json_body_is_read_whatever_the_content_type(client):
    for content_type in ["text/plain", "application/x-www-form-urlencoded"]:
        response = client.post(
            "/things",
            content=b'{"safety": "safe"}',
            headers={"Content-Type": content_type},
        )
        assert response.json()["params"] == {"safety": "safe"}


def test_no_body(client):
    assert client.post("/things").json()["params"] == {}


def test_body_overrides_the_query_string(client):
    response = client.post("/things?safety=query&source=query", json={"safety": "b"})
    assert response.json()["params"] == {"safety": "b", "source": "query"}
    assert response.json()["model"] == ["b", "query", 0]


def test_blank_query_values_are_dropped(client):
    assert client.post("/things?safety=").json()["params"] == {}


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe", b"[1, 2]", b'"text"'])
def test_invalid_json_body(client, content):
    response = client.post("/things", content=content)
    assert response.status_code == 400
    assert response.json() == {
        "name": "ValidationError",
        "title": "Bad Request",
        "description": "Could not decode the request body. The JSON "
        "was incorrect or was not encoded as UTF-8.",
    }


def test_invalid_parameter_in_body(client):
    response = client.post("/things", json={"number": "x"})
    assert response.status_code == 400
    assert response.json() == {
        "name": "InvalidParameterError",
        "title": "Validation error",
        "description": "Parameter 'number' must be an integer value.",
    }


def test_multipart_with_metadata_field(client):
    response = client.post(
        "/things",
        **_multipart(
            [
                ("metadata", None, None, b'{"safety": "safe"}'),
                ("content", "image.png", "image/png", b"\x89PNG-content"),
            ]
        ),
    )
    assert response.json()["model"] == ["safe", "", 0]
    assert response.json()["files"] == {"content": 12}
    assert response.json()["hasContent"] is True


def test_multipart_with_metadata_blob(client):
    # browsers send the JSON part as a Blob, which carries a file name
    response = client.post(
        "/things",
        **_multipart(
            [
                ("metadata", "blob", "application/json", b'{"safety": "safe"}'),
                ("content", "image.png", "image/png", b"content"),
                ("thumbnail", "thumb.jpg", "image/jpeg", b"thumbnail"),
            ]
        ),
    )
    assert response.json()["model"] == ["safe", "", 0]
    assert response.json()["files"] == {"metadata": 18, "content": 7, "thumbnail": 9}


def test_multipart_non_ascii_metadata(client):
    metadata = json.dumps({"source": "zażółć"}, ensure_ascii=False)
    response = client.post(
        "/things",
        **_multipart(
            [
                ("metadata", None, None, metadata.encode("utf-8")),
                ("content", "image.png", "image/png", b"content"),
            ]
        ),
    )
    assert response.json()["model"] == ["", "zażółć", 0]


def test_multipart_file_content_is_byte_exact(client):
    payload = bytes(range(256)) + b"\r\n--not-the-boundary\r\n" + b"\x00\xff"
    response = client.post(
        "/echo/content",
        **_multipart([("content", "data.bin", "application/octet-stream", payload)]),
    )
    assert bytes.fromhex(response.json()["hex"]) == payload


def test_multipart_large_file(client):
    payload = b"0123456789abcdef" * (3 * 1024 * 1024 // 16)
    response = client.post(
        "/things", **_multipart([("content", "big.bin", "video/mp4", payload)])
    )
    assert response.json()["files"] == {"content": len(payload)}


def test_multipart_without_metadata_keeps_query_params(client):
    response = client.post(
        "/things?safety=fromquery",
        **_multipart([("content", "image.png", "image/png", b"content")]),
    )
    assert response.json()["params"] == {"safety": "fromquery"}
    assert response.json()["files"] == {"content": 7}


def test_multipart_plain_field_is_not_a_file(client):
    parts: list[Part] = [
        ("metadata", None, None, b'{"safety": "safe"}'),
        ("content", None, None, b"just text"),
        ("thumbnail", "thumb.jpg", "image/jpeg", b"thumbnail"),
    ]
    response = client.post("/things", **_multipart(parts))
    assert response.json()["files"] == {"thumbnail": 9}
    assert response.json()["hasContent"] is False
    response = client.post("/echo/content", **_multipart(parts))
    assert response.status_code == 400
    assert response.json()["name"] == "MissingRequiredFileError"


def test_multipart_invalid_metadata(client):
    response = client.post(
        "/things",
        **_multipart(
            [
                ("metadata", None, None, b"{not json"),
                ("content", "image.png", "image/png", b"content"),
            ]
        ),
    )
    assert response.status_code == 400
    assert response.json()["name"] == "ValidationError"
    assert response.json()["description"].startswith("Could not decode the request")


def test_multipart_without_parts(client):
    response = client.post("/things", **_multipart([]))
    assert response.status_code == 400
    assert response.json() == {
        "name": "ValidationError",
        "title": "Bad Request",
        "description": "No files attached.",
    }


def test_multipart_malformed_body(client):
    response = client.post(
        "/things",
        content=b"this is not multipart",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 400
    assert response.json() == {
        "name": "ValidationError",
        "title": "Bad Request",
        "description": "Could not decode the multipart request body.",
    }


def test_get_file():
    data = dependencies.RequestData({}, {"key": b"content"})
    assert data.has_file("key")
    assert data.get_file("key") == b"content"
    assert not data.has_file("non-existing")
    with pytest.raises(errors.MissingRequiredFileError):
        data.get_file("non-existing")
    assert data.get_file("non-existing", default=b"") == b""


def test_get_file_from_url():
    with patch("lithica.func.net.download"):
        net.download.return_value = b"content"
        data = dependencies.RequestData({"keyUrl": "example.com"}, {})
        assert data.has_file("key")
        assert data.get_file("key") == b"content"
        net.download.assert_called_once_with("example.com", use_video_downloader=False)
        with pytest.raises(errors.ValidationError):
            data.get_file("non-existing")


def test_get_file_from_url_with_the_video_downloader():
    with patch("lithica.func.net.download"):
        net.download.return_value = b"content"
        data = dependencies.RequestData({"keyUrl": "example.com"}, {})
        data.get_file("key", use_video_downloader=True)
        net.download.assert_called_once_with("example.com", use_video_downloader=True)


def test_get_file_from_token(tmpdir, config_injector):
    config_injector({"data_dir": str(tmpdir)})
    token = file_uploads.save(b"uploaded earlier")
    data = dependencies.RequestData({"keyToken": token}, {})
    assert data.has_file("key")
    assert data.get_file("key") == b"uploaded earlier"
    # an upload endpoint takes the content itself, never a token
    assert not data.has_file("key", allow_tokens=False)
    with pytest.raises(errors.MissingRequiredFileError):
        data.get_file("key", allow_tokens=False)


def test_get_file_from_expired_token(tmpdir, config_injector):
    config_injector({"data_dir": str(tmpdir)})
    data = dependencies.RequestData({"keyToken": "gone"}, {})
    with pytest.raises(errors.MissingRequiredFileError) as ex:
        data.get_file("key")
    assert type(ex.value) is errors.MissingRequiredFileError
    with pytest.raises(errors.MissingOrExpiredRequiredFileError):
        data.get_file("key", default=b"")


def test_uploaded_file_wins_over_url_and_token():
    with patch("lithica.func.net.download") as download:
        data = dependencies.RequestData(
            {"keyUrl": "example.com", "keyToken": "t"}, {"key": b"uploaded"}
        )
        assert data.get_file("key") == b"uploaded"
        download.assert_not_called()
