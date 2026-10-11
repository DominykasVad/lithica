from typing import Any

import pytest

from lithica import errors
from lithica.api.schemas import (
    AnyList,
    Bool,
    Int,
    IntList,
    RequestModel,
    ResponseModel,
    Str,
    StrList,
    request_body,
    required,
)


class _Params(RequestModel):
    text: Str = ""
    number: Int = 5
    flag: Bool = True
    items: AnyList = []
    names: StrList = []
    numbers: IntList = []
    content_url: Str = ""
    version: Int = required()


def _read(**params: Any) -> _Params:
    return _Params.from_params(params)


def _refused(description: str, **params: Any) -> None:
    """Reading the (first) given parameter is refused with this description."""
    wire_name = next(iter(params))
    field = {"contentUrl": "content_url"}.get(wire_name, wire_name)
    read = _read(**params)
    with pytest.raises(errors.InvalidParameterError) as ex:
        getattr(read, field)
    assert str(ex.value) == description


def test_defaults():
    params = _read()
    assert params.text == ""
    assert params.number == 5
    assert params.flag is True
    assert params.items == [] and params.names == [] and params.numbers == []


def test_string():
    assert _read(text="value").text == "value"
    assert _read(text=["1", "2", "3"]).text == "1,2,3"
    assert _read(text=5).text == "5"
    assert _read(text=1.5).text == "1.5"
    assert _read(text=None).text == ""
    _refused("Parameter 'text' must be a string value.", text={"a": 1})
    _refused("Parameter 'text' must be a string value.", text=[1, 2])
    _refused("Parameter 'text' must be a string value.", text=True)


def test_integer():
    assert _read(number="50").number == 50
    assert _read(number=50).number == 50
    assert _read(number=-3).number == -3
    _refused("Parameter 'number' must be an integer value.", number="invalid")
    _refused("Parameter 'number' must be an integer value.", number=[1, 2, 3])
    _refused("Parameter 'number' must be an integer value.", number=None)


@pytest.mark.parametrize(
    "value", ["1", "y", "yes", "yep", "yup", "yeah", "t", "true", "TRUE", True, 1]
)
def test_true(value):
    assert _read(flag=value).flag is True


@pytest.mark.parametrize(
    "value", ["0", "n", "no", "nope", "f", "false", "FALSE", False, 0]
)
def test_false(value):
    assert _read(flag=value).flag is False


@pytest.mark.parametrize("value", ["herp", "2", ["1", "2"], None])
def test_not_a_boolean(value):
    _refused("Parameter 'flag' must be a boolean value.", flag=value)


def test_list():
    assert _read(items="value").items == ["value"]
    assert _read(items="a,b").items == ["a", "b"]
    assert _read(items=["1", 2, {"x": 1}]).items == ["1", 2, {"x": 1}]
    _refused("Parameter 'items' must be a list.", items=5)
    _refused("Parameter 'items' must be a list.", items=None)


def test_string_list():
    assert _read(names=["1", "2", "3"]).names == ["1", "2", "3"]
    assert _read(names="a,b").names == ["a", "b"]
    _refused("Parameter 'names' must be a list of string values.", names=["a", 1])
    _refused("Parameter 'names' must be a list.", names=5)


def test_integer_list():
    assert _read(numbers=[1, 2, 3]).numbers == [1, 2, 3]
    _refused("Parameter 'numbers' must be a list of integer values.", numbers=[1, "2"])
    # text is split into strings, and strings are not integers
    _refused("Parameter 'numbers' must be a list of integer values.", numbers="1,2")


def test_fields_are_camel_case_on_the_wire():
    assert _read(contentUrl="http://example.com").content_url == "http://example.com"
    # the python name is not a wire name
    assert _read(content_url="http://example.com").content_url == ""
    _refused("Parameter 'contentUrl' must be a string value.", contentUrl={})


def test_unknown_fields_are_ignored():
    assert _read(unknown="x", text="t").text == "t"


def test_unreadable_value_is_reported_when_it_is_read():
    # the request is accepted; the endpoint may refuse it for another reason
    # before it gets to the value
    params = _read(text={}, number="x", flag="yes", names=["a"])
    assert params.flag is True
    assert params.names == ["a"]
    assert params.has("text") and params.has("number")
    with pytest.raises(errors.InvalidParameterError, match="'text' must be a string"):
        getattr(params, "text")  # noqa: B009  (the read is the test)
    with pytest.raises(errors.InvalidParameterError, match="'number' must be an int"):
        params.require("number")
    # and again, every time
    with pytest.raises(errors.InvalidParameterError, match="'text' must be a string"):
        getattr(params, "text")  # noqa: B009


def test_unknown_attribute_is_still_an_attribute_error():
    with pytest.raises(AttributeError):
        getattr(_read(), "no_such_field")  # noqa: B009
    with pytest.raises(AttributeError):
        getattr(_read(text={}), "no_such_field")  # noqa: B009


def test_has():
    params = _read(text=None)
    assert params.has("text")
    assert not params.has("number")
    assert not params.has("version")


def test_require():
    assert _read(version="3").require("version") == 3
    with pytest.raises(errors.MissingRequiredParameterError) as ex:
        _read().require("version")
    assert str(ex.value) == "Required parameter 'version' is missing."
    with pytest.raises(errors.MissingRequiredParameterError) as ex:
        _read().require("content_url")
    assert str(ex.value) == "Required parameter 'contentUrl' is missing."
    # a required field is still checked when it is there
    _refused("Parameter 'version' must be an integer value.", version="x")


def test_request_body_schema():
    described = request_body(_Params)
    assert list(described["requestBody"]["content"]) == ["application/json"]
    schema = described["requestBody"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["version"]
    assert schema["properties"]["version"] == {"type": "integer"}
    assert schema["properties"]["contentUrl"] == {"type": "string"}
    assert schema["properties"]["flag"] == {"type": "boolean"}
    assert schema["properties"]["names"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schema["properties"]["numbers"]["items"] == {"type": "integer"}
    assert "content_url" not in schema["properties"]


def test_request_body_schema_with_files():
    described = request_body(_Params, "content", "thumbnail")
    content = described["requestBody"]["content"]
    assert list(content) == ["application/json", "multipart/form-data"]
    multipart = content["multipart/form-data"]
    assert (
        multipart["schema"]["properties"]["metadata"]
        == (content["application/json"]["schema"])
    )
    assert multipart["schema"]["properties"]["content"] == {
        "type": "string",
        "format": "binary",
    }
    assert "thumbnail" in multipart["schema"]["properties"]
    assert multipart["encoding"] == {"metadata": {"contentType": "application/json"}}


class _Thing(ResponseModel):
    id: int
    note: str | None


def test_response_model_requires_nothing_in_the_schema():
    schema = _Thing.model_json_schema()
    assert "required" not in schema
    assert schema["properties"]["id"]["type"] == "integer"
    assert schema["properties"]["note"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]


def test_response_model_forbids_unknown_fields():
    import pydantic

    _Thing.model_validate({"id": 1, "note": None})
    with pytest.raises(pydantic.ValidationError):
        _Thing.model_validate({"id": 1, "note": None, "new": 1})
