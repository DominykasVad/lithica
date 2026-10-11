import json
from datetime import datetime
from typing import Any

from starlette.responses import Response


def _serialize_default(obj: Any) -> str:
    """Encode what the json module does not know: timestamps."""
    if isinstance(obj, datetime):
        # timestamps are naive UTC throughout; the wire format says so
        return obj.isoformat("T") + "Z"
    raise TypeError("Type not serializable")


def dump_json(obj: Any) -> str:
    return json.dumps(obj, default=_serialize_default, indent=2)


class JsonResponse(Response):
    """
    The API's JSON response. It writes exactly what the old framework wrote
    (timestamps as naive UTC with a "Z", two-space indentation), which is why
    the endpoints do not use FastAPI's own JSON encoding.
    """

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return dump_json(content).encode("utf-8")
