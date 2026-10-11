"""
Types of the data the API accepts.

The API has always been lenient about how a value is written: a number may
arrive as a string, a list as comma-separated text, a boolean as "yes". The
types below keep those rules, so a request model built from them accepts
what the old framework's `get_param_as_*` readers accepted and refuses what
they refused, with the same messages.
"""

from typing import Annotated, Any, LiteralString

from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError

from lithica.api.error_handlers import PARAMETER_ERROR

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
