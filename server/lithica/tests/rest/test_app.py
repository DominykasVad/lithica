import io
import json
from typing import Any

import pytest

from lithica.rest import app, errors

BOUNDARY = "----lithicatestboundary"

# (field name, file name or None, content type or None, payload)
Part = tuple[str, str | None, str | None, bytes]


def _multipart_body(parts: list[Part]) -> bytes:
    body = b""
    for name, file_name, content_type, payload in parts:
        disposition = 'form-data; name="%s"' % name
        if file_name is not None:
            disposition += '; filename="%s"' % file_name
        body += ("--%s\r\n" % BOUNDARY).encode()
        body += ("Content-Disposition: %s\r\n" % disposition).encode()
        if content_type is not None:
            body += ("Content-Type: %s\r\n" % content_type).encode()
        body += b"\r\n" + payload + b"\r\n"
    body += ("--%s--\r\n" % BOUNDARY).encode()
    return body


def _env(
    body: bytes, content_type: str | None, query_string: str = ""
) -> dict[str, Any]:
    env: dict[str, Any] = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/posts",
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_ACCEPT": "application/json",
        "wsgi.input": io.BytesIO(body),
    }
    if content_type is not None:
        env["CONTENT_TYPE"] = content_type
    return env


def _multipart_env(parts: list[Part], query_string: str = "") -> dict[str, Any]:
    return _env(
        _multipart_body(parts),
        "multipart/form-data; boundary=%s" % BOUNDARY,
        query_string,
    )


def test_json_body():
    ctx = app._create_context(
        _env(b'{"tags": ["a", "b"], "safety": "safe"}', "application/json")
    )
    assert ctx.get_param_as_string_list("tags") == ["a", "b"]
    assert ctx.get_param_as_string("safety") == "safe"
    assert not ctx.has_file("content")


def test_invalid_json_body():
    with pytest.raises(errors.HttpBadRequest):
        app._create_context(_env(b"{not json", "application/json"))


def test_multipart_with_metadata_field():
    ctx = app._create_context(
        _multipart_env(
            [
                ("metadata", None, None, b'{"safety": "safe"}'),
                ("content", "image.png", "image/png", b"\x89PNG-content"),
            ]
        )
    )
    assert ctx.get_param_as_string("safety") == "safe"
    assert ctx.get_file("content") == b"\x89PNG-content"


def test_multipart_with_metadata_blob():
    # browsers send the JSON part as a Blob, which carries a file name
    ctx = app._create_context(
        _multipart_env(
            [
                ("metadata", "blob", "application/json", b'{"safety": "safe"}'),
                ("content", "image.png", "image/png", b"content"),
                ("thumbnail", "thumb.jpg", "image/jpeg", b"thumbnail"),
            ]
        )
    )
    assert ctx.get_param_as_string("safety") == "safe"
    assert ctx.get_file("content") == b"content"
    assert ctx.get_file("thumbnail") == b"thumbnail"


def test_multipart_non_ascii_metadata():
    metadata = json.dumps({"source": "zażółć"}, ensure_ascii=False)
    ctx = app._create_context(
        _multipart_env(
            [
                ("metadata", None, None, metadata.encode("utf-8")),
                ("content", "image.png", "image/png", b"content"),
            ]
        )
    )
    assert ctx.get_param_as_string("source") == "zażółć"


def test_multipart_file_content_is_byte_exact():
    payload = bytes(range(256)) + b"\r\n--not-the-boundary\r\n" + b"\x00\xff"
    ctx = app._create_context(
        _multipart_env([("content", "data.bin", "application/octet-stream", payload)])
    )
    assert ctx.get_file("content") == payload


def test_multipart_large_file():
    payload = b"0123456789abcdef" * (3 * 1024 * 1024 // 16)
    ctx = app._create_context(
        _multipart_env([("content", "big.bin", "video/mp4", payload)])
    )
    assert ctx.get_file("content") == payload


def test_multipart_without_metadata_keeps_query_params():
    ctx = app._create_context(
        _multipart_env(
            [("content", "image.png", "image/png", b"content")],
            query_string="fields=id",
        )
    )
    assert ctx.get_param_as_string("fields") == "id"
    assert ctx.get_file("content") == b"content"


def test_multipart_invalid_metadata():
    with pytest.raises(errors.HttpBadRequest):
        app._create_context(
            _multipart_env(
                [
                    ("metadata", None, None, b"{not json"),
                    ("content", "image.png", "image/png", b"content"),
                ]
            )
        )


def test_multipart_without_parts():
    with pytest.raises(errors.HttpBadRequest) as ex:
        app._create_context(_multipart_env([]))
    assert ex.value.description == "No files attached."


def test_multipart_malformed_body():
    env = _env(b"this is not multipart", "multipart/form-data")
    with pytest.raises(errors.HttpBadRequest):
        app._create_context(env)


def _call(env: dict[str, Any]) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = app.application(env, start_response)
    return captured["status"], captured["headers"], b"".join(body)


def _get_env(origin: str | None = None) -> dict[str, Any]:
    env: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/no-such-path",
        "QUERY_STRING": "",
        "HTTP_ACCEPT": "application/json",
        "wsgi.input": io.BytesIO(b""),
    }
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    return env


def _preflight_env(origin: str) -> dict[str, Any]:
    env = _get_env(origin)
    env["REQUEST_METHOD"] = "OPTIONS"
    env["HTTP_ACCESS_CONTROL_REQUEST_METHOD"] = "POST"
    del env["HTTP_ACCEPT"]
    return env


@pytest.mark.parametrize("cors_origins", [[], None])
def test_no_cors_headers_by_default(config_injector, cors_origins):
    config_injector({"cors_origins": cors_origins})
    status, headers, _body = _call(_get_env("https://other.example.com"))
    assert status.startswith("404")
    assert "Access-Control-Allow-Origin" not in headers
    assert "Vary" not in headers


def test_no_cors_headers_without_the_setting(config_injector):
    config_injector({})
    _status, headers, _body = _call(_get_env("https://other.example.com"))
    assert "Access-Control-Allow-Origin" not in headers


def test_preflight_is_not_answered_by_default(config_injector):
    config_injector({"cors_origins": []})
    status, headers, _body = _call(_preflight_env("https://other.example.com"))
    assert not status.startswith("200")
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Methods" not in headers


def test_cors_headers_for_listed_origin(config_injector):
    config_injector(
        {"cors_origins": ["https://app.example.com", "https://b.example.com"]}
    )
    status, headers, _body = _call(_get_env("https://b.example.com"))
    # the headers are sent on error responses too, or the client could not
    # read the error
    assert status.startswith("404")
    assert headers["Access-Control-Allow-Origin"] == "https://b.example.com"
    assert headers["Vary"] == "Origin"
    assert headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example.com",
        "http://app.example.com",
        "https://app.example.com.evil.example.com",
        "https://app.example.com:8443",
        "null",
        "*",
    ],
)
def test_no_cors_headers_for_unlisted_origin(config_injector, origin):
    config_injector({"cors_origins": ["https://app.example.com"]})
    _status, headers, _body = _call(_get_env(origin))
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Vary"] == "Origin"


def test_no_allow_origin_without_origin_header(config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    _status, headers, _body = _call(_get_env())
    assert "Access-Control-Allow-Origin" not in headers


def test_preflight_for_listed_origin(config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    status, headers, body = _call(_preflight_env("https://app.example.com"))
    assert status == "200"
    assert body == b""
    assert headers["Access-Control-Allow-Origin"] == "https://app.example.com"
    assert headers["Access-Control-Allow-Methods"] == (
        "GET, POST, PUT, DELETE, OPTIONS"
    )
    assert headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type"


def test_preflight_for_unlisted_origin(config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    status, headers, _body = _call(_preflight_env("https://evil.example.com"))
    assert not status.startswith("200")
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Methods" not in headers
