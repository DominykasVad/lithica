"""
Types of the data the API accepts and returns.

The API has always been lenient about how a value is written: a number may
arrive as a string, a list as comma-separated text, a boolean as "yes". The
types below keep those rules, so a request model built from them accepts
what the old framework's `get_param_as_*` readers accepted and refuses what
they refused, with the same messages.
"""

from typing import Annotated, Any, LiteralString, Self

import pydantic
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

from lithica import errors
from lithica.api.error_handlers import PARAMETER_ERROR, parameter_error

TRUE_WORDS = ["1", "y", "yes", "yeah", "yep", "yup", "t", "true"]
FALSE_WORDS = ["0", "n", "no", "nope", "f", "false"]


def _refuse(problem: LiteralString) -> PydanticCustomError:
    # the message completes "Parameter 'x' ...", see error_handlers
    return PydanticCustomError(PARAMETER_ERROR, problem)


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if type(value) is list:
        try:
            return ",".join(value)
        except TypeError:
            pass
    if type(value) is int or type(value) is float:
        return str(value)
    if type(value) is str:
        return value
    raise _refuse("must be a string value")


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        raise _refuse("must be an integer value") from None


def _to_bool(value: Any) -> bool:
    text = str(value).lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise _refuse("must be a boolean value")


def _to_list(value: Any) -> list[Any]:
    if type(value) is str:
        return value.split(",") if "," in value else [value]
    if type(value) is list:
        return value
    raise _refuse("must be a list")


def _to_str_list(value: Any) -> list[str]:
    items = _to_list(value)
    if any(type(item) is not str for item in items):
        raise _refuse("must be a list of string values")
    return items


def _to_int_list(value: Any) -> list[int]:
    items = _to_list(value)
    if any(type(item) is not int for item in items):
        raise _refuse("must be a list of integer values")
    return items


Str = Annotated[str, BeforeValidator(_to_str)]
Int = Annotated[int, BeforeValidator(_to_int)]
Bool = Annotated[bool, BeforeValidator(_to_bool)]
# Any: the items are passed on as they came (post notes are objects)
AnyList = Annotated[list[Any], BeforeValidator(_to_list)]
StrList = Annotated[list[str], BeforeValidator(_to_str_list)]
IntList = Annotated[list[int], BeforeValidator(_to_int_list)]


# ---------------------------------------------------------------------------
# request models


REQUIRED_MARK = "x-lithica-required"


def required() -> Any:
    """
    Default of a request field the endpoint cannot do without.

    The field is not required by the model itself, because the old API
    reported a missing parameter only when the endpoint got to reading it:
    a request for a missing tag that also lacks `version` is "tag not
    found", not "version is missing". The endpoint reads such a field with
    `RequestModel.require()`. The OpenAPI schema lists the field as
    required, which is what a client needs to know.
    """
    return Field(default=None, json_schema_extra={REQUIRED_MARK: True})


class RequestModel(BaseModel):
    """
    Base of the request bodies. Field names are camelCase on the wire.
    Unknown fields are ignored, as they always were.
    """

    model_config = ConfigDict(alias_generator=to_camel, extra="ignore")

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> Self:
        try:
            return cls.model_validate(params)
        except pydantic.ValidationError as ex:
            raise parameter_error(ex.errors()) from ex

    def has(self, field: str) -> bool:
        """Whether the request carried this field at all (even as null)."""
        return field in self.model_fields_set

    # Any: the caller reads one named field; its type is the field's own
    def require(self, field: str) -> Any:
        """The value of a `required()` field, or the API's missing-parameter error."""
        if field not in self.model_fields_set:
            name = type(self).model_fields[field].alias or field
            raise errors.MissingRequiredParameterError(
                "Required parameter %r is missing." % name
            )
        return getattr(self, field)


def request_body(model: type[RequestModel], *files: str) -> dict[str, Any]:
    """
    Describe an endpoint's request body for the OpenAPI document; pass the
    result as `openapi_extra`. The body itself is read by
    `dependencies.body()`, not by FastAPI, because the API takes its JSON
    either as the body or as the `metadata` part of a multipart request
    whose other parts (`files`) are uploads.
    """
    schema = model.model_json_schema()
    assert "$defs" not in schema, "request models are flat"
    schema.pop("title", None)
    needed = list(schema.pop("required", []))
    for name, field in schema.get("properties", {}).items():
        field.pop("title", None)
        field.pop("default", None)
        if field.pop(REQUIRED_MARK, False):
            needed.append(name)
    if needed:
        schema["required"] = needed

    content: dict[str, Any] = {"application/json": {"schema": schema}}
    if files:
        parts: dict[str, Any] = {"metadata": schema}
        for name in files:
            parts[name] = {"type": "string", "format": "binary"}
        content["multipart/form-data"] = {
            "schema": {"type": "object", "properties": parts},
            "encoding": {"metadata": {"contentType": "application/json"}},
        }
    return {"requestBody": {"content": content}}


# ---------------------------------------------------------------------------
# response models


def _nothing_is_required(schema: dict[str, Any]) -> None:
    schema.pop("required", None)


class ResponseModel(BaseModel):
    """
    Base of the models that describe what the API returns.

    Why no field is marked as required: every resource endpoint takes a
    `fields` query parameter, and the response then holds only the fields
    that were asked for. A client generated from a schema that called a
    field required would reject such a response. So the models state each
    field's type truthfully (nullable only where the value can really be
    null) and the schema drops `required` for all of them.

    Why the endpoints do not return these models: the responses are built by
    the serializers in `lithica.func` and written by `JsonResponse`, exactly
    as before the move to FastAPI, so the wire format cannot drift. The
    models are the description of that output. The tests keep the two in
    step: they validate real, complete responses against the models, which
    forbid fields they do not know.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_nothing_is_required)


class ErrorResponse(BaseModel):
    """Body of every error response. Some errors add fields of their own."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Machine-readable name of the error.")
    title: str = Field(description="Short human-readable category.")
    description: str = Field(description="Human-readable explanation.")
