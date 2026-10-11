from typing import Any, cast

from lithica import errors, model
from lithica.func import file_uploads, net
from lithica.func.content import ContentLike

MISSING = object()
Request = dict[str, Any]
Response = dict[str, Any] | None


class Context:
    def __init__(
        self,
        env: dict[str, Any],
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: Request | None = None,
        files: dict[str, bytes] | None = None,
    ) -> None:
        self.env = env
        self.method = method
        self.url = url
        self._headers = headers or {}
        self._params = params or {}
        self._files = files or {}

        # an anonymous user until the authenticator says otherwise; the name
        # is left unset, which reads as None
        self.user = model.User()
        self.user.rank = "anonymous"

        self.session: Any = None

    def has_header(self, name: str) -> bool:
        return name in self._headers

    def get_header(self, name: str) -> str:
        return self._headers.get(name, "")

    def has_file(self, name: str, allow_tokens: bool = True) -> bool:
        return (
            name in self._files
            or name + "Url" in self._params
            or (allow_tokens and name + "Token" in self._params)
        )

    def get_file(
        self,
        name: str,
        default: object | bytes = MISSING,
        use_video_downloader: bool = False,
        allow_tokens: bool = True,
    ) -> ContentLike:
        if name in self._files and self._files[name]:
            return self._files[name]

        if name + "Url" in self._params:
            return net.download(
                self._params[name + "Url"],
                use_video_downloader=use_video_downloader,
            )

        if allow_tokens and name + "Token" in self._params:
            ret = file_uploads.get(self._params[name + "Token"])
            if ret:
                return ret
            elif default is not MISSING:
                raise errors.MissingOrExpiredRequiredFileError(
                    "Required file %r is missing or has expired." % name
                )

        if default is not MISSING:
            return cast(bytes, default)
        raise errors.MissingRequiredFileError("Required file %r is missing." % name)

    def has_param(self, name: str) -> bool:
        return name in self._params

    def get_param_as_list(
        self, name: str, default: object | list[Any] = MISSING
    ) -> list[Any]:
        if name not in self._params:
            if default is not MISSING:
                return cast(list[Any], default)
            raise errors.MissingRequiredParameterError(
                "Required parameter %r is missing." % name
            )
        value = self._params[name]
        if type(value) is str:
            if "," in value:
                return value.split(",")
            return [value]
        if type(value) is list:
            return value
        raise errors.InvalidParameterError("Parameter %r must be a list." % name)

    def get_param_as_int_list(
        self, name: str, default: object | list[int] = MISSING
    ) -> list[int]:
        ret = self.get_param_as_list(name, default)
        for item in ret:
            if type(item) is not int:
                raise errors.InvalidParameterError(
                    "Parameter %r must be a list of integer values." % name
                )
        return ret

    def get_param_as_string_list(
        self, name: str, default: object | list[str] = MISSING
    ) -> list[str]:
        ret = self.get_param_as_list(name, default)
        for item in ret:
            if type(item) is not str:
                raise errors.InvalidParameterError(
                    "Parameter %r must be a list of string values." % name
                )
        return ret

    def get_param_as_string(self, name: str, default: object | str = MISSING) -> str:
        if name not in self._params:
            if default is not MISSING:
                return cast(str, default)
            raise errors.MissingRequiredParameterError(
                "Required parameter %r is missing." % name
            )
        value = self._params[name]
        try:
            if value is None:
                return ""
            if type(value) is list:
                return ",".join(value)
            if type(value) is int or type(value) is float:
                return str(value)
            if type(value) is str:
                return value
        except TypeError:
            pass
        raise errors.InvalidParameterError(
            "Parameter %r must be a string value." % name
        )

    def get_param_as_int(
        self,
        name: str,
        default: object | int = MISSING,
        min: int | None = None,
        max: int | None = None,
    ) -> int:
        if name not in self._params:
            if default is not MISSING:
                return cast(int, default)
            raise errors.MissingRequiredParameterError(
                "Required parameter %r is missing." % name
            )
        value = self._params[name]
        try:
            value = int(value)
            if min is not None and value < min:
                raise errors.InvalidParameterError(
                    "Parameter %r must be at least %r." % (name, min)
                )
            if max is not None and value > max:
                raise errors.InvalidParameterError(
                    "Parameter %r may not exceed %r." % (name, max)
                )
            return value
        except (ValueError, TypeError):
            pass
        raise errors.InvalidParameterError(
            "Parameter %r must be an integer value." % name
        )

    def get_param_as_bool(self, name: str, default: object | bool = MISSING) -> bool:
        if name not in self._params:
            if default is not MISSING:
                return cast(bool, default)
            raise errors.MissingRequiredParameterError(
                "Required parameter %r is missing." % name
            )
        value = self._params[name]
        try:
            value = str(value).lower()
        except TypeError:
            pass
        if value in ["1", "y", "yes", "yeah", "yep", "yup", "t", "true"]:
            return True
        if value in ["0", "n", "no", "nope", "f", "false"]:
            return False
        raise errors.InvalidParameterError(
            "Parameter %r must be a boolean value." % name
        )
