import hashlib
import json
import os
import tempfile
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
    read_body,
)
from lithica.api.routing import ApiRouter
from lithica.api.schemas import Int, RequestModel, ResponseModel, Str, request_body
from lithica.func import content as content_module
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
        params: Annotated[_ThingParams, Depends(read_body(_ThingParams))],
    ) -> dict[str, Any]:
        return {
            "params": data.params,
            "model": [params.safety, params.source, params.number],
            "files": {name: len(content) for name, content in data.files.items()},
            "hasContent": data.has_file("content"),
        }

    @router.post("/echo/{name}")
    def echo_file(name: str, data: RequestDataParam) -> dict[str, Any]:
        return {"hex": content_module.read(data.get_file(name)).hex()}

    @router.post("/where/{name}")
    def where_is_file(name: str, data: RequestDataParam) -> dict[str, Any]:
        """Report how the file is held: in memory, or at which path."""
        content = data.get_file(name)
        on_disk = isinstance(content, content_module.Content)
        return {
            "path": content.path if on_disk else None,
            "size": content_module.size(content),
            "sha1": content_module.sha1(content),
        }

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
        "/where/{name}",
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


def _streamed(body: bytes, piece: int = 65536):
    """The body as a generator, so that it is sent without a Content-Length."""
    for start in range(0, len(body), piece):
        yield body[start : start + piece]


@pytest.fixture
def temporary_dir(config_injector, tmpdir):
    """A data directory for the test; gives its folder for temporary files."""
    config_injector({"data_dir": str(tmpdir.mkdir("data"))})
    return content_module.temporary_dir()


def _left_behind(temporary_dir: str) -> list[str]:
    return os.listdir(temporary_dir)


@pytest.fixture
def upload_dirs(monkeypatch, temporary_dir):
    """The directories made for the uploads of the requests in this test."""
    made: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args: Any, **kwargs: Any) -> str:
        made.append(real_mkdtemp(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(dependencies.tempfile, "mkdtemp", recording_mkdtemp)
    return made


def _all_removed(directories: list[str]) -> bool:
    assert directories, "no upload directory was made"
    return not any(os.path.exists(directory) for directory in directories)


def test_small_upload_is_kept_in_memory(client):
    payload = b"x" * 1000
    response = client.post(
        "/where/content", **_multipart([("content", "small.bin", None, payload)])
    )
    assert response.json() == {
        "path": None,
        "size": 1000,
        "sha1": hashlib.sha1(payload).hexdigest(),
    }


def test_large_upload_is_written_to_disk_and_removed_afterwards(
    client, upload_dirs, temporary_dir
):
    payload = os.urandom(3 * 1024 * 1024 + 17)
    response = client.post(
        "/where/content",
        **_multipart(
            [
                ("metadata", None, None, b'{"safety": "safe"}'),
                ("content", "big.bin", "video/mp4", payload),
            ]
        ),
    )
    result = response.json()
    assert result["size"] == len(payload)
    assert result["sha1"] == hashlib.sha1(payload).hexdigest()
    # it was a file in a directory of its own while the request ran, inside
    # the data directory's folder for temporary files ...
    upload_dir = os.path.dirname(result["path"])
    assert os.path.basename(upload_dir).startswith("upload-")
    assert os.path.dirname(upload_dir) == temporary_dir
    assert temporary_dir == os.path.join(
        dependencies.config.config["data_dir"], "temporary-uploads", ".tmp"
    )
    # ... and neither is left once the request is over
    assert not os.path.exists(result["path"])
    assert _all_removed(upload_dirs)
    assert _left_behind(temporary_dir) == []


def test_upload_directory_is_removed_when_the_endpoint_fails(
    client, upload_dirs, temporary_dir
):
    payload = os.urandom(2 * 1024 * 1024)
    response = client.post(
        "/echo/missing", **_multipart([("content", "big.bin", None, payload)])
    )
    assert response.status_code == 400
    assert response.json()["name"] == "MissingRequiredFileError"
    assert _all_removed(upload_dirs)
    assert _left_behind(temporary_dir) == []


def test_upload_directory_is_removed_when_the_body_is_malformed(
    client, upload_dirs, temporary_dir
):
    body = _multipart([("content", "big.bin", None, os.urandom(2 * 1024 * 1024))])
    # cut the body off in the middle of the file
    response = client.post(
        "/where/content",
        content=body["content"][: 1024 * 1024 + 500000],
        headers=body["headers"],
    )
    assert response.status_code == 400
    assert _all_removed(upload_dirs)
    assert _left_behind(temporary_dir) == []


def test_downloaded_file_is_removed_afterwards(client, temporary_dir):
    downloaded = content_module.Content.create_temporary()
    assert os.path.dirname(downloaded.path) == temporary_dir
    with downloaded.open_for_writing() as handle:
        handle.write(b"downloaded content")
    with patch("lithica.func.net.download", return_value=downloaded):
        response = client.post(
            "/where/content", json={"contentUrl": "http://example.com/file"}
        )
    assert response.json()["path"] == downloaded.path
    assert response.json()["size"] == 18
    assert not os.path.exists(downloaded.path)
    assert _left_behind(temporary_dir) == []


@pytest.fixture
def upload_limit(config_injector):
    def set_limit(limit):
        config_injector({"max_upload_size": limit})

    return set_limit


TOO_LARGE = {
    "name": "RequestTooLargeError",
    "title": "Payload Too Large",
    "description": "The request is larger than the maximum of 100000 bytes.",
}


def test_request_up_to_the_limit_is_accepted(client, upload_limit):
    body = _multipart([("content", "f.bin", None, b"x" * 50000)])
    upload_limit(len(body["content"]))
    response = client.post("/where/content", **body)
    assert response.status_code == 200
    assert response.json()["size"] == 50000


def test_request_over_the_limit_is_refused_by_its_declared_length(
    client, upload_limit, upload_dirs, temporary_dir
):
    upload_limit(100000)
    body = _multipart([("content", "f.bin", None, b"x" * 100000)])
    response = client.post("/where/content", **body)
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert _all_removed(upload_dirs)
    assert _left_behind(temporary_dir) == []


def test_request_over_the_limit_is_refused_while_it_arrives(
    client, upload_limit, upload_dirs, temporary_dir
):
    upload_limit(100000)
    body = _multipart([("content", "f.bin", None, os.urandom(5 * 1024 * 1024))])
    # no Content-Length: the server finds out only by counting
    response = client.post(
        "/where/content", content=_streamed(body["content"]), headers=body["headers"]
    )
    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert _all_removed(upload_dirs)
    assert _left_behind(temporary_dir) == []


def test_json_body_over_the_limit_is_refused(client, upload_limit):
    upload_limit(100000)
    response = client.post("/things", json={"source": "x" * 100000})
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    response = client.post(
        "/things",
        content=_streamed(json.dumps({"source": "x" * 100000}).encode()),
    )
    assert response.status_code == 413


def test_default_limit_applies_without_the_setting(client, config_injector):
    config_injector({})
    assert dependencies.max_upload_size() == 1024 * 1024 * 1024
    config_injector({"max_upload_size": None})
    assert dependencies.max_upload_size() == 1024 * 1024 * 1024
    assert client.post("/things", json={"safety": "safe"}).status_code == 200


def test_client_that_leaves_in_the_middle_of_its_request(
    client, upload_dirs, temporary_dir
):
    """The request ends as a refused one: no server error, nothing left on disk."""
    import asyncio

    body = _multipart([("content", "big.bin", None, os.urandom(2 * 1024 * 1024))])
    half = body["content"][: 1024 * 1024 + 300000]
    messages = [
        {"type": "http.request", "body": half, "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/where/content",
        "raw_path": b"/where/content",
        "root_path": "",
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "headers": [
            (b"accept", b"application/json"),
            (b"content-type", body["headers"]["Content-Type"].encode()),
        ],
    }
    # raises if the application lets the disconnect escape as an error
    asyncio.run(client.app(scope, receive, send))
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 400
    assert _all_removed(upload_dirs)
    assert _left_behind(temporary_dir) == []
