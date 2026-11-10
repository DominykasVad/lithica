from collections.abc import Callable
from typing import Any

from lithica import errors, model
from lithica.func import site_settings

# what a serializer gives: the fields of a resource, or nothing for no resource
Response = dict[str, Any] | None


class BaseSerializer:
    feature_resource = ""
    _fields: dict[str, Callable[[model.Base], Any]] = {}

    def serialize(self, options: list[str]) -> Any:
        field_factories = self._serializers()
        if not options:
            options = list(field_factories.keys())
        _check(options, list(field_factories))
        options = site_settings.active_fields(self.feature_resource, options)
        return {key: field_factories[key]() for key in options}

    @classmethod
    def field_names(cls) -> list[str]:
        """
        The fields this serializer knows, without a resource to serialize:
        the factories are bound methods, listed here and never called.
        """
        return list(cls.__new__(cls)._serializers())

    @classmethod
    def check_fields(cls, options: list[str]) -> None:
        """Refuses fields this serializer does not know, as serialize() would."""
        _check(options, cls.field_names())

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        raise NotImplementedError()


def _check(options: list[str], known: list[str]) -> None:
    for key in options:
        if key not in known:
            raise errors.ValidationError(
                "Invalid key: %r. Valid keys: %r." % (key, list(sorted(known)))
            )
