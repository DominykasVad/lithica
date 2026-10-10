import io
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from lithica.rest import app, errors

BOUNDARY = "----lithicatestboundary"

# (field name, file name or None, content type or None, payload)
Part = Tuple[str, Optional[str], Optional[str], bytes]


def _multipart_body(parts: List[Part]) -> bytes:
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
    body: bytes, content_type: Optional[str], query_string: str = ""
) -> Dict[str, Any]:
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/posts",
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_ACCEPT": "application/json",
        "wsgi.input": io.BytesIO(body),
    }  # type: Dict[str, Any]
    if content_type is not None:
        env["CONTENT_TYPE"] = content_type
    return env


def _multipart_env(parts: List[Part], query_string: str = "") -> Dict[str, Any]:
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
        _multipart_env(
            [("content", "data.bin", "application/octet-stream", payload)]
        )
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
