from collections.abc import Callable
from typing import Any

from lithica import errors, model

# what a serializer gives: the fields of a resource, or nothing for no resource
Response = dict[str, Any] | None


class BaseSerializer:
    _fields: dict[str, Callable[[model.Base], Any]] = {}

    def serialize(self, options: list[str]) -> Any:
        field_factories = self._serializers()
        if not options:
            options = list(field_factories.keys())
        ret = {}
        for key in options:
            if key not in field_factories:
                raise errors.ValidationError(
                    "Invalid key: %r. Valid keys: %r."
                    % (key, list(sorted(field_factories.keys())))
                )
            factory = field_factories[key]
            ret[key] = factory()
        return ret

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        raise NotImplementedError()
